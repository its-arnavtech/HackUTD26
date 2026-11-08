"""L14 live demo helpers: sample messages and "plug into any system"."""

from __future__ import annotations

import pytest

from app import connect


def test_samples_come_from_training_templates_with_truth_and_no_tags():
    samples = connect.sample_messages(n=10, seed=7)
    assert len(samples) == 10
    for s in samples:
        assert "<URL" not in s["text"] and "<PERSON" not in s["text"] and "<PHONE" not in s["text"]
        assert s["truth"]["is_scam"] == (s["category"] != "legit")
        assert s["category"] in connect.categories()
    assert all(r["message"].get("template_set") != "B" for r in connect._scenarios())  # test wording never used


def test_category_filter():
    assert {s["category"] for s in connect.sample_messages("delivery_scam", n=5, seed=1)} == {"delivery_scam"}
    assert connect.sample_messages("not_a_category") == []


@pytest.mark.parametrize("source", ["nessie", "paysim", "sparkov", "ibm_aml", "generic_card_processor"])
def test_every_payment_system_maps_and_flags_the_suspicious_payment(source):
    p = connect.preview(source)
    names = {s["signal"] for s in p["signals"]}
    assert {"new_payee", "amount_far_above_usual"} <= names
    assert all(e["source_system"] == source for e in p["canonical"])


def test_telecom_takeover_steps_are_flagged():
    names = [s["signal"] for s in connect.preview("telecom_billing")["signals"]]
    assert names.count("account_takeover_step") == 2


def test_normal_activity_raises_nothing():
    normal = connect.SAMPLES["nessie"][:3]
    assert connect.preview("nessie", normal)["signals"] == []


def test_unknown_source():
    with pytest.raises(KeyError):
        connect.preview("mainframe_cobol")


def test_routes(client):
    sources = client.get("/api/connect/sources").json()
    assert {s["name"] for s in sources} >= {"nessie", "paysim", "telecom_billing"}
    r = client.post("/api/connect/paysim/preview", json={})
    assert r.status_code == 200 and r.json()["signals"]
    custom = client.post("/api/connect/paysim/preview", json={"records": [{"step": 7480, "type": "TRANSFER", "amount": 10, "nameOrig": "A", "nameDest": "B"}]})
    assert custom.status_code == 200 and custom.json()["canonical"][0]["event_type"] == "transfer_out"
    assert client.post("/api/connect/nope/preview", json={}).status_code == 404
    assert client.post("/api/connect/paysim/preview", json={"records": [{}] * 201}).status_code == 422
    samples = client.get("/api/demo/samples?category=job_offer&n=2").json()
    assert len(samples["samples"]) == 2 and "job_offer" in samples["categories"]


def test_live_demo_only_uses_real_companies_and_financial_institutions():
    samples = connect.sample_messages(n=500, seed=3)
    assert samples and all(s["claimed_brand"] in connect.DEMO_BRANDS for s in samples)
    for fake in ("Northline Mobile", "Harbor Mutual", "Hearthside Hire", "Parcel Lane", "IRS", "USPS", "TxTag", None):
        assert all(s["claimed_brand"] != fake for s in samples)
    assert "conversation_lure" not in connect.categories() and "toll_government" not in connect.categories()


def test_real_messages_come_from_official_channels():
    legit = connect.sample_messages("legit", n=10, seed=1)
    assert {s["claimed_brand"] for s in legit} <= {"Capital One", "T-Mobile"}
    assert all(not s["truth"]["is_scam"] for s in legit)
    capital_one = [s for s in legit if s["claimed_brand"] == "Capital One"]
    assert capital_one and all(s["sender"] in {"227898", "227767", "227373", "22767", "61869", "80101"} for s in capital_one)
