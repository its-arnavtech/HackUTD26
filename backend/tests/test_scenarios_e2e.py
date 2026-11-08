"""A18: the three demo scenarios end to end in replay mode (POC_MVP 4.3, 7.4, 7.8).

Every scenario goes through `scripts.run_scenario.run_scenario`, so whatever
`run_scenario.AGENT` points at is what gets tested: today the stand-in, and
L8's `run_agent` after the one-line swap there. Nothing here names the agent.

Two replay worlds:

- `synthetic` (always available): Cursor's in-memory FakeNessie is seeded with
  `scripts.seed_nessie`, the scenarios' Nessie calls are recorded into a temp
  fixtures folder, then all three scenarios replay with `DEMO_MODE=replay` and
  every network socket blocked. Only the Nessie data source is fake; the client,
  tools, redaction, features, classifier and agent are the real code paths.
  The real agent can't run here (it would need recorded Nemotron answers), so
  this world is skipped once `AGENT` is no longer the stand-in.
- `recorded` (once A19 lands): the committed `data/nessie_seed.json` and
  `data/fixtures/`, recorded live. Same checks, no fakes, sockets blocked.

Checks per issue A18: plans differ between messages, verdicts, the Nessie
findings, and the code guardrails (POC_MVP 7.4).
"""

from __future__ import annotations

import json
import re
import socket
from datetime import datetime

import pytest

rs = pytest.importorskip("scripts.run_scenario")
if not hasattr(rs, "run_scenario"):  # G1 not merged on this branch yet
    pytest.skip("scripts.run_scenario is still the G1 stub", allow_module_level=True)

from app.config import DATA_DIR, get_settings  # noqa: E402
from app.contracts import Action, AgentMode, ConfidenceWords, ToolName, TrailKind, Verdict  # noqa: E402
from app.integrations import cache  # noqa: E402
from app.integrations import nessie as nessie_mod  # noqa: E402
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


def _real_world_available() -> bool:
    return (DATA_DIR / "nessie_seed.json").exists() and bool(cache.list_fixtures("nessie"))


def _agent_is_stand_in() -> bool:
    return rs.AGENT is getattr(rs, "stand_in_agent", None)


class _NoNetwork:
    """Block every outbound connection, so replay can't quietly go live."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def refuse(*args, **kwargs):
            raise AssertionError("A18 replay test tried to open a network connection")

        monkeypatch.setattr(socket.socket, "connect", refuse)
        monkeypatch.setattr(socket, "create_connection", refuse)


def _replay_settings(mp: pytest.MonkeyPatch) -> None:
    mp.setenv("DEMO_MODE", "replay")
    mp.setenv("PHONE_HASH_SALT", "a18-synthetic-salt")
    mp.setenv("NESSIE_API_KEY", "")
    get_settings.cache_clear()


def _synthetic_world(mp: pytest.MonkeyPatch, tmp_path_factory) -> dict:
    from scripts.seed_nessie import seed
    from tests.fake_nessie import API_KEY, FakeNessie

    root = tmp_path_factory.mktemp("a18_world")
    mp.setattr(cache, "FIXTURES_DIR", root / "fixtures")
    _replay_settings(mp)

    fake = FakeNessie()
    base_url = "https://fake-nessie.test"
    seeded = seed(nessie_mod.NessieClient(API_KEY, base_url, http=fake.client(), mode="record"))
    manifest = seeded.manifest
    # Transfer payees/times and the planted purchase's time live in the manifest (DATA_SPEC 6).
    details = {"transfer_details": nessie_mod.transfer_details_from_seed(manifest)}
    if hasattr(nessie_mod, "purchase_times_from_seed"):
        details["purchase_times"] = nessie_mod.purchase_times_from_seed(manifest)
    mp.setattr(nessie_tools, "load_seed", lambda *a, **k: manifest)

    # Record: the Nessie client talks to the fake and saves fixtures; RDAP stays in
    # replay (an unrecorded lookup means "age unknown", as in the demo).
    recorder = nessie_mod.NessieClient(API_KEY, base_url, http=fake.client(), mode="record", **details)
    mp.setattr(nessie_tools, "client_from_settings", lambda *a, **k: recorder)
    for n in SCENARIOS:
        rs.run_scenario(n)

    # Replay: a client with no key and a transport that fails if it is ever used.
    import httpx

    def unreachable(request):
        raise AssertionError(f"replay reached the transport: {request.method} {request.url.path}")

    replayer = nessie_mod.NessieClient("", base_url, http=httpx.Client(transport=httpx.MockTransport(unreachable)), **details)
    mp.setattr(nessie_tools, "client_from_settings", lambda *a, **k: replayer)
    return {"name": "synthetic", "manifest": manifest, "fixtures": len(cache.list_fixtures("nessie"))}


def _recorded_world(mp: pytest.MonkeyPatch) -> dict:
    _replay_settings(mp)
    manifest = json.loads((DATA_DIR / "nessie_seed.json").read_text(encoding="utf-8"))
    return {"name": "recorded", "manifest": manifest, "fixtures": len(cache.list_fixtures("nessie"))}


@pytest.fixture(scope="module", params=["synthetic", "recorded"])
def world(request, tmp_path_factory):
    if request.param == "synthetic" and not _agent_is_stand_in():
        pytest.skip("the real agent needs recorded Nemotron fixtures; the 'recorded' world covers it (A19)")
    if request.param == "recorded" and not _real_world_available():
        pytest.skip("no recorded fixtures yet: needs data/nessie_seed.json (P4) and data/fixtures/nessie (A19)")
    mp = pytest.MonkeyPatch()
    try:
        info = _synthetic_world(mp, tmp_path_factory) if request.param == "synthetic" else _recorded_world(mp)
        _NoNetwork(mp)
        runs = {n: rs.run_scenario(n) for n in SCENARIOS}
        yield {**info, "runs": runs}
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
            assert not e.finding.startswith("Couldn't run"), f"tool failed in replay: {e.tool.value}: {e.finding}"
    used = [e.tool for e in trail if e.kind == TrailKind.tool]
    assert used == list(run.result.plan), "the trail must show exactly the planned tools, in order"


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


def test_scenario_1_plan_matches_the_script(world):
    run = world["runs"][1]
    assert [t.value for t in run.result.plan] == run.scenario["expected_plan"]


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
    assert "you may not have made" in finding or str(PLANTED_AMOUNT) in finding
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
