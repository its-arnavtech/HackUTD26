"""L6: privacy audit log and GET /api/privacy/{id}.

Scenario 1's message (synthetic) runs with real redaction (A3) and the real
agent input builder; tools are canned so nothing calls out.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import time
from datetime import datetime

import pytest

from app import contracts as c
from app import privacy_log
from app.agent.registry import ToolRegistry, builtin_tools
from app.privacy.redact import redact
from app.privacy_log import ACCOUNT_NUMBERS, FULL_LINK, HISTORY, NAME, ORIGINAL_TEXT, PHONE_NUMBERS, SENDER_NUMBER, PrivacyLog
from app.state import JobRunner, StateStore
from scripts import run_scenario as rs

SCENARIO = rs.load_scenario(1)
TEXT = SCENARIO["message"]["text"]
SENDER = SCENARIO["message"]["sender"]  # +15550104477, synthetic
RAW_LINK = "https://capone-verify-alert.com/verify"
MSG = c.MessageIn(text=TEXT, sender=SENDER, received_at=datetime.fromisoformat(SCENARIO["message"]["received_at"]))

CANNED = {
    c.ToolName.check_link: c.CheckLinkResult(domain="capone-verify-alert.com", domain_age_days=3, on_blocklist=False, lookalike_of="capitalone.com", signals=[]),
    c.ToolName.check_sender: c.CheckSenderResult(sender_type=c.SenderType.long_code, matches_official_channel=False, official_channels_known=True, note="n"),
    c.ToolName.nessie_recent_activity: c.NessieRecentActivityResult(accounts_checked=2, items_checked=6, flagged=[]),
}
RESULT = c.AgentResult(plan=list(CANNED), verdict=c.Verdict.likely_scam, confidence_words=c.ConfidenceWords.very_likely, reason="r")


@pytest.fixture(autouse=True)
def phone_salt(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("PHONE_HASH_SALT", "synthetic-test-salt")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def reg():
    """The real tool specs (names, args, reads, injected fields) with canned results."""
    r = ToolRegistry()
    for spec in builtin_tools():
        value = CANNED.get(spec.name)
        r.register(dataclasses.replace(spec, fn=(lambda v: lambda args, ai: v)(value) if value else _unavailable))
    yield r
    r.shutdown()


def _unavailable(args, agent_input):
    raise NotImplementedError


def agent_input(mode: c.AgentMode = c.AgentMode.check) -> c.AgentInput:
    return rs.build_agent_input(rs.Run(scenario=SCENARIO, mode=mode))


def pipeline(reg: ToolRegistry, leak: str | None = None):
    """A stand-in for L9 + L8 that records the way they will (see privacy_log's docstring)."""

    def job(message_id, message, on_trail):
        redacted = redact(message.text)
        privacy_log.record_redaction(redacted)
        ai = agent_input(message.mode)
        privacy_log.record_local("classifier", {"text_redacted": ai.text_redacted, "features": ai.features.model_dump(mode="json")})
        payload = ai.model_dump(mode="json", exclude_none=True)
        if leak:
            payload["note"] = leak
        privacy_log.record_model("nemotron", payload)
        calls = [("check_link", {"url_id": "URL_1"}), ("check_sender", {"claimed_brand": "Capital One"}), ("nessie_recent_activity", {"days": 7})]
        for name, args in calls:
            call = reg.call(name, args, ai)
            privacy_log.record_tool_result("nemotron", call.to_tool_message())
            on_trail.add(c.TrailKind.tool, tool=c.ToolName(name), finding="x")
        return RESULT

    return job


def wait_done(get, mid):
    deadline = time.monotonic() + 5
    while (poll := get(mid))["status"] != "done":
        assert time.monotonic() < deadline
        time.sleep(0.01)
    return poll


# --- end to end through the API ----------------------------------------------------------

LIVE = "inbox,post_message,result,clicked,demo_reset,privacy"


@pytest.fixture
def client(make_client, monkeypatch, reg):
    from app import main

    monkeypatch.setattr(main, "pipeline_job", pipeline(reg))
    return make_client(DEMO_MODE="replay", LIVE_ROUTES=LIVE)


def post(client) -> str:
    body = {"text": TEXT, "sender": SENDER, "received_at": SCENARIO["message"]["received_at"]}
    mid = client.post("/api/messages", json=body).json()["message_id"]
    wait_done(lambda m: client.get(f"/api/messages/{m}/result").json(), mid)
    return mid


def test_privacy_route_shows_redaction_and_every_recipient(client):
    mid = post(client)
    r = client.get(f"/api/privacy/{mid}")
    assert r.status_code == 200
    view = c.PrivacyView.model_validate(r.json())

    assert view.message_id == mid
    assert view.redaction.counts.PERSON == 1
    assert [(x.recipient, x.kind) for x in view.recipients] == [
        ("classifier", "local"),
        ("nemotron", "model"),
        ("check_link", "tool"),
        ("check_sender", "tool"),
        ("nessie_recent_activity", "tool"),
    ]
    by_name = {x.recipient: x for x in view.recipients}

    # Nemotron: the agent input, plus every tool result sent back to it, in one entry.
    nemo = by_name["nemotron"]
    assert nemo.payload["text_redacted"].startswith("Capital One Alert: unusual sign-in for <PERSON>.")
    assert [m["tool"] for m in nemo.payload["tool_results"]] == ["check_link", "check_sender", "nessie_recent_activity"]
    assert nemo.received_fields[-1] == "tool_results"

    # Tools: the validated arguments plus the agent-input fields each one reads.
    link = by_name["check_link"]
    assert link.received_fields == ["url_id", "urls"]
    assert link.payload["url_id"] == "URL_1" and link.payload["urls"][0]["registered_domain"] == "capone-verify-alert.com"
    assert by_name["check_sender"].received_fields == ["claimed_brand", "sender"]
    assert by_name["nessie_recent_activity"].received_fields == ["days", "customer_context"]
    assert all(x.at is not None for x in view.recipients)

    assert view.never_sent == [NAME, ACCOUNT_NUMBERS, ORIGINAL_TEXT, SENDER_NUMBER, FULL_LINK, HISTORY]

    # The response itself carries none of what redaction hid.
    raw = r.text
    assert "Linda" not in raw and RAW_LINK not in raw and "5550104477" not in raw and "raw_urls" not in raw


def test_recovery_run_is_added_and_reset_clears(client):
    mid = post(client)
    first = len(client.get(f"/api/privacy/{mid}").json()["recipients"])
    client.post(f"/api/messages/{mid}/clicked")
    wait_done(lambda m: client.get(f"/api/messages/{m}/result").json(), mid)
    view = client.get(f"/api/privacy/{mid}").json()
    assert len(view["recipients"]) == 2 * first  # both runs: the audit log keeps what each run sent
    recovery_nemotron = [r for r in view["recipients"] if r["recipient"] == "nemotron"][1]
    assert recovery_nemotron["payload"]["mode"] == "recovery"
    assert len(recovery_nemotron["payload"]["tool_results"]) == 3  # merged per run, not across runs

    client.post("/api/demo/reset")
    assert client.get(f"/api/privacy/{mid}").status_code == 404


def test_unknown_message_is_404(client):
    r = client.get("/api/privacy/msg_9999")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


def test_mocked_route_still_serves_the_mock(make_client):
    client = make_client()
    assert client.get("/api/privacy/msg_0001").json()["recipients"][0]["recipient"] == "classifier"


def test_a_leaked_link_is_not_claimed_as_never_sent(make_client, monkeypatch, reg, caplog):
    from app import main

    monkeypatch.setattr(main, "pipeline_job", pipeline(reg, leak=f"see {RAW_LINK}"))
    client = make_client(DEMO_MODE="replay", LIVE_ROUTES=LIVE)
    mid = post(client)
    with caplog.at_level(logging.ERROR, logger="app.privacy_log"):
        view = client.get(f"/api/privacy/{mid}").json()
    assert FULL_LINK not in view["never_sent"] and NAME in view["never_sent"]
    leaks = [r for r in caplog.records if r.name == "app.privacy_log" and r.levelno == logging.ERROR]
    assert leaks and RAW_LINK not in leaks[0].getMessage() and leaks[0].fields == {"item": FULL_LINK}


# --- store and runner ----------------------------------------------------------------------


@pytest.fixture
def store():
    s = StateStore()
    yield s
    s.close()


def test_runner_binds_the_run_log_so_registry_calls_are_recorded(store, reg):
    runner = JobRunner(store)
    mid = store.add_message(MSG)

    def job(message_id, message, on_trail):
        assert privacy_log.current().run == 1
        reg.call("check_link", {"url_id": "URL_1"}, agent_input())
        reg.call("check_link", {"url_id": "URL_1"}, agent_input(), on_call=privacy_log.current())  # no duplicate
        reg.call("check_link", {}, agent_input())  # invalid args: never reached the tool, not recorded
        return RESULT

    runner.submit(mid, job).result(timeout=5)
    runner.shutdown()
    assert [r.recipient for r in store.privacy(mid)] == ["check_link", "check_link"]
    assert privacy_log.current() is None


def test_superseded_run_is_still_recorded(store):
    mid = store.add_message(MSG)
    old = PrivacyLog(store, mid, store.start_run(mid))
    store.start_run(mid, c.AgentMode.recovery)
    old.record("nemotron", "model", {"text_redacted": "x"})
    assert [r.recipient for r in store.privacy(mid)] == ["nemotron"]


def test_latest_redaction_wins(store):
    mid = store.add_message(MSG)
    PrivacyLog(store, mid, store.start_run(mid)).redaction(redact(TEXT))
    second = redact(TEXT).model_copy(update={"report": c.RedactionReport(counts=c.RedactionCounts(PERSON=2))})
    PrivacyLog(store, mid, store.start_run(mid)).redaction(second)
    assert store.redaction(mid).report.counts.PERSON == 2


def test_view_before_anything_is_recorded(store):
    mid = store.add_message(MSG)
    view = privacy_log.view(store, mid)
    assert view.redaction.counts == c.RedactionCounts() and view.recipients == []
    # Without the redaction step's output there's nothing to check names against, so no name claim.
    assert view.never_sent == [SENDER_NUMBER, FULL_LINK, HISTORY]


def test_helpers_do_nothing_outside_a_run():
    assert privacy_log.current() is None
    privacy_log.record_redaction(redact(TEXT))
    privacy_log.record_model("nemotron", {"a": 1})
    privacy_log.record_local("classifier", {"a": 1})
    privacy_log.record_tool_result("nemotron", {"ok": True})


def test_a_broken_store_never_breaks_the_check(store, caplog):
    mid = store.add_message(MSG)
    p = PrivacyLog(store, mid, store.start_run(mid))
    store.close()
    p.record("nemotron", "model", {"a": 1})
    p.redaction(redact(TEXT))
    p.tool_result("nemotron", {"ok": True})
    assert any("privacy log write failed" in r.getMessage() for r in caplog.records)


def test_payload_models_are_serialized_without_nulls(store):
    mid = store.add_message(MSG)
    PrivacyLog(store, mid, store.start_run(mid)).record("nemotron", "model", agent_input())
    [r] = store.privacy(mid)
    assert "since" not in r.payload and r.received_fields == list(r.payload)
    json.dumps(r.payload)


# --- never_sent checks ---------------------------------------------------------------------


def _recipient(**payload) -> c.PrivacyRecipient:
    return c.PrivacyRecipient(recipient="nemotron", kind="model", payload=payload)


def test_never_sent_clean():
    red = redact(TEXT)
    out = privacy_log.never_sent(TEXT, SENDER, red, [_recipient(text_redacted=red.text_redacted, domain="capone-verify-alert.com")])
    assert out == [NAME, ACCOUNT_NUMBERS, ORIGINAL_TEXT, SENDER_NUMBER, FULL_LINK, HISTORY]


@pytest.mark.parametrize(
    "leak, dropped",
    [
        ({"note": "hi linda"}, NAME),
        ({"note": "sent from 555-010-4477"}, SENDER_NUMBER),
        ({"note": "www.capone-verify-alert.com"}, FULL_LINK),
        ({"nested": [{"t": TEXT}]}, ORIGINAL_TEXT),
    ],
)
def test_never_sent_drops_what_was_sent(leak, dropped):
    red = redact(TEXT)
    out = privacy_log.never_sent(TEXT, SENDER, red, [_recipient(text_redacted=red.text_redacted, **leak)])
    assert dropped not in out and HISTORY in out


def test_account_digits_are_checked():
    text = "Your card ending 4821 was charged. Reply to Linda."
    red = redact(text)
    assert red.report.counts.ACCOUNT_DIGITS == 1  # A3 hid them
    clean = privacy_log.never_sent(text, "TMOBILE", red, [_recipient(text_redacted=red.text_redacted)])
    assert ACCOUNT_NUMBERS in clean and SENDER_NUMBER not in clean and FULL_LINK not in clean
    leaked = privacy_log.never_sent(text, "TMOBILE", red, [_recipient(text_redacted=red.text_redacted, x="4821")])
    assert ACCOUNT_NUMBERS not in leaked


def test_phone_numbers_and_addresses_in_the_text_are_checked():
    text = "Hi Maria Lopez, mail to 12 Oak Street or maria.lopez@example.com, call 214-555-0101"
    red = redact(text)
    assert red.report.counts.PHONE == 1
    assert privacy_log._hidden_tokens(text, red.text_redacted) == ["Maria", "Lopez", "Oak", "Street", "maria.lopez@example.com", "214-555-0101"]
    clean = privacy_log.never_sent(text, "TMOBILE", red, [_recipient(text_redacted=red.text_redacted)])
    assert PHONE_NUMBERS in clean and NAME in clean
    for leak, dropped in [("2145550101", PHONE_NUMBERS), ("(214) 555-0101", PHONE_NUMBERS), ("Oak Street", NAME), ("MARIA.LOPEZ@EXAMPLE.COM", NAME)]:
        out = privacy_log.never_sent(text, "TMOBILE", red, [_recipient(text_redacted=red.text_redacted, x=leak)])
        assert dropped not in out, leak


def test_deleting_a_message_deletes_its_privacy_records(store):
    """SECURITY_PLAN 1: L3's retention cleanup and DELETE route must take L6's records with the message."""
    mid = store.add_message(MSG)
    p = PrivacyLog(store, mid, store.start_run(mid))
    p.redaction(redact(TEXT))
    p.record("nemotron", "model", {"a": 1})
    with store._tx():
        store._db.execute("DELETE FROM messages WHERE message_id = ?", (mid,))
    with store._lock:
        left = [store._db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("privacy", "redaction")]
    assert left == [0, 0]
