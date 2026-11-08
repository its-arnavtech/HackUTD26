"""L9: pipeline (redact, features, classify, agent), classifier fallback, L6 hooks, and the real routes.

Redaction, URL features, message features and brand detection are the real
modules. The agent, classifier and campaign store are faked: nothing calls
Nemotron, Nessie or writes the campaign DB.
"""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from types import SimpleNamespace

import numpy as np
import pytest

from app import contracts as c
from app import pipeline as pl
from app.agent import loop
from app.config import get_settings

SALT = "test-salt-not-a-secret"
SCENARIO_1 = c.MessageIn(
    text="Capital One Alert: unusual sign-in for Linda. Your account will be locked in 2 hours. Verify now: https://capone-verify-alert.com/verify",
    sender="+15550104477",
    received_at=datetime.fromisoformat("2026-11-08T09:14:00-06:00"),
)
RAW_VALUES = ["Linda", "15550104477", "555-010-4477", "https://", "capone-verify-alert.com/verify"]

CLASSIFIED = c.ClassifierOutput(category="bank_impersonation", score=0.94, top3=[("bank_impersonation", 0.94)], baseline_score=0.81)
RESULT = c.AgentResult(
    plan=[c.ToolName.check_link],
    verdict=c.Verdict.likely_scam,
    confidence_words=c.ConfidenceWords.likely,
    reason="The link imitates Capital One.",
    evidence=[c.Evidence(tool=c.ToolName.check_link, finding="Lookalike domain")],
    actions=[c.Action.block_sender],
)


@pytest.fixture(autouse=True)
def salt(monkeypatch):
    """A3's redaction reads the salt through get_settings(); give it one and keep it out of other tests."""
    monkeypatch.setenv("PHONE_HASH_SALT", SALT)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def fake_classify(text, features):
    return CLASSIFIED


class FakeAgent:
    """Records what it was given and writes a small trail, like run_agent."""

    def __init__(self, release: threading.Event | None = None):
        self.inputs: list[c.AgentInput] = []
        self.release = release
        self.started = threading.Event()

    def __call__(self, agent_input, on_trail, **kwargs):
        self.inputs.append(agent_input)
        on_trail(c.TrailEntry(step=1, kind=c.TrailKind.plan, finding="Plan: check_link", at=datetime.now(timezone.utc)))
        self.started.set()
        if self.release is not None:
            assert self.release.wait(5), "test never released the agent"
        on_trail(c.TrailEntry(step=2, kind=c.TrailKind.verdict, finding="Likely a scam", at=datetime.now(timezone.utc)))
        return RESULT


def make_pipeline(agent=None, record=None, **kw) -> pl.Pipeline:
    return pl.Pipeline(agent=agent or FakeAgent(), classify=fake_classify, record_campaign=record, **kw)


# --- build_input --------------------------------------------------------------------


def test_build_input_redacts_before_anything_else():
    agent_input, redacted = make_pipeline().build_input("msg_0001", SCENARIO_1)
    dumped = agent_input.model_dump_json()
    for raw in RAW_VALUES:
        assert raw not in dumped, f"{raw!r} reached the agent input"
    assert "<PERSON>" in agent_input.text_redacted and "<URL_1>" in agent_input.text_redacted
    assert agent_input.sender.type == c.SenderType.long_code and agent_input.sender.value.startswith("<PHONE_HASH_")
    assert agent_input.sender.claimed_brand == "Capital One"
    assert [u.registered_domain for u in agent_input.urls] == ["capone-verify-alert.com"]
    assert agent_input.urls[0].is_official_brand_domain is False
    assert agent_input.features.urgency_deadline  # "2 hours"
    assert agent_input.classifier == CLASSIFIED
    assert agent_input.customer_context == pl.DEMO_CUSTOMER
    assert agent_input.mode == c.AgentMode.check and agent_input.since is None
    assert redacted.raw_urls == ["https://capone-verify-alert.com/verify"]  # kept privately for the URL features


def test_recovery_input_has_since_received_at():
    agent_input, _ = make_pipeline().build_input("msg_0001", SCENARIO_1, c.AgentMode.recovery)
    assert agent_input.mode == c.AgentMode.recovery and agent_input.since == SCENARIO_1.received_at


def test_message_without_a_link_or_brand():
    msg = c.MessageIn(text="Hi Mom, landed safe. Will call you after dinner tonight.", sender="+15550137788", received_at=SCENARIO_1.received_at)
    agent_input, _ = make_pipeline().build_input("msg_0101", msg)
    assert agent_input.urls == [] and agent_input.sender.claimed_brand is None


