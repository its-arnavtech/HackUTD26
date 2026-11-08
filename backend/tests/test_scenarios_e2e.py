"""A18: all three authored scenarios with the real L8 agent and recorded services.

The checked-in profile uses A1's real baseline to avoid local L7 artifact and
platform float differences in cache keys. Real redaction, features, five tools,
Nemotron responses and Nessie results are replayed with every socket blocked.
Optional Gemini search is explicitly unavailable in this profile. L7 evaluation
and the app's G2 live/replay gate remain separate.
"""

from __future__ import annotations

import json
import re
import socket
from datetime import datetime

import pytest

from scripts import run_scenario as rs

from app.config import DATA_DIR, get_settings  # noqa: E402
from app.contracts import Action, AgentMode, ConfidenceWords, ToolName, TrailKind, Verdict  # noqa: E402
from app.integrations import cache  # noqa: E402
from app.tools import nessie_tools  # noqa: E402

SCENARIOS = (1, 2, 3)
PLANTED_AMOUNT = 900
BILL_PAID_ON = "2026-11-01"
_PHONE_CANDIDATE = re.compile(r"\+?\(?\d[\d\s().-]{6,}\d")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _has_phone(text: str) -> bool:
    """10 or more digits in a phone-like run (dates and amounts don't count)."""
    for m in _PHONE_CANDIDATE.finditer(text):
        s = m.group(0).strip()
        if not _ISO_DATE.match(s) and len(re.sub(r"\D", "", s)) >= 10:
            return True
    return False
_LINK = re.compile(r"https?://|www\.", re.I)
_BARE_DOMAIN = re.compile(r"\b(?:[a-z0-9-]+\.)+(?:com|net|org|info|co|io|top|xyz|us|app|site|online)\b", re.I)


def _official_domains() -> set[str]:
    brands = json.loads((DATA_DIR / "brands.json").read_text(encoding="utf-8"))["brands"]
    return {d.lower() for b in brands for d in b.get("official_domains", [])}


