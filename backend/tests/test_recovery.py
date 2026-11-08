"""L11: the real loop, local detail hydration, and explicit confirmation taps."""

from datetime import datetime

import pytest

from app import contracts as c
from app.agent import loop
from app.agent.registry import ToolCall
from app.errors import NotFoundError
from app.state import JobRunner, StateStore
from tests.agent_input_factory import make_input
from tests.test_loop import FakeChat, FakeTools, GOOD_FINAL, final_turn, tools_turn
from tests.test_state import MSG, RESULT


def recovery_input(linked=True):
    ai = make_input()
    return ai.model_copy(update={
        "mode": c.AgentMode.recovery, "since": ai.received_at,
        "customer_context": c.CustomerContext(linked_bank=linked, linked_institutions=["Capital One"] if linked else []),
    })


class RecoveryTools(FakeTools):
    def __init__(self, flagged=True, fail=False):
        super().__init__()
        self.flagged, self.failed = flagged, fail

    def __call__(self, name, args, agent_input, on_call=None):
        if name != "nessie_recent_activity":
            return super().__call__(name, args, agent_input, on_call=on_call)
        self.called.append((name, args))
        if self.failed:
            return ToolCall(name=name, args=args, ok=False, error={"type": "timeout", "message": "Unavailable"})
        return ToolCall(name=name, args=args, ok=True, result={
            "accounts_checked": 2, "items_checked": 1,
            "flagged": [{"ref": "txn_28", "type": "purchase", "amount": 900,
                         "new_payee": True, "minutes_after_message": 17, "reason": "first purchase at this merchant"}]
            if self.flagged else [],
        })


@pytest.mark.parametrize("provider_fails", [False, True])
def test_recovery_finds_verified_refs_even_if_model_omits_them_or_fails(provider_fails):
    ai = recovery_input()
    chat = FakeChat(RuntimeError("provider unavailable")) if provider_fails else FakeChat(final_turn(GOOD_FINAL))
    tools, trail = RecoveryTools(), []
    result = loop.run_agent(ai, trail.append, chat=chat, call_tool=tools, tool_schemas=[])
    assert result.was_this_you == ["txn_28"] and result.replan
    assert result.actions == [c.Action.freeze_card, c.Action.call_number_on_card, c.Action.change_password]
    assert tools.called[0] == ("nessie_recent_activity", {"since": ai.received_at.isoformat()})
    assert result.plan[0] == c.ToolName.nessie_recent_activity
    assert [entry.step for entry in trail] == list(range(1, len(trail) + 1))
    assert trail[0].kind == c.TrailKind.plan and trail[-1].kind == c.TrailKind.verdict
    assert any(entry.kind == c.TrailKind.replan for entry in trail)
    if provider_fails:
        assert result.verdict == c.Verdict.unsure


@pytest.mark.parametrize("flagged,failed", [(False, False), (True, True)])
def test_empty_or_failed_bank_check_drops_invented_refs(flagged, failed):
    tools = RecoveryTools(flagged=flagged, fail=failed)
    result = loop.run_agent(recovery_input(), lambda _: None,
                            chat=FakeChat(final_turn({**GOOD_FINAL, "was_this_you": ["invented", "txn_28"]})),
                            call_tool=tools, tool_schemas=[])
    assert result.was_this_you == []
    assert c.Action.freeze_card not in result.actions


def test_recovery_time_window_cannot_be_changed_by_the_model():
    ai, tools = recovery_input(), RecoveryTools()
    chat = FakeChat(tools_turn(("nessie_recent_activity", {"days": 90})), final_turn(GOOD_FINAL))
    result = loop.run_agent(ai, lambda _: None, chat=chat, call_tool=tools, tool_schemas=[])
    assert result.was_this_you == ["txn_28"]  # duplicate tool results don't duplicate cards
    assert all(args == {"since": ai.received_at.isoformat()} for name, args in tools.called if name == "nessie_recent_activity")


def test_unlinked_recovery_never_reads_bank_or_accepts_model_refs():
    tools = RecoveryTools()
    chat = FakeChat(tools_turn(("nessie_recent_activity", {"days": 7})),
                    final_turn({**GOOD_FINAL, "was_this_you": ["txn_28"]}))
    result = loop.run_agent(recovery_input(False), lambda _: None, chat=chat, call_tool=tools, tool_schemas=[])
    assert not tools.called and not result.was_this_you