def test_classifier_gets_only_redacted_text_and_features():
    seen = []
    p = pl.Pipeline(agent=FakeAgent(), classify=lambda text, features: (seen.append((text, features)), CLASSIFIED)[1], record_campaign=None)
    p.build_input("msg_0001", SCENARIO_1)
    [(text, features)] = seen
    assert "Linda" not in text and "https://" not in text and isinstance(features, c.Features)


# --- run ------------------------------------------------------------------------------


def test_run_calls_the_agent_and_passes_the_trail_through():
    agent = FakeAgent()
    trail: list[c.TrailEntry] = []
    result = make_pipeline(agent).run("msg_0001", SCENARIO_1, trail.append)
    assert result == RESULT
    assert [a.message_id for a in agent.inputs] == ["msg_0001"]
    assert [t.kind for t in trail] == [c.TrailKind.plan, c.TrailKind.verdict]


def test_campaign_recorded_once_in_check_mode_only():
    recorded = []
    p = make_pipeline(record=recorded.append)
    p.run("msg_0001", SCENARIO_1, lambda e: None)
    p.run("msg_0001", SCENARIO_1, lambda e: None, c.AgentMode.recovery)
    assert [a.message_id for a in recorded] == ["msg_0001"]
    assert "Linda" not in recorded[0].model_dump_json()


def test_campaign_failure_never_breaks_a_check():
    def boom(agent_input):
        raise RuntimeError("database is locked")

    assert make_pipeline(record=boom).run("msg_0001", SCENARIO_1, lambda e: None) == RESULT


def test_job_uses_the_stored_mode():
    from app.state import StoredMessage

    agent = FakeAgent()
    stored = StoredMessage(message_id="msg_0001", sender=SCENARIO_1.sender, text=SCENARIO_1.text, received_at=SCENARIO_1.received_at,
                           source=c.MessageSource.scenario, status=c.JobStatus.running, mode=c.AgentMode.recovery, run=2)
    make_pipeline(agent).job("msg_0001", stored, lambda e: None)
    assert agent.inputs[0].mode == c.AgentMode.recovery


def test_redaction_failure_propagates_so_the_runner_reports_it(monkeypatch):
    monkeypatch.delenv("PHONE_HASH_SALT")
    monkeypatch.setattr(get_settings(), "PHONE_HASH_SALT", None)  # also ignore a salt in the local .env
    with pytest.raises(ValueError, match="PHONE_HASH_SALT"):
        make_pipeline().run("msg_0001", SCENARIO_1, lambda e: None)


# --- L6 privacy hooks ----------------------------------------------------------------------


class FakePrivacyLog:
    def __init__(self, fail: bool = False):
        self.calls: list[tuple] = []
        self.fail = fail

    def __getattr__(self, name):
        def hook(*args):
            if self.fail:
                raise RuntimeError("store closed")
            self.calls.append((name, *args))

        return hook


def test_pipeline_records_redaction_and_classifier_input(monkeypatch):
    fake = FakePrivacyLog()
    monkeypatch.setattr(pl, "_privacy_log", fake)
    make_pipeline().run("msg_0001", SCENARIO_1, lambda e: None)
    names = [call[0] for call in fake.calls]
    assert names == ["record_redaction", "record_local"]
    assert isinstance(fake.calls[0][1], c.RedactedMessage)
    _, recipient, payload = fake.calls[1]
    assert recipient == "classifier" and set(payload) == {"text_redacted", "features"}
    assert not any(raw in json.dumps(payload) for raw in RAW_VALUES)


def test_agent_records_what_nemotron_received(monkeypatch):
    from tests.test_loop import GOOD_FINAL, FakeChat, FakeTools, final_turn, tools_turn

    fake = FakePrivacyLog()
    monkeypatch.setattr(loop, "privacy_log", fake)
    agent_input, _ = make_pipeline().build_input("msg_0001", SCENARIO_1)
    chat = FakeChat(tools_turn(("check_link", {"url_id": "URL_1"})), final_turn({**GOOD_FINAL, "confidence_words": "likely"}))
    loop.run_agent(agent_input, lambda e: None, chat=chat, call_tool=FakeTools(), tool_schemas=[], protocol="native")
    [(_, model, sent)] = [call for call in fake.calls if call[0] == "record_model"]  # once, not twice
    assert model == "nemotron" and c.AgentInput.model_validate(sent) == agent_input
    [tool_result] = [call for call in fake.calls if call[0] == "record_tool_result"]
    assert tool_result[1] == "nemotron" and tool_result[2]["tool"] == "check_link"