class _NoNetwork:
    """Block every outbound connection, so replay can't quietly go live."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def refuse(*args, **kwargs):
            raise AssertionError("A18 replay test tried to open a network connection")

        monkeypatch.setattr(socket.socket, "connect", refuse)
        monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture(scope="module")
def world():
    from scripts.replay_demo import PROFILE, demo_profile
    profile_path = DATA_DIR / "fixtures" / "demo_profile.json"
    assert profile_path.exists(), "Missing committed replay profile; record it with python -m scripts.replay_demo record"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    assert profile["profile"] == PROFILE
    manifest = json.loads((DATA_DIR / "nessie_seed.json").read_text(encoding="utf-8"))
    mp = pytest.MonkeyPatch()
    try:
        with demo_profile("replay"):
            mp.setenv("NVIDIA_API_KEY", "")
            mp.setenv("NESSIE_API_KEY", "")
            get_settings.cache_clear()
            nessie_tools._REF_DETAILS.clear()
            _NoNetwork(mp)
            runs = {n: rs.run_scenario(n) for n in SCENARIOS}
            yield {"name": "recorded", "manifest": manifest, "fixtures": len(cache.list_fixtures()), "runs": runs}
    finally:
        mp.undo()
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Every scenario
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n", SCENARIOS)
def test_scenario_completes_in_replay_with_a_valid_trail(world, n):
    run = world["runs"][n]
    trail = run.trail
    assert trail and trail[0].kind == TrailKind.plan and trail[-1].kind == TrailKind.verdict
    assert [e.step for e in trail] == list(range(1, len(trail) + 1))
    for e in trail:
        if e.kind == TrailKind.tool:
            assert e.tool is not None and e.finding
            if e.tool != ToolName.public_scam_reports:  # explicitly cut from the recorded profile
                assert not e.finding.startswith("Couldn't run"), f"tool failed in replay: {e.tool.value}: {e.finding}"
    used = [e.tool for e in trail if e.kind == TrailKind.tool]
    assert set(used) == set(run.result.plan), "the final plan must match the actual checks"


@pytest.mark.parametrize("n", SCENARIOS)
def test_redaction_runs_before_the_agent(world, n):
    run = world["runs"][n]
    payload = run.agent_input.model_dump_json()
    message = run.scenario["message"]
    assert "Linda" not in payload
    assert message["sender"] not in payload and message["sender"].lstrip("+") not in payload
    for raw_url in re.findall(r"https?://\S+", message["text"]):
        assert raw_url not in payload
    assert stage_source(run, "redaction") == "real"


@pytest.mark.parametrize("n", SCENARIOS)
def test_guardrails(world, n):
    """POC_MVP 7.4: fixed enums, at most 3 actions, very-likely needs two tools, no numbers or links in the text.

    A bare domain may appear only if it's a brand's official domain ("imitates
    capitalone.com"); the scam's own domain must never reach the reason, because
    phones turn bare domains into tappable links."""
    r = world["runs"][n].result
    official = _official_domains()
    assert isinstance(r.verdict, Verdict) and isinstance(r.confidence_words, ConfidenceWords)
    assert 1 <= len(r.actions) <= 3 and all(isinstance(a, Action) for a in r.actions)
    assert len(set(r.actions)) == len(r.actions)
    if r.confidence_words == ConfidenceWords.very_likely:
        assert len({e.tool for e in r.evidence}) >= 2
    for text in [r.reason, *(e.finding for e in r.evidence)]:
        assert not _has_phone(text), f"phone number in model-facing text: {text!r}"
        assert not _LINK.search(text), f"link in model-facing text: {text!r}"
        for domain in (m.group(0).lower() for m in _BARE_DOMAIN.finditer(text)):
            assert domain in official, f"non-official domain {domain!r} in model-facing text: {text!r}"
    assert r.reason.strip()


def stage_source(run, name: str) -> str:
    return next(s.source for s in run.stages if s.name == name)


# ---------------------------------------------------------------------------
# Plans differ (NVIDIA track: two messages, two plans)
# ---------------------------------------------------------------------------


def test_plans_differ_between_messages(world):
    plans = {n: tuple(world["runs"][n].result.plan) for n in SCENARIOS}
    assert plans[1] != plans[3], "scenario 1 (bank lock) and 3 (fake bill) must get different plans"
    assert plans[1] != plans[2], "recovery (scenario 2) must re-plan, not repeat the check"


def test_scenario_1_checks_the_script_claims(world):
    run = world["runs"][1]
    # Nemotron may reorder or add checks; the expected plan specifies the
    # minimum claim checks, not an exact prewritten model sequence.
    assert set(run.scenario["expected_plan"]) <= {t.value for t in run.result.plan}


# ---------------------------------------------------------------------------
# Verdicts and Nessie findings, per scenario
# ---------------------------------------------------------------------------


def test_scenario_1_bank_lock_is_a_scam(world):
    run = world["runs"][1]
    assert run.mode == AgentMode.check
    assert run.result.verdict == Verdict.likely_scam
    assert ToolName.nessie_recent_activity in run.result.plan
    assert not run.result.was_this_you, "check mode never asks 'Was this you?'"


def _planted(manifest: dict) -> dict:
    """The planted $900: a purchase at "Unknown Payee" (DATA_SPEC 6); older manifests had a transfer."""
    return manifest.get("planted") or manifest["transfers"]["planted_transfer"]


def test_scenario_2_recovery_finds_the_planted_900(world):
    run = world["runs"][2]
    r = run.result
    assert run.mode == AgentMode.recovery
    assert r.plan[0] == ToolName.nessie_recent_activity
    assert r.was_this_you, "recovery must ask 'Was this you?' about the planted $900"
    finding = next(e.finding for e in run.trail if e.tool == ToolName.nessie_recent_activity)
    assert "Flagged" in finding or str(PLANTED_AMOUNT) in finding
    from app.tools.nessie_tools import resolve_ref
    details = [resolve_ref(ref) for ref in r.was_this_you]
    assert any(item.amount == PLANTED_AMOUNT and item.payee == "Unknown Payee" for item in details)
    assert Action.freeze_card in r.actions
    planted = _planted(world["manifest"])
    assert planted["amount"] == PLANTED_AMOUNT
    assert datetime.fromisoformat(planted["at"]) > run.agent_input.received_at


def test_scenario_3_fake_bill_checks_the_real_bill(world):
    run = world["runs"][3]
    r = run.result
    assert ToolName.nessie_bill_status in r.plan
    finding = next(e.finding for e in run.trail if e.tool == ToolName.nessie_bill_status)
    assert f"paid on {BILL_PAID_ON}" in finding
    assert r.verdict == Verdict.likely_scam


def test_guardrail_helpers_catch_what_they_should():
    assert _has_phone("call 214-555-0143 now") and _has_phone("text +15550104477")
    assert not _has_phone("paid on 2026-11-01, $1,299.00 due, ref 4471")
    assert _LINK.search("go to https://x.example") and _LINK.search("www.thing.com")
    found = [m.group(0) for m in _BARE_DOMAIN.finditer("imitates capitalone.com via capone-verify-alert.com")]
    assert found == ["capitalone.com", "capone-verify-alert.com"]
    assert "capitalone.com" in _official_domains() and "capone-verify-alert.com" not in _official_domains()


def test_the_world_really_replayed(world):
    assert world["fixtures"] > 0
    assert get_settings().DEMO_MODE.value == "replay"
