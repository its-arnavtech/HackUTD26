"""L15b: official contact, opt-in scam memory, delete my data."""

from __future__ import annotations

import pytest

from app import protection


@pytest.fixture(autouse=True)
def _clean():
    protection.clear()
    yield
    protection.clear()


def test_official_contact_only_from_verified_list():
    c1 = protection.official_contact("capital one")
    assert c1["verified"] and c1["domains"] == ["capitalone.com"] and "227898" in c1["short_codes"]
    unknown = protection.official_contact("Totally Real Bank")
    assert not unknown["verified"] and unknown["domains"] == [] and "back of your card" in unknown["advice"]


def test_memory_needs_consent_and_keeps_no_text():
    ind = {"brand": "Chase", "category": "bank_impersonation", "domain": "chase-verify.test", "wording": "abc"}
    assert protection.remember("u", "m1", ind) == {"consent": False, "matches": []}
    protection.set_consent("u", True)
    assert protection.remember("u", "m1", ind)["matches"] == []
    again = protection.remember("u", "m2", {**ind, "wording": "zzz"})
    assert "the same link domain" in again["matches"][0]["why"] and "the same Chase lure" in again["matches"][0]["why"]
    kept = protection.view("u")["items"]
    assert len(kept) == 2 and set(kept[0]) == {"at", "brand", "category", "domain"}  # no text, no message id
    protection.set_consent("u", False)
    assert protection.view("u") == {"consent": False, "items": []}  # opting out deletes


def test_indicators_are_minimized():
    ind = protection.indicators_from_privacy({
        "text_redacted": "Chase: verify <PERSON> at <URL_1> now", "sender": {"claimed_brand": "Chase"},
        "classifier": {"category": "bank_impersonation"}, "urls": [{"registered_domain": "chase-x.test"}],
    })
    assert ind["brand"] == "Chase" and ind["domain"] == "chase-x.test" and len(ind["wording"]) == 12 and "verify" not in ind["wording"]


def test_routes(client):
    assert client.get("/api/official-contact?brand=T-Mobile").json()["domains"] == ["t-mobile.com"]
    assert client.put("/api/memory/consent", json={"on": True}).json()["consent"] is True
    r = client.post("/api/memory/msg_0001")
    assert r.status_code == 200 and r.json()["consent"] is True
    gone = client.delete("/api/my-data").json()
    assert gone["deleted"] is True
    assert client.get("/api/memory").json() == {"consent": False, "items": []}
