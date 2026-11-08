"""L15 features: agent accuracy, any system as the agent's bank source, trusted contact, scam waves."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app import activity_source, agent_eval, trusted_contact, waves
from app import contracts as c


@pytest.fixture(autouse=True)
def _clean_state():
    activity_source.clear()
    trusted_contact.clear()
    waves.detector.clear()
    yield
    activity_source.clear()
    trusted_contact.clear()
    waves.detector.clear()


# ---------------------------------------------------------------------------
# 1. Agent accuracy
# ---------------------------------------------------------------------------


def test_sample_is_balanced_and_from_the_test_split_only():
    sample = agent_eval.load_test_sample(per_category=2)
    assert len(sample) == 18
    assert all(r["split"] == "test" for r in sample)
    assert {r["taxonomy_id"] for r in sample} == {
        "bank_impersonation", "billing_scam", "delivery_scam", "account_security", "toll_government",
        "prize_refund", "job_offer", "conversation_lure", "legit"}
    assert agent_eval.load_test_sample(per_category=2) == sample  # seeded: same sample every run


def test_scoring_counts_unsure_separately():
    o = agent_eval.Outcome
    outcomes = [
        o("a", "billing_scam", True, "likely_scam", 1000, ["check_link"]),
        o("b", "billing_scam", True, "unsure", 2000),
        o("c", "legit", False, "likely_safe", 3000, ["check_sender"]),
        o("d", "legit", False, "likely_scam", 4000),
        o("e", "legit", False, "error", 100),
    ]
    s = agent_eval.summarize(outcomes, model="m", per_category=2, started_at=datetime.now(timezone.utc))
    assert s["n"] == 4 and s["errors"] == 1
    assert s["accuracy"] == 0.5 and s["unsure"] == 0.25
    assert s["scams_caught"] == 0.5 and s["false_alarms"] == 0.5
    assert s["avg_seconds"] == 2.5 and s["worst_seconds"] == 4.0
    billing = next(r for r in s["categories"] if r["category"] == "billing_scam")
    assert billing == {"category": "billing_scam", "n": 2, "correct": 0.5, "unsure": 0.5, "wrong": 0.0}


def test_runner_uses_our_classifier_and_survives_a_crash():
    sample = agent_eval.load_test_sample(per_category=1)[:3]
    seen = []

    def classify(text, features):
        return c.ClassifierOutput(category="billing_scam", score=0.42, top3=[("billing_scam", 0.42)], baseline_score=0.4)

    def agent(agent_input, on_trail):
        seen.append(agent_input.classifier.score)
        if len(seen) == 2:
            raise RuntimeError("model down")
        on_trail(c.TrailEntry(step=1, kind=c.TrailKind.tool, tool=c.ToolName.check_link, at=datetime.now(timezone.utc)))
        return SimpleNamespace(verdict=c.Verdict.likely_scam)

    outcomes = agent_eval.run(sample, agent, classify)
    assert seen == [0.42, 0.42, 0.42]  # the file's own classifier numbers are not used
    assert [o.verdict for o in outcomes].count("error") == 1
    assert outcomes[0].tools == ["check_link"]


def test_agent_metrics_route(client, tmp_path, monkeypatch):
    monkeypatch.setattr(agent_eval, "OUTPUT", tmp_path / "agent_metrics.json")
    assert client.get("/api/agent-metrics").status_code == 404
    (tmp_path / "agent_metrics.json").write_text(json.dumps({"accuracy": 0.8, "n": 45}), encoding="utf-8")
    assert client.get("/api/agent-metrics").json()["accuracy"] == 0.8


# ---------------------------------------------------------------------------
# 2. Any payment system as the agent's bank activity
# ---------------------------------------------------------------------------


def _input(mode=c.AgentMode.recovery):
    from tests.test_loop import INPUT

    return INPUT.model_copy(update={"mode": mode, "received_at": datetime(2026, 11, 8, 15, 0, tzinfo=timezone.utc)})


@pytest.mark.parametrize("source", ["paysim", "sparkov", "ibm_aml", "generic_card_processor", "nessie"])
def test_recovery_flags_the_suspicious_payment_from_any_payment_system(source):
    from app.tools import nessie_tools

    activity_source.set_active(source)
    result = nessie_tools.nessie_recent_activity(c.NessieRecentActivityArgs(since=_input().received_at), _input())
    assert result.flagged, source
    item = result.flagged[0]
    assert item.ref.startswith("evt_") and item.new_payee
    assert "first payment ever" not in item.reason  # payee names stay out of the model's result
    detail = nessie_tools.resolve_ref(item.ref)
    assert detail.amount == item.amount and detail.payee


def test_check_mode_sees_only_activity_before_the_text():
    from app.tools import nessie_tools

    activity_source.set_active("paysim")
    result = nessie_tools.nessie_recent_activity(c.NessieRecentActivityArgs(days=7), _input(c.AgentMode.check))
    assert result.flagged == [] and result.items_checked >= 1


def test_carrier_events_are_preview_only_and_clear_returns_to_nessie():
    with pytest.raises(activity_source.UnsupportedSource):
        activity_source.set_active("telecom_billing")
    activity_source.set_active("sparkov")
    assert activity_source.status()["source"] == "sparkov"
    activity_source.clear()
    assert activity_source.status() == {"source": "nessie", "label": "Capital One Nessie (bank)", "live_nessie": True, "records": 0}


def test_active_source_routes(client):
    assert client.get("/api/connect/active").json()["source"] == "nessie"
    assert client.post("/api/connect/active", json={"source": "paysim"}).json()["source"] == "paysim"
    assert client.post("/api/connect/active", json={"source": "telecom_billing"}).status_code == 400
    assert client.delete("/api/connect/active").json()["source"] == "nessie"


# ---------------------------------------------------------------------------
# 3. Trusted contact
# ---------------------------------------------------------------------------


def test_contact_is_masked_and_alert_is_content_free():
    contact = trusted_contact.save("u1", "Maya", "+1 (512) 555-4471")
    assert contact.view() == {"name": "Maya", "phone_masked": "•••• 4471"}
    note = trusted_contact.alert_note("u1", "Linda")
    assert "Maya (•••• 4471)" in note and "5125554471" not in note
    for forbidden in ("http", "$", "<URL", "capone"):
        assert forbidden not in trusted_contact.alert_text("Linda", recovery=True)


@pytest.mark.parametrize("name,phone", [("", "5125554471"), ("Maya<script>", "5125554471"), ("Maya", "123"), ("Maya", "call me")])
def test_bad_contacts_are_refused(name, phone):
    with pytest.raises(trusted_contact.InvalidContact):
        trusted_contact.save("u1", name, phone)


def test_trusted_contact_routes_and_alert_action(client):
    assert client.get("/api/trusted-contact").json() == {"contact": None}
    r = client.post("/api/actions", json={"message_id": "msg_0001", "action": "alert_trusted_contact"})
    assert "Add a trusted contact first" in r.json()["note"]
    saved = client.put("/api/trusted-contact", json={"name": "Maya", "phone": "+15125554471"}).json()
    assert saved == {"contact": {"name": "Maya", "phone_masked": "•••• 4471"}}
    note = client.post("/api/actions", json={"message_id": "msg_0001", "action": "alert_trusted_contact"}).json()["note"]
    assert "Maya" in note and "+15125554471" not in note and "Simulated" in note
    assert client.put("/api/trusted-contact", json={"name": "Maya", "phone": "not a phone"}).status_code in (400, 422)
    assert client.delete("/api/trusted-contact").json() == {"contact": None}
    other = client.post("/api/actions", json={"message_id": "msg_0001", "action": "block_sender"}).json()["note"]
    assert other == "Simulated for the demo. Nothing was sent."


# ---------------------------------------------------------------------------
# 4. Scam waves
# ---------------------------------------------------------------------------


def test_fingerprint_groups_rotating_wording_by_brand_and_type():
    a = waves.fingerprint("Walmart: payment of $18 did not clear. Fix it at <URL_1>.", "Walmart", "billing_scam")
    b = waves.fingerprint("Walmart notice. $48 is past due. Use <URL_1>.", "Walmart", "billing_scam")
    assert a == b
    assert a != waves.fingerprint("x", "Target", "billing_scam")
    # Without a brand the wording skeleton decides, stable across amounts and links.
    assert waves.fingerprint("Pay $18 at http://a.test now", None, None) == waves.fingerprint("Pay $940 at http://zz.test now", None, None)


def test_threshold_growth_and_legit_ignored():
    d = waves.WaveDetector()
    now = datetime.now(timezone.utc)
    for i in range(4):
        d.observe("Fake toll notice", brand="E-ZPass", category="toll_government", at=now - timedelta(minutes=i))
    assert d.waves(now) == []  # 4 is below the threshold
    d.observe("Fake toll notice", brand="E-ZPass", category="toll_government", at=now)
    assert len(d.waves(now)) == 1 and d.waves(now)[0]["trend"] == "new"
    for _ in range(10):
        d.observe("Your bill is ready", brand="T-Mobile", category="legit", at=now)
    assert len(d.waves(now)) == 1  # real messages never make a wave
    g = waves.WaveDetector()
    g.observe("x", brand="USPS", category="delivery_scam", at=now - timedelta(minutes=90))
    for _ in range(3):
        g.observe("x", brand="USPS", category="delivery_scam", at=now)
    assert g.waves(now)[0]["trend"] == "growing"  # 3x the previous hour


def test_wave_routes_simulate_and_warn(client):
    assert client.get("/api/waves").json()["waves"] == []
    sim = client.post("/api/waves/simulate", json={}).json()
    assert sim["messages"] >= 5 and sim["fingerprints"] == 1
    wave = client.get("/api/waves").json()["waves"][0]
    warn = client.post(f"/api/waves/{wave['id']}/warn").json()
    assert wave["brand"] in warn["text"] and "http" not in warn["text"] and warn["sent"] is False
    assert client.get("/api/waves").json()["waves"][0]["warned"] is True
    assert client.post("/api/waves/nope/warn").status_code == 404
    assert client.post("/api/waves/simulate", json={"campaign_id": "camp_999"}).status_code == 404
    client.post("/api/demo/reset")
    assert client.get("/api/waves").json()["waves"] == []