def test_broken_privacy_log_never_breaks_a_check(monkeypatch):
    monkeypatch.setattr(pl, "_privacy_log", FakePrivacyLog(fail=True))
    assert make_pipeline().run("msg_0001", SCENARIO_1, lambda e: None) == RESULT


# --- classifier -------------------------------------------------------------------------


class FakeBaseline:
    """Shape of A1's BaselineModel that the fallback uses."""

    clf = SimpleNamespace(classes_=np.array(["account_security", "bank_impersonation", "legit"]),
                          predict_proba=lambda X: np.array([[0.2, 0.7, 0.1]]))

    def _features(self, texts):
        assert texts == ["redacted text"]
        return texts


def test_classify_uses_l7_when_its_model_exists(monkeypatch):
    import app.classifier.predict as predict_module

    monkeypatch.setattr(predict_module, "predict", lambda text, features: CLASSIFIED)
    assert pl.classify("redacted text", c.Features()) == CLASSIFIED


@pytest.mark.parametrize("error", [FileNotFoundError("Train L7 first"), NotImplementedError("L7")])
def test_classify_falls_back_to_the_baseline_with_real_scores(monkeypatch, error):
    import app.classifier.predict as predict_module

    def missing(text, features):
        raise error

    monkeypatch.setattr(predict_module, "predict", missing)
    monkeypatch.setattr(pl, "_baseline_model", FakeBaseline())
    out = pl.classify("redacted text", c.Features())
    assert out.category == "bank_impersonation" and out.score == pytest.approx(0.7)
    assert [label for label, _ in out.top3] == ["bank_impersonation", "account_security", "legit"]
    assert out.baseline_score == pytest.approx(0.7)


def test_warm_only_runs_for_the_real_classifier(monkeypatch):
    calls = []
    monkeypatch.setattr(pl, "warm_classifier", lambda: calls.append("warm"))
    make_pipeline().warm()  # fake classifier: nothing to warm
    pl.Pipeline(agent=FakeAgent(), record_campaign=None).warm()
    assert calls == ["warm"]


def test_warm_uses_the_baseline_when_l7_is_untrained(monkeypatch):
    import app.classifier.predict as predict_module

    def untrained():
        raise FileNotFoundError("Train L7 first")

    trained = []
    monkeypatch.setattr(predict_module, "get_model", untrained)
    monkeypatch.setattr(pl, "_baseline", lambda: trained.append(True))
    pl.warm_classifier()
    assert trained == [True]


# --- routes ------------------------------------------------------------------------------------


@pytest.fixture
def live(make_client, tmp_path):
    """App with every route real (confirm and privacy have no real code yet) and the pipeline faked."""

    def _make(agent=None, record=None):
        client = make_client(USE_MOCKS=False, DEMO_MODE="replay", PHONE_HASH_SALT=SALT)
        client.app.state.pipeline = make_pipeline(agent, record)
        return client

    return _make


def wait_status(client, mid, status, timeout=5.0):
    deadline = time.monotonic() + timeout
    while True:
        poll = client.get(f"/api/messages/{mid}/result").json()
        if poll["status"] == status:
            return poll
        assert time.monotonic() < deadline, f"{mid} stuck at {poll['status']}"
        time.sleep(0.01)


def test_startup_loads_the_demo_inbox_unchecked(live):
    agent = FakeAgent()
    client = live(agent)
    inbox = client.get("/api/inbox").json()
    assert [i["message_id"] for i in inbox] == ["msg_0003", "msg_0001", "msg_0101"]  # newest first
    assert {i["status"] for i in inbox} == {"queued"} and agent.inputs == []
    assert {i["source"] for i in inbox} == {"scenario", "authored"}


def test_first_open_starts_one_check_and_the_trail_fills_in_live(live):
    release = threading.Event()
    agent = FakeAgent(release)
    client = live(agent)

    first = client.get("/api/messages/msg_0001/result").json()
    assert first["status"] in {"queued", "running"}
    assert agent.started.wait(5)
    running = client.get("/api/messages/msg_0001/result").json()
    assert running["status"] == "running" and [t["kind"] for t in running["trail"]] == ["plan"] and running["result"] is None

    release.set()
    done = wait_status(client, "msg_0001", "done")
    assert [t["kind"] for t in done["trail"]] == ["plan", "verdict"] and done["result"]["verdict"] == "likely_scam"
    assert len(agent.inputs) == 1  # polling again never restarts it
    assert agent.inputs[0].sender.claimed_brand == "Capital One"


