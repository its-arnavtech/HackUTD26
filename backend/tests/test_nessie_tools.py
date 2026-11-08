from __future__ import annotations

import json
from datetime import date, datetime

import pytest

from app.config import get_settings
from app.contracts import (
    AgentMode,
    NessieBillStatusArgs,
    NessieBillStatusResult,
    NessieRecentActivityArgs,
    NessieRecentActivityResult,
)
from app.integrations.nessie import NessieClient, NessieError, transfer_details_from_seed
from app.tools import nessie_tools
from app.tools.nessie_tools import (
    NESSIE_BILL_STATUS_SPEC,
    NESSIE_RECENT_ACTIVITY_SPEC,
    nessie_bill_status,
    nessie_recent_activity,
    resolve_ref,
)
from scripts import seed_nessie
from tests.agent_input_factory import RECEIVED_AT, make_input
from tests.fake_nessie import API_KEY, FakeNessie


@pytest.fixture(autouse=True)
def live_mode(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "live")
    get_settings.cache_clear()
    nessie_tools._REF_DETAILS.clear()
    yield
    get_settings.cache_clear()
    nessie_tools._REF_DETAILS.clear()


@pytest.fixture
def bank():
    """A fake Nessie seeded exactly like the demo, plus a client that knows the manifest."""
    fake = FakeNessie()
    bootstrap = NessieClient(API_KEY, "https://api.nessieisreal.com", http=fake.client())
    manifest = seed_nessie.seed(bootstrap).manifest
    client = NessieClient(API_KEY, "https://api.nessieisreal.com", http=fake.client(), transfer_details=transfer_details_from_seed(manifest))
    return fake, client, manifest


def check_input():
    return make_input()


def recovery_input():
    base = make_input()
    return base.model_copy(update={"mode": AgentMode.recovery, "since": base.received_at})


def activity(bank, args, agent_input):
    _, client, manifest = bank
    return nessie_recent_activity(args, agent_input, client=client, seed=manifest)


def test_scenario_1_check_mode_finds_nothing_unusual(bank):
    result = activity(bank, NessieRecentActivityArgs(days=7), check_input())
    assert result.accounts_checked == 2
    assert result.items_checked > 5
    assert result.flagged == []


def test_scenario_2_recovery_finds_the_planted_transfer(bank):
    result = activity(bank, NessieRecentActivityArgs(since=datetime.fromisoformat(RECEIVED_AT)), recovery_input())
    assert result.items_checked == 1
    [item] = result.flagged
    assert item.type == "transfer"
    assert item.amount == 900
    assert item.new_payee is True
    assert item.minutes_after_message == 17
    assert item.reason == "new payee, 6x the 30-day median"
    assert item.ref.startswith("txn_")


def test_check_mode_never_sees_activity_after_the_message(bank):
    result = activity(bank, NessieRecentActivityArgs(days=30), check_input())
    assert all(f.amount != 900 for f in result.flagged)


def test_ref_resolves_to_customer_facing_details_only_in_the_app(bank):
    _, client, manifest = bank
    [item] = activity(bank, NessieRecentActivityArgs(since=datetime.fromisoformat(RECEIVED_AT)), recovery_input()).flagged
    detail = resolve_ref(item.ref, client=client, seed=manifest)
    assert (detail.payee, detail.amount, detail.type) == ("Unknown Payee", 900, "transfer")
    assert detail.at == datetime.fromisoformat("2026-11-08T09:31:00-06:00")

    nessie_tools._REF_DETAILS.clear()
    assert resolve_ref(item.ref, client=client, seed=manifest) == detail  # same ref after a restart


def test_unknown_ref(bank):
    _, client, manifest = bank
    with pytest.raises(KeyError):
        resolve_ref("txn_9999", client=client, seed=manifest)


def test_first_purchase_at_a_new_merchant_is_flagged(bank):
    fake, client, manifest = bank
    merchant = client.create_merchant({"name": "Sentinel Demo Electronics", "category": "Electronics"})
    client.create_purchase(
        manifest["accounts"]["linda_credit"],
        {"merchant_id": merchant["_id"], "medium": "balance", "purchase_date": "2026-11-06", "amount": 499.0, "description": "Electronics"},
    )
    result = activity(bank, NessieRecentActivityArgs(days=7), check_input())
    [item] = result.flagged
    assert (item.type, item.amount, item.reason, item.new_payee) == ("purchase", 499.0, "first purchase at this merchant", False)
    assert item.minutes_after_message is None
    assert resolve_ref(item.ref, client=client, seed=manifest).payee == "Sentinel Demo Electronics"


def test_results_never_carry_names_account_numbers_or_merchants(bank):
    fake, _, manifest = bank
    results = [
        activity(bank, NessieRecentActivityArgs(since=datetime.fromisoformat(RECEIVED_AT)), recovery_input()),
        activity(bank, NessieRecentActivityArgs(days=30), check_input()),
        nessie_bill_status(NessieBillStatusArgs(payee="T-Mobile"), check_input(), client=bank[1], seed=manifest),
    ]
    dumped = json.dumps([r.model_dump(mode="json") for r in results])
    forbidden = ["Linda", "Sentinel", "Unknown", "Payee", "Grocery", "Coffee", "4444"]
    forbidden += list(manifest["accounts"].values()) + [m for m in manifest["merchants"].values()]
    for word in forbidden:
        assert word not in dumped


def test_scenario_3_bill_is_paid(bank):
    _, client, manifest = bank
    result = nessie_bill_status(NessieBillStatusArgs(payee="T-Mobile"), check_input(), client=client, seed=manifest)
    assert result == NessieBillStatusResult(
        found=True, last_status="completed", last_payment_date=date(2026, 11, 1), amount_due_now=0, recurring=True
    )
    assert nessie_bill_status(NessieBillStatusArgs(payee="tmobile"), check_input(), client=client, seed=manifest).found


def test_pending_bill_is_due_and_latest_wins(bank):
    _, client, manifest = bank
    client.create_bill(
        manifest["accounts"]["linda_checking"],
        {"status": "pending", "payee": "T-Mobile", "nickname": "Phone bill", "payment_date": "2026-12-01", "payment_amount": 85.0},
    )
    result = nessie_bill_status(NessieBillStatusArgs(payee="T-Mobile"), check_input(), client=client, seed=manifest)
    assert (result.last_status, result.amount_due_now, result.recurring) == ("pending", 85.0, False)


def test_unknown_payee_bill_not_found(bank):
    _, client, manifest = bank
    assert nessie_bill_status(NessieBillStatusArgs(payee="Acme Power"), check_input(), client=client, seed=manifest) == NessieBillStatusResult(found=False)


def test_missing_seed_is_a_clear_error(bank):
    _, client, _ = bank
    with pytest.raises(NessieError, match="seed_nessie"):
        nessie_recent_activity(NessieRecentActivityArgs(days=7), check_input(), client=client, seed={})


def test_specs_match_contracts():
    assert NESSIE_RECENT_ACTIVITY_SPEC.args_model is NessieRecentActivityArgs
    assert NESSIE_RECENT_ACTIVITY_SPEC.result_model is NessieRecentActivityResult
    assert NESSIE_BILL_STATUS_SPEC.args_model is NessieBillStatusArgs
    assert NESSIE_BILL_STATUS_SPEC.result_model is NessieBillStatusResult