def test_conflicting_ignore_action_is_removed():
    from app.agent.guardrails import enforce
    result = enforce(c.AgentResult.model_validate({**GOOD_FINAL, "actions": ["block_sender", "ignore"]}), make_input().classifier)
    assert result.actions == [c.Action.block_sender]


def detail(ref="txn_28"):
    return c.WasThisYouItem(ref=ref, type="purchase", amount=900, payee="Synthetic Merchant",
                           at=datetime.fromisoformat("2026-11-08T09:31:00-06:00"))


def test_runner_resolves_details_only_for_the_customer(monkeypatch):
    from app.tools import nessie_tools
    resolved = []
    def resolve(ref):
        resolved.append(ref)
        return detail(ref)
    monkeypatch.setattr(nessie_tools, "resolve_ref", resolve)
    store = StateStore()
    runner = JobRunner(store)
    try:
        mid = store.add_message(MSG)
        runner.submit(mid, lambda *args: RESULT.model_copy(update={"was_this_you": ["txn_28"]}), mode=c.AgentMode.recovery).result(5)
        poll = store.poll(mid)
        assert poll.was_this_you_items == [detail()] and resolved == ["txn_28"]
        assert "Synthetic Merchant" not in poll.result.model_dump_json()
        assert store._db.execute("SELECT COUNT(*) FROM confirmations").fetchone()[0] == 0
        assert store.confirm_transaction("txn_28", False).recorded
        assert store._db.execute("SELECT was_me FROM confirmations").fetchone()[0] == 0
        store.confirm_transaction("txn_28", True)
        assert store._db.execute("SELECT COUNT(*), MAX(was_me) FROM confirmations").fetchone()[0] == 1
        assert store._db.execute("SELECT was_me FROM confirmations").fetchone()[0] == 1
        store.start_run(mid, c.AgentMode.recovery)
        with pytest.raises(NotFoundError):
            store.confirm_transaction("txn_28", False)
        store.reset()
        assert store._db.execute("SELECT COUNT(*) FROM confirmations").fetchone()[0] == 0
    finally:
        runner.shutdown()
        store.close()


def test_confirm_route_only_accepts_items_from_a_finished_recovery(make_client):
    client = make_client(USE_MOCKS=False, DEMO_MODE="replay", PHONE_HASH_SALT="test-salt")
    assert client.post("/api/transactions/invented/confirm", json={"was_me": False}).status_code == 404
    store = client.app.state.store
    mid = store.add_message(MSG)
    run = store.start_run(mid, c.AgentMode.recovery)
    store.set_was_this_you(mid, run, [detail()])
    assert client.post("/api/transactions/txn_28/confirm", json={"was_me": False}).status_code == 404
    store.finish(mid, run, RESULT.model_copy(update={"was_this_you": ["txn_28"]}))
    response = client.post("/api/transactions/txn_28/confirm", json={"was_me": False})
    assert response.status_code == 200 and response.json() == {"ref": "txn_28", "was_me": False, "recorded": True}


def test_clicked_route_runs_recovery_and_polls_app_only_details(make_client, monkeypatch):
    import json
    from app import main
    from app.tools import nessie_tools

    chat = FakeChat(final_turn(GOOD_FINAL))
    def job(mid, message, trail):
        assert message.mode == c.AgentMode.recovery
        ai = recovery_input().model_copy(update={"message_id": mid})
        return loop.run_agent(ai, trail, chat=chat, call_tool=RecoveryTools(), tool_schemas=[])
    monkeypatch.setattr(main, "pipeline_job", job)
    monkeypatch.setattr(nessie_tools, "resolve_ref", lambda ref: detail(ref))
    client = make_client(USE_MOCKS=False, DEMO_MODE="replay", PHONE_HASH_SALT="test-salt")
    store = client.app.state.store
    mid = store.add_message(MSG)
    assert store.poll(mid).was_this_you_items == []
    response = client.post(f"/api/messages/{mid}/clicked")
    assert response.status_code == 200 and response.json()["mode"] == "recovery"
    from tests.test_state import wait_done
    poll = wait_done(store, mid)
    assert poll.result.was_this_you == ["txn_28"] and poll.was_this_you_items == [detail()]
    assert client.get(f"/api/messages/{mid}/result").json()["was_this_you_items"][0]["amount"] == 900
    assert "Synthetic Merchant" not in json.dumps(chat.requests)
    assert store._db.execute("SELECT COUNT(*) FROM confirmations").fetchone()[0] == 0
    client.app.state.runner.shutdown()