def test_many_pollers_start_exactly_one_check(live):
    release = threading.Event()
    agent = FakeAgent(release)
    client = live(agent)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: client.get("/api/messages/msg_0003/result").status_code, range(16)))
    release.set()
    wait_status(client, "msg_0003", "done")
    assert len(agent.inputs) == 1


def test_opening_one_message_does_not_check_the_others(live):
    agent = FakeAgent()
    client = live(agent)
    wait_status(client, "msg_0001", "done")
    statuses = {i["message_id"]: i["status"] for i in client.get("/api/inbox").json()}
    assert statuses == {"msg_0001": "done", "msg_0003": "queued", "msg_0101": "queued"}


def test_posted_message_starts_at_once_and_clicked_reruns_in_recovery(live):
    agent = FakeAgent()
    client = live(agent)
    body = {"text": SCENARIO_1.text, "sender": SCENARIO_1.sender, "received_at": SCENARIO_1.received_at.isoformat()}
    mid = client.post("/api/messages", json=body).json()["message_id"]
    assert mid == "msg_0004"
    deadline = time.monotonic() + 5
    while not agent.inputs:
        assert time.monotonic() < deadline
        time.sleep(0.01)
    wait_status(client, mid, "done")
    assert client.post(f"/api/messages/{mid}/clicked").json()["mode"] == "recovery"
    poll = wait_status(client, mid, "done")
    assert poll["mode"] == "recovery"
    assert [a.mode for a in agent.inputs] == [c.AgentMode.check, c.AgentMode.recovery]
    assert agent.inputs[1].since == SCENARIO_1.received_at


def test_actions_are_simulated(live):
    client = live()
    r = client.post("/api/actions", json={"message_id": "msg_0001", "action": "block_sender"})
    assert r.status_code == 200 and r.json()["status"] == "simulated" and "Nothing was sent" in r.json()["note"]
    assert client.post("/api/actions", json={"message_id": "msg_9999", "action": "block_sender"}).status_code == 404
    assert client.post("/api/actions", json={"message_id": "msg_0001", "action": "wire_money"}).status_code == 422


def test_campaigns_come_from_the_campaign_store(live):
    client = live()
    card = c.Campaign(campaign_id="camp_01", category="billing_scam", count_total=28, count_last_24h=3,
                      first_seen=SCENARIO_1.received_at, last_seen=SCENARIO_1.received_at,
                      template="<BRAND>: bill or payment demand", redacted_example="Pattern preview")
    client.app.state.list_campaigns = lambda: [card]
    assert client.get("/api/campaigns").json()[0]["campaign_id"] == "camp_01"


def test_metrics_come_from_the_eval_file(live, tmp_path):
    client = live()
    from app import mocks

    path = tmp_path / "metrics.json"
    path.write_text(mocks.load("metrics.json").model_dump_json(), encoding="utf-8")
    client.app.state.metrics_path = path
    assert client.get("/api/metrics").json()["n_test"] == mocks.load("metrics.json").n_test
    client.app.state.metrics_path = tmp_path / "missing.json"
    r = client.get("/api/metrics")
    assert r.status_code == 404 and "scripts.evaluate" in r.json()["error"]["message"]


def test_real_metrics_file_is_valid(live):
    """The committed eval/metrics.json (A13, L7) must parse as the contract."""
    assert live().get("/api/metrics").status_code == 200


def test_reset_reloads_the_demo_inbox(live):
    client = live()
    body = {"text": "hello", "sender": "+15550100000", "received_at": "2026-11-08T11:00:00-06:00"}
    client.post("/api/messages", json=body)
    assert len(client.get("/api/inbox").json()) == 4
    assert client.post("/api/demo/reset").json() == {"ok": True, "inbox_count": 3}
    assert {i["status"] for i in client.get("/api/inbox").json()} == {"queued"}


def test_confirm_and_privacy_are_real_too(live):
    """L11 and L6 merged: with L9 every route is real."""
    client = live()
    assert client.post("/api/transactions/txn_3/confirm", json={"was_me": False}).status_code == 404  # no finished recovery
    assert client.get("/api/privacy/msg_0001").status_code == 200


def test_unknown_message_is_404_everywhere(live):
    client = live()
    assert client.get("/api/messages/msg_9999/result").status_code == 404
    assert client.post("/api/messages/msg_9999/clicked").status_code == 404


def test_mocks_still_work_when_on(client):
    """USE_MOCKS=true (frontend dev and the default) is unchanged."""
    assert client.get("/api/inbox").status_code == 200
    assert client.get("/api/metrics").status_code == 200
    assert client.post("/api/actions", json={"message_id": "msg_0001", "action": "report_spam"}).json()["status"] == "simulated"
