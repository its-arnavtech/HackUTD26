from __future__ import annotations

import statistics
from datetime import datetime

import pytest

from app.config import get_settings
from app.integrations.nessie import NessieClient, purchase_times_from_seed, transfer_details_from_seed
from scripts import seed_nessie
from tests.fake_nessie import API_KEY, TRANSFER_FIELDS, FakeNessie


@pytest.fixture(autouse=True)
def live_mode(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "live")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def client(fake: FakeNessie, seed: dict | None = None) -> NessieClient:
    return NessieClient(
        API_KEY,
        "https://api.nessieisreal.com",
        http=fake.client(),
        transfer_details=transfer_details_from_seed(seed),
        purchase_times=purchase_times_from_seed(seed),
    )


def test_seed_creates_everything_in_7_7():
    fake = FakeNessie()
    report = seed_nessie.seed(client(fake))
    manifest = report.manifest

    assert set(manifest["customers"]) == {"linda"}
    assert set(manifest["accounts"]) == {"linda_checking", "linda_credit"}
    linda = fake.customers[manifest["customers"]["linda"]]
    assert (linda["first_name"], linda["address"]["street_number"]) == ("Linda", "802")
    assert {fake.accounts[manifest["accounts"][k]]["type"] for k in ("linda_checking", "linda_credit")} == {"Checking", "Credit Card"}

    purchase_dates = sorted({p.day for p in seed_nessie.purchase_plan()})
    assert len(manifest["purchases"]) >= 20
    assert (purchase_dates[-1] - purchase_dates[0]).days >= 25
    assert purchase_dates[-1] < seed_nessie.MESSAGE_AT.date()

    bill = fake.children[manifest["accounts"]["linda_checking"]]["bills"][0]
    assert (bill["payee"], bill["status"], bill["payment_date"], bill["recurring_date"]) == ("T-Mobile", "completed", "2026-11-01", 1)


def test_planted_900_is_a_first_purchase_at_unknown_payee_17_minutes_after_the_message():
    fake = FakeNessie()
    manifest = seed_nessie.seed(client(fake)).manifest
    planted = manifest["planted"]
    assert planted["type"] == "purchase" and planted["amount"] == 900
    assert planted["account_id"] == manifest["accounts"]["linda_checking"]
    assert fake.merchants[planted["merchant_id"]]["name"] == "Unknown Payee"
    minutes_after = (datetime.fromisoformat(planted["at"]) - seed_nessie.MESSAGE_AT).total_seconds() / 60
    assert minutes_after == 17
    assert manifest["purchase_times"] == {planted["id"]: planted["at"]}

    stored = [p for a in fake.children.values() for p in a["purchases"] if p["_id"] == planted["id"]]
    assert stored and stored[0]["merchant_id"] == planted["merchant_id"] and stored[0]["purchase_date"] == "2026-11-08"
    earlier_at_merchant = [p for p in seed_nessie.purchase_plan() if p.merchant == "unknown_payee"]
    assert earlier_at_merchant == []
    assert 900 / statistics.median(p.amount for p in seed_nessie.purchase_plan()) > 20


def test_transfers_send_only_the_fields_nessie_accepts():
    fake = FakeNessie()
    manifest = seed_nessie.seed(client(fake)).manifest  # the fake 400s on any other field
    checking = manifest["accounts"]["linda_checking"]
    sent = fake.children[checking]["transfers"]
    assert len(sent) == len(seed_nessie.transfer_plan())
    for t in sent:
        assert set(t) - {"_id", "type", "payer_id"} == set(TRANSFER_FIELDS)
    for t in manifest["transfers"].values():
        assert t["payee_id"] == manifest["accounts"]["linda_credit"]  # kept in the manifest, own account


def test_second_run_creates_nothing_and_keeps_ids():
    fake = FakeNessie()
    first = seed_nessie.seed(client(fake))
    posts_after_first = len(fake.posts)

    second = seed_nessie.seed(client(fake, first.manifest))
    assert second.created == []
    assert len(fake.posts) == posts_after_first
    assert second.manifest == first.manifest
    assert len(second.found) == len(first.created)


def test_rerun_works_without_a_manifest():
    fake = FakeNessie()
    first = seed_nessie.seed(client(fake))
    second = seed_nessie.seed(client(fake))
    assert second.created == []
    assert second.manifest["transfers"] == first.manifest["transfers"]
    assert second.manifest["planted"] == first.manifest["planted"]


def test_abandoned_linda_at_800_demo_way_is_never_reused():
    fake = FakeNessie()
    c = client(fake)
    old = c.create_customer({**seed_nessie.CUSTOMERS["linda"], "address": {**seed_nessie.ADDRESS, "street_number": "800"}})
    old_checking = c.create_account(old["_id"], {"type": "Checking", "nickname": "Linda Everyday Checking"})
    for _ in range(2):  # the duplicates an earlier run left behind
        c.create_purchase(old_checking["_id"], {"purchase_date": "2026-11-07", "amount": 49, "description": "Groceries"})

    manifest = seed_nessie.seed(client(fake)).manifest
    assert manifest["customers"]["linda"] != old["_id"]
    assert old_checking["_id"] not in manifest["accounts"].values()
    keys = [(p["description"], p["purchase_date"], p["amount"]) for p in fake.children[manifest["accounts"]["linda_checking"]]["purchases"]]
    assert len(keys) == len(set(keys))


def test_dry_run_changes_nothing():
    fake = FakeNessie()
    report = seed_nessie.seed(client(fake), dry_run=True)
    assert fake.posts == []
    assert "customer linda" in report.created and "purchase planted_purchase" in report.created


def test_partial_seed_is_completed():
    fake = FakeNessie()
    c = client(fake)
    c.create_customer(seed_nessie.CUSTOMERS["linda"])
    report = seed_nessie.seed(c)
    assert report.found == ["customer linda"]
    assert len(fake.customers) == 1


def test_seed_never_deletes():
    fake = FakeNessie()
    seed_nessie.seed(client(fake))
    seed_nessie.seed(client(fake))
    assert not any(r.method == "DELETE" for r in fake.requests)
    assert "--dedupe" not in (seed_nessie.__doc__ or "")


def test_api_key_never_lands_in_the_manifest():
    report = seed_nessie.seed(client(FakeNessie()))
    assert API_KEY not in str(report.manifest)


def test_main_reports_missing_key(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("NESSIE_API_KEY", "")
    get_settings.cache_clear()
    assert seed_nessie.main(["--out", str(tmp_path / "seed.json")]) == 1
    assert "NESSIE_API_KEY" in capsys.readouterr().err
    assert not (tmp_path / "seed.json").exists()


def test_purchase_amounts_are_whole_dollars():
    assert all(float(p.amount).is_integer() for p in [*seed_nessie.purchase_plan(), seed_nessie.planted_purchase()])


def test_second_run_creates_nothing_when_nessie_truncates_amounts():
    fake = FakeNessie(truncate_purchase_amounts=True)
    seed_nessie.seed(client(fake))
    posts = len(fake.posts)
    assert seed_nessie.seed(client(fake)).created == []
    assert len(fake.posts) == posts
