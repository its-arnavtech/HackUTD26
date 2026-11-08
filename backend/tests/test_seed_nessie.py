from __future__ import annotations

import statistics
from datetime import datetime

import pytest

from app.config import get_settings
from app.integrations.nessie import NessieClient, transfer_details_from_seed
from scripts import seed_nessie
from tests.fake_nessie import API_KEY, FakeNessie


@pytest.fixture(autouse=True)
def live_mode(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "live")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def client(fake: FakeNessie, seed: dict | None = None) -> NessieClient:
    return NessieClient(API_KEY, "https://api.nessieisreal.com", http=fake.client(), transfer_details=transfer_details_from_seed(seed))


def test_seed_creates_everything_in_7_7():
    fake = FakeNessie()
    report = seed_nessie.seed(client(fake))
    manifest = report.manifest

    assert set(manifest["customers"]) == {"linda", "unknown_payee"}
    assert set(manifest["accounts"]) == {"linda_checking", "linda_credit", "unknown_checking"}
    linda = fake.customers[manifest["customers"]["linda"]]
    assert linda["first_name"] == "Linda"
    assert {fake.accounts[manifest["accounts"][k]]["type"] for k in ("linda_checking", "linda_credit")} == {"Checking", "Credit Card"}

    purchase_dates = sorted({p.day for p in seed_nessie.purchase_plan()})
    assert len(manifest["purchases"]) >= 20
    assert (purchase_dates[-1] - purchase_dates[0]).days >= 25
    assert purchase_dates[-1] < seed_nessie.MESSAGE_AT.date()

    bill = fake.children[manifest["accounts"]["linda_checking"]]["bills"][0]
    assert (bill["payee"], bill["status"], bill["payment_date"], bill["recurring_date"]) == ("T-Mobile", "completed", "2026-11-01", 1)

    planted = manifest["transfers"]["planted_transfer"]
    assert planted["amount"] == 900.0
    assert planted["payer_id"] == manifest["accounts"]["linda_checking"]
    assert planted["payee_id"] == manifest["accounts"]["unknown_checking"]
    minutes_after = (datetime.fromisoformat(planted["at"]) - seed_nessie.MESSAGE_AT).total_seconds() / 60
    assert minutes_after == 17

    regular = [t["amount"] for k, t in manifest["transfers"].items() if k != "planted_transfer"]
    assert planted["amount"] / statistics.median(regular) == 6


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


def test_dry_run_changes_nothing():
    fake = FakeNessie()
    report = seed_nessie.seed(client(fake), dry_run=True)
    assert fake.posts == []
    assert "customer linda" in report.created and "transfer planted_transfer" in report.created


def test_partial_seed_is_completed():
    fake = FakeNessie()
    c = client(fake)
    c.create_customer(seed_nessie.CUSTOMERS["linda"])
    report = seed_nessie.seed(c)
    assert report.found == ["customer linda"]
    assert len(fake.customers) == 2


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
    assert all(float(p.amount).is_integer() for p in seed_nessie.purchase_plan())


def test_second_run_creates_nothing_when_nessie_truncates_amounts():
    fake = FakeNessie(truncate_purchase_amounts=True)
    seed_nessie.seed(client(fake))
    posts = len(fake.posts)
    assert seed_nessie.seed(client(fake)).created == []
    assert len(fake.posts) == posts


def duplicate_every_purchase(fake: FakeNessie, manifest: dict) -> int:
    """Recreate the live state: every planned purchase stored twice."""
    c = client(fake)
    copies = 0
    for account in ("linda_checking", "linda_credit"):
        account_id = manifest["accounts"][account]
        for p in list(fake.children[account_id]["purchases"]):
            c.create_purchase(account_id, {k: p[k] for k in ("merchant_id", "medium", "purchase_date", "amount", "status", "description")})
            copies += 1
    return copies


def purchase_keys(fake: FakeNessie, manifest: dict) -> list[tuple]:
    return sorted(
        (p["description"], p["purchase_date"], p["amount"])
        for account in ("linda_checking", "linda_credit")
        for p in fake.children[manifest["accounts"][account]]["purchases"]
    )


def test_dedupe_keeps_one_purchase_per_key_and_deletes_the_rest():
    fake = FakeNessie()
    first = seed_nessie.seed(client(fake))
    planned = len(seed_nessie.purchase_plan())
    assert duplicate_every_purchase(fake, first.manifest) == planned

    report = seed_nessie.seed(client(fake, first.manifest), dedupe=True)
    assert report.created == []
    assert len(report.deleted) == planned
    keys = purchase_keys(fake, first.manifest)
    assert len(keys) == planned == len(set(keys))
    assert report.manifest["purchases"] == first.manifest["purchases"]
    assert set(report.manifest["purchases"].values()) <= {p["_id"] for a in fake.children.values() for p in a["purchases"]}

    again = seed_nessie.seed(client(fake, first.manifest), dedupe=True)
    assert again.created == [] and again.deleted == []


def test_dedupe_dry_run_and_no_flag_delete_nothing():
    fake = FakeNessie()
    first = seed_nessie.seed(client(fake))
    duplicate_every_purchase(fake, first.manifest)
    before = purchase_keys(fake, first.manifest)

    dry = seed_nessie.seed(client(fake), dry_run=True, dedupe=True)
    assert len(dry.deleted) == len(seed_nessie.purchase_plan())
    assert seed_nessie.seed(client(fake)).deleted == []
    assert purchase_keys(fake, first.manifest) == before
    assert not any(r.method == "DELETE" for r in fake.requests)
