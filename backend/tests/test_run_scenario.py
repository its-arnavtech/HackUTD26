from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from app.contracts import (
    AgentMode,
    AgentResult,
    CheckLinkResult,
    CheckSenderResult,
    ConfidenceWords,
    FlaggedItem,
    NessieBillStatusResult,
    NessieRecentActivityResult,
    SenderType,
    ToolName,
    TrailEntry,
    TrailKind,
    Verdict,
)
from scripts import run_scenario as rs

SCAM_LINK = CheckLinkResult(domain="capone-verify-alert.com", domain_age_days=3, on_blocklist=False, lookalike_of="capitalone.com", signals=[])
NOT_OFFICIAL = CheckSenderResult(sender_type=SenderType.long_code, matches_official_channel=False, official_channels_known=True, note="n")
QUIET = NessieRecentActivityResult(accounts_checked=2, items_checked=6, flagged=[])
PLANTED = NessieRecentActivityResult(
    accounts_checked=2,
    items_checked=1,
    flagged=[FlaggedItem(ref="txn_28", type="transfer", amount=900, new_payee=True, minutes_after_message=17, reason="new payee, 6x the 30-day median")],
)
PAID_BILL = NessieBillStatusResult(found=True, last_status="completed", last_payment_date=date(2026, 11, 1), amount_due_now=0, recurring=True)


@pytest.fixture(autouse=True)
def phone_salt(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("PHONE_HASH_SALT", "synthetic-test-salt")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def tools(monkeypatch):
    """Replace the tool table with canned results, as A10 and A11 would return them."""
    calls: list[tuple[ToolName, object]] = []

    def install(results: dict[ToolName, object]) -> list:
        def make(tool, value):
            def fn(args, agent_input):
                calls.append((tool, args))
                if isinstance(value, Exception):
                    raise value
                return value

            return fn

        monkeypatch.setattr(rs, "TOOLS", {tool: make(tool, value) for tool, value in results.items()})
        return calls

    return install


def test_scenario_1_runs_on_stubs_with_a_schema_valid_verdict():
    run = rs.run_scenario(1)
    assert isinstance(run.result, AgentResult)
    assert [t.value for t in run.result.plan] == run.scenario["expected_plan"]
    assert run.trail[0].kind == TrailKind.plan and run.trail[-1].kind == TrailKind.verdict
    assert [e.step for e in run.trail] == list(range(1, len(run.trail) + 1))
    assert {s.name for s in run.stages} >= {"redaction", "classifier", "agent loop"}


def test_redaction_runs_before_anything_sees_the_message():
    run = rs.run_scenario(1)
    payload = run.agent_input.model_dump_json()
    message = run.scenario["message"]
    for raw in ("Linda", message["sender"], "https://", "/verify"):
        assert raw not in payload
    assert run.agent_input.sender.type == SenderType.long_code
    assert run.agent_input.sender.value.startswith("<PHONE_HASH_")
    assert run.agent_input.urls[0].registered_domain == "capone-verify-alert.com"
    assert run.agent_input.sender.claimed_brand == "Capital One"


def test_scenario_1_with_tool_results_is_very_likely_a_scam(tools):
    calls = tools({ToolName.check_link: SCAM_LINK, ToolName.check_sender: NOT_OFFICIAL, ToolName.nessie_recent_activity: QUIET})
    run = rs.run_scenario(1)
    assert [c[0] for c in calls] == [ToolName.check_link, ToolName.check_sender, ToolName.nessie_recent_activity]
    assert calls[2][1].days == 7
    r = run.result
    assert (r.verdict, r.confidence_words) == (Verdict.likely_scam, ConfidenceWords.very_likely)
    assert r.reason == "Domain imitates capitalone.com, and not sent from an official channel."
    assert [a.value for a in r.actions] == ["block_sender", "report_spam", "call_number_on_card"]
    assert len({e.tool for e in r.evidence}) >= 2


def test_scenario_2_recovery_returns_was_this_you(tools):
    calls = tools({ToolName.nessie_recent_activity: PLANTED})
    run = rs.run_scenario(2)
    assert run.mode == AgentMode.recovery
    assert calls[0][1].since == run.agent_input.received_at
    assert run.result.was_this_you == ["txn_28"]
    assert [a.value for a in run.result.actions] == ["freeze_card", "call_number_on_card", "change_password"]


def test_scenario_3_checks_the_bill(tools):
    calls = tools({ToolName.check_link: SCAM_LINK, ToolName.nessie_bill_status: PAID_BILL})
    run = rs.run_scenario(3)
    assert ToolName.nessie_bill_status in [c[0] for c in calls]
    assert run.result.verdict == Verdict.likely_scam
    assert "paid on 2026-11-01" in run.result.reason


def test_tool_errors_come_back_as_data(tools):
    tools({ToolName.check_link: RuntimeError("boom"), ToolName.check_sender: NotImplementedError(), ToolName.nessie_recent_activity: QUIET})
    run = rs.run_scenario(1)
    findings = [e.finding for e in run.trail if e.kind == TrailKind.tool]
    assert findings[0] == "Couldn't run: RuntimeError: boom"
    assert findings[1] == "Not available yet (A10 not merged)"
    assert run.result.verdict == Verdict.unsure


def test_l8_swap_is_one_assignment(monkeypatch):
    seen = {}

    def fake_run_agent(agent_input, on_trail):
        seen["input"] = agent_input
        on_trail(TrailEntry(step=1, kind=TrailKind.verdict, finding="likely_safe", at=agent_input.received_at))
        return AgentResult(plan=[], verdict=Verdict.likely_safe, confidence_words=ConfidenceWords.likely, reason="ok")

    monkeypatch.setattr(rs, "AGENT", fake_run_agent)
    run = rs.run_scenario(1)
    assert seen["input"] is run.agent_input
    assert run.result.verdict == Verdict.likely_safe
    assert next(s for s in run.stages if s.name == "agent loop").source == "real"


def test_agent_line_points_at_the_stand_in_and_run_agent_is_imported():
    source = Path(rs.__file__).read_text(encoding="utf-8")
    assert "AGENT: Callable[[AgentInput, Callable[[TrailEntry], None]], AgentResult] = stand_in_agent" in source
    assert rs.run_agent.__module__ == "app.agent.loop"


def test_cli_text_and_json(capsys):
    assert rs.main(["1"]) == 0
    out = capsys.readouterr().out
    assert "How we checked:" in out and "Verdict (schema-valid AgentResult):" in out

    assert rs.main(["1", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    AgentResult.model_validate(data["result"])
    assert data["mode"] == "check" and data["trail"][0]["kind"] == "plan"


def test_missing_phone_salt_stops_instead_of_using_the_stand_in(monkeypatch, capsys):
    from app.config import get_settings

    monkeypatch.setenv("PHONE_HASH_SALT", "")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="PHONE_HASH_SALT"):
        rs.run_scenario(1)
    assert rs.main(["1"]) == 2
    assert "PHONE_HASH_SALT" in capsys.readouterr().err
