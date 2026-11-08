"""Synthetic linked scenarios, canonical events, and source mappings.

The generator is seeded and offline. These tests check the committed files and
that a rebuild matches them byte for byte.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone

import jsonschema
import pytest

from app.adapters.mapping_loader import apply_mapping, available_mappings, configure, load_mapping
from app.config import DATA_DIR
from app.integrations.rdap import domain_age_days
from scripts.gen_linked_scenarios import SEED, TAXONOMY, TELECOM_TYPES, render_blobs

GENERATED = DATA_DIR / "generated"
SCHEMA = json.loads((GENERATED / "payment_schema.json").read_text(encoding="utf-8"))
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA)

PHONE = re.compile(r"\+\d{10,}|555-\d{4}")


def _lines(name: str) -> list[dict]:
    path = GENERATED / name
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


@pytest.fixture(scope="module")
def messages():
    return _lines("messages_multiclass.jsonl")


@pytest.fixture(scope="module")
def campaigns():
    return _lines("campaigns.jsonl")


@pytest.fixture(scope="module")
def urls():
    return _lines("urls.jsonl")


@pytest.fixture(scope="module")
def scenarios():
    return _lines("linked_scenarios.jsonl")


@pytest.fixture(scope="module")
def telecom():
    return _lines("telecom_events.jsonl")


def test_payment_schema_is_a_schema():
    jsonschema.Draft202012Validator.check_schema(SCHEMA)
    assert "event_id" in SCHEMA["required"]
    assert "esim_transfer" in SCHEMA["properties"]["event_type"]["enum"]


def test_message_counts_and_shape(messages):
    assert len(messages) >= 150 * len(TAXONOMY)
    by_cat = Counter(row["taxonomy_id"] for row in messages)
    assert set(by_cat) == set(TAXONOMY)
    assert all(count >= 150 for count in by_cat.values())
    by_split = Counter(row["split"] for row in messages)
    assert by_split["train"] == 1260
    assert by_split["validation"] == 270
    assert by_split["test"] == 270
    subtypes = Counter(row["subtype"] for row in messages if row["taxonomy_id"] == "legit")
    for subtype in ("carrier_bill", "otp", "delivery"):
        assert subtypes[subtype] >= 20
    for row in messages:
        assert row["template_set"] in {"A", "B"}
        assert row["mode"] == "check"
        assert row["classifier"]["category"] == row["taxonomy_id"]
        assert row["is_scam"] is (row["taxonomy_id"] != "legit")
        assert row["sender"]["type"] in {"short_code", "long_code", "alphanumeric", "email", "unknown"}
        if row["sender"]["type"] == "long_code":
            assert row["sender"]["value"].startswith("<PHONE_HASH_")
        assert not PHONE.search(row["text_redacted"])
        if row["source_url"]:
            assert row["source_url"].startswith("https://")
            host = row["source_url"].split("/")[2]
            assert host.endswith(".test") or host.endswith(".example")
        if row["split"] == "test":
            assert row["template_set"] == "B"
        else:
            assert row["template_set"] == "A"


def test_no_train_test_leakage(messages):
    def grab(split: str):
        rows = [row for row in messages if row["split"] == split]
        return {
            "template": {row["template_id"] for row in rows},
            "skeleton": {row["template_skeleton"] for row in rows},
            "url": {row["source_url"] for row in rows if row["source_url"]},
            "sender": {row["sender"]["value"] for row in rows},
        }

    train, validation, test = grab("train"), grab("validation"), grab("test")
    for key in ("template", "skeleton", "url", "sender"):
        assert train[key].isdisjoint(test[key]), key
        assert validation[key].isdisjoint(test[key]), key
    # Set A may repeat a template between train and validation. Set B is test only.
    assert train["template"].isdisjoint(test["template"])


def test_campaigns(campaigns, messages):
    by_id = defaultdict(list)
    for row in campaigns:
        by_id[row["campaign_id"]].append(row)
    assert len(by_id) >= 30
    message_urls = {row["source_url"] for row in messages if row["source_url"]}
    message_senders = {row["sender"]["value"] for row in messages}
    for campaign_id, rows in by_id.items():
        assert 5 <= len(rows) <= 15, campaign_id
        assert len({row["variant_index"] for row in rows}) == len(rows)
        assert len({row["sender"]["value"] for row in rows}) == len(rows)
        assert len({row["url"] for row in rows}) == len(rows)
        assert len({row["template_skeleton"] for row in rows}) == len(rows)
        assert {row["template_set"] for row in rows} == {"A"}
        assert {row["taxonomy_id"] for row in rows} == {rows[0]["taxonomy_id"]}
        assert rows[0]["taxonomy_id"] in TAXONOMY and rows[0]["taxonomy_id"] != "legit"
    assert {row["url"] for row in campaigns}.isdisjoint(message_urls)
    assert {row["sender"]["value"] for row in campaigns}.isdisjoint(message_senders)
    assert any(row["url"] == "https://tm0bile-billing.test/pay" for row in campaigns)


def test_urls_and_rdap(urls):
    techniques = {row["technique"] for row in urls}
    assert {"typosquat", "homoglyph", "subdomain abuse", "URL shortener", "fresh registration"} <= techniques
    assert {row["label"] for row in urls} == {"phishing", "legit"}
    found_false = 0
    for row in urls:
        assert row["domain"].endswith(".test") or row["domain"].endswith(".example"), row["domain"]
        assert row["host"].endswith(".test") or row["host"].endswith(".example"), row["host"]
        assert set(row["rdap"]) == {"found", "registered_at", "registrar"}
        record = {"found": row["rdap"]["found"], "registered_at": row["rdap"]["registered_at"]}
        if row["rdap"]["found"]:
            assert row["rdap"]["registered_at"].endswith("Z")
            age = domain_age_days(record, datetime(2026, 11, 8, tzinfo=timezone.utc))
            assert age is not None and age >= 0
        else:
            found_false += 1
            assert domain_age_days(record, datetime(2026, 11, 8, tzinfo=timezone.utc)) is None
    assert found_false >= 1


def test_scenarios_cover_the_stories(scenarios):
    assert len(scenarios) >= 300
    fraud = [row for row in scenarios if row["ground_truth"]["is_fraud"]]
    benign = [row for row in scenarios if not row["ground_truth"]["is_fraud"]]
    assert 0.35 <= len(benign) / len(scenarios) <= 0.45
    kinds = Counter(row["ground_truth"]["fraud_type"] for row in fraud)
    for kind in (
        "billing_unknown_payee",
        "delivery_cnp",
        "carrier_takeover",
        "toll_payment",
        "refund_overpay",
        "job_deposit",
    ):
        assert kinds[kind] >= 1
    assert any(row["taxonomy_id"] != "legit" for row in benign)
    assert any(row["taxonomy_id"] == "legit" for row in benign)
    assert any(row["campaign_id"] is None for row in scenarios)
    assert any(row["campaign_id"] for row in scenarios)
    assert any(row["click"] is None for row in scenarios)
    assert any(row["click"] and row["click"]["clicked"] for row in scenarios)

    def posts(kind: str):
        return next(row for row in scenarios if row["ground_truth"]["fraud_type"] == kind)["post_events"]

    billing = posts("billing_unknown_payee")
    assert any(event["event_type"] == "bill_payment" and event["counterparty_name"] == "Unknown Payee" and event["counterparty_first_seen"] for event in billing)
    delivery = posts("delivery_cnp")
    assert any(event["channel"] == "card_not_present" for event in delivery)
    takeover = posts("carrier_takeover")
    takeover_types = {event["event_type"] for event in takeover}
    assert takeover_types & {"sim_change", "esim_transfer", "port_out_request"}
    assert "password_reset" in takeover_types and "transfer_out" in takeover_types
    toll = posts("toll_payment")
    assert any(event["event_type"] == "bill_payment" and event["counterparty_name"] != "Northline Mobile" for event in toll)
    refund = posts("refund_overpay")
    assert any(event["event_type"] == "transfer_out" for event in refund)
    job = posts("job_deposit")
    assert [event["event_type"] for event in job][:2] == ["deposit", "transfer_out"]
    legit = next(row for row in benign if row["taxonomy_id"] == "legit")
    assert any(event["event_type"] == "bill_payment" and event["counterparty_name"] == "Northline Mobile" and not event["labels"]["is_fraud"] for event in legit["post_events"])


def test_events_match_schema_and_signals(scenarios, telecom):
    signal_names = {
        "new_payee",
        "amount_far_from_baseline",
        "channel_never_used",
        "bill_nonmatching_biller",
        "new_device_or_sim_near_payment",
        "timing_near_message",
    }
    seen = {True: set(), False: set()}
    event_ids = set()
    for scenario in scenarios:
        message_at = datetime.fromisoformat(scenario["message"]["received_at"]).astimezone(timezone.utc)
        baseline, post = scenario["baseline_events"], scenario["post_events"]
        assert baseline and post
        first = datetime.strptime(baseline[0]["timestamp"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        last = datetime.strptime(baseline[-1]["timestamp"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        assert 30 <= (message_at - first).days <= 60
        assert last < message_at
        for event in post:
            assert datetime.strptime(event["timestamp"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) > message_at
        for event in [*baseline, *post]:
            assert event["event_id"] not in event_ids
            event_ids.add(event["event_id"])
            errors = list(VALIDATOR.iter_errors(event))
            assert not errors, errors[0].message
        fraud_ids = [event["event_id"] for event in post if event["labels"]["is_fraud"]]
        truth = scenario["ground_truth"]
        if truth["is_fraud"]:
            assert truth["first_fraud_event_id"] == fraud_ids[0]
            assert truth["first_fraud_event_id"] in {event["event_id"] for event in post}
        else:
            assert truth["first_fraud_event_id"] is None
            assert fraud_ids == []
        assert set(truth["signals"]) == signal_names
        for name, value in truth["signals"].items():
            seen[bool(value)].add(name)
        for key in ("message_id", "mode", "received_at", "sender", "text_redacted", "urls", "features", "classifier", "customer_context"):
            assert key in scenario["message"]
    assert seen[True] == signal_names
    assert seen[False] == signal_names
    assert TELECOM_TYPES <= {event["event_type"] for event in telecom}
    for event in telecom:
        assert not list(VALIDATOR.iter_errors(event))


def test_nessie_export_round_trip(scenarios):
    mapping = load_mapping("nessie")
    money = {"purchase", "transfer_out", "transfer_in", "deposit", "withdrawal", "refund"}
    bill_types = {"bill_payment", "bill_issued"}
    section6 = {
        "customers": {"_id", "first_name", "last_name"},
        "accounts": {"_id", "type", "nickname", "balance", "customer_id"},
        "purchases": {"_id", "merchant_id", "purchase_date", "amount", "status", "description"},
        "transfers": {"_id", "payer_id", "payee_id", "transaction_date", "amount", "status", "description"},
        "bills": {"_id", "status", "payee", "nickname", "payment_date", "recurring_date", "payment_amount"},
        "merchants": {"_id", "name", "category"},
    }
    for scenario in scenarios:
        export = json.loads((GENERATED / "nessie_export" / f"{scenario['scenario_id']}.json").read_text(encoding="utf-8"))
        assert export["scenario_id"] == scenario["scenario_id"]
        for name, fields in section6.items():
            assert export[name], name
            for obj in export[name]:
                assert set(obj) == fields
        events = {event["event_id"]: event for event in [*scenario["baseline_events"], *scenario["post_events"]]}
        linked = {link["event_id"] for link in export["manifest"]["links"]}
        for event in events.values():
            exports_as_bill = event["event_type"] in bill_types and event["bill"] is not None
            if event["event_type"] in money or exports_as_bill:
                assert event["event_id"] in linked
        objects = {
            "purchase": {obj["_id"]: obj for obj in export["purchases"]},
            "transfer": {obj["_id"]: obj for obj in export["transfers"]},
            "bill": {obj["_id"]: obj for obj in export["bills"]},
        }
        for link in export["manifest"]["links"]:
            wrapped = dict(objects[link["object"]][link["object_id"]])
            wrapped.update(event_type=link["event_type"], account_id=link["account_id"], at=link["at"])
            got = apply_mapping(wrapped, mapping)
            assert got["source_system"] == "nessie"
            assert got["event_type"] == link["event_type"]
            assert got["amount_minor"] == link["amount_minor_truncated"]
            assert got["timestamp"][:10] == link["at"][:10]
            source = events[link["event_id"]]
            assert got["amount_minor"] == (source["amount_minor"] // 100) * 100


def test_mapping_files_cover_every_source():
    assert available_mappings() == [
        "generic_card_processor",
        "ibm_aml",
        "nessie",
        "paysim",
        "sparkov",
        "telecom_billing",
    ]
    nessie = configure("nessie")
    purchase = nessie({"_object": "purchase", "amount": 49, "purchase_date": "2026-10-10", "merchant_id": "m1", "account_id": "acct"})
    assert purchase["event_type"] == "purchase"
    assert purchase["amount_minor"] == 4900
    assert purchase["timestamp"] == "2026-10-10T00:00:00Z"
    assert purchase["currency"] == "USD"
    assert purchase["account_id"] == "acct"

    paysim = apply_mapping(
        {"type": "TRANSFER", "step": 3, "amount": 12.5, "nameOrig": "C1", "nameDest": "C2", "newbalanceOrig": 40, "isFraud": 1},
        load_mapping("paysim"),
    )
    assert paysim["event_type"] == "transfer_out"
    assert paysim["timestamp"] == "2026-01-01T03:00:00Z"
    assert paysim["amount_minor"] == 1250
    assert paysim["balance_after_minor"] == 4000
    assert paysim["labels"]["is_fraud"] is True
    assert paysim["merchant_category"] is None

    sparkov = apply_mapping(
        {"trans_date_trans_time": "2026-10-02 15:04:05", "cc_num": "4000", "merchant": "Demo Grocery", "category": "grocery", "amt": 12.5, "is_fraud": 0},
        load_mapping("sparkov"),
    )
    assert sparkov["event_type"] == "purchase"
    assert sparkov["timestamp"] == "2026-10-02T15:04:05Z"
    assert sparkov["amount_minor"] == 1250
    assert sparkov["labels"]["is_fraud"] is False

    ibm = apply_mapping(
        {"Payment Format": "Wire", "Timestamp": "2026-10-03T00:00:00Z", "Account": "A1", "Account.1": "A2", "Amount Paid": 10, "Payment Currency": "EUR", "Is Laundering": "false"},
        load_mapping("ibm_aml"),
    )
    assert ibm["event_type"] == "transfer_out"
    assert ibm["channel"] == "wire"
    assert ibm["currency"] == "EUR"
    assert ibm["amount_minor"] == 1000
    assert ibm["counterparty_id"] == "A2"
    assert ibm["labels"]["is_fraud"] is False

    card = apply_mapping(
        {"txn_type": "auth", "authorization_time": "2026-10-01T00:00:00Z", "card_token": "tok", "merchant_name": "Shop", "amount_cents": 4990, "entry_mode": "ECOM", "mcc": "5732", "is_fraud": 0},
        load_mapping("generic_card_processor"),
    )
    assert card["event_type"] == "purchase"
    assert card["amount_minor"] == 4990
    assert card["channel"] == "card_not_present"
    assert card["merchant_category"] == "5732"

    telecom = apply_mapping(
        {"event_code": "ESIM_TRANSFER", "event_time": "2026-11-01T12:00:00Z", "msisdn": "+15555550180", "charge": 0, "sim_iccid": "8901", "bill_status": "open"},
        load_mapping("telecom_billing"),
    )
    assert telecom["event_type"] == "esim_transfer"
    assert telecom["merchant_category"] == "carrier"
    assert telecom["device"]["device_id"] == "8901"
    assert telecom["bill"]["status"] == "pending"
    with pytest.raises(FileNotFoundError):
        load_mapping("not-a-source")


def test_committed_files_match_the_seeded_generator():
    first = render_blobs()
    second = render_blobs()
    assert first.keys() == second.keys()
    for relative, text in first.items():
        assert text == second[relative]
        assert (GENERATED / relative).read_text(encoding="utf-8") == text
    readme = first["SYNTHETIC_LINKED_README.md"]
    assert "synthetic only — not real customer data" in readme
    assert str(SEED) in readme
    assert "no LLM API" in readme


def test_a21_messages_were_not_rewritten():
    """The new files sit beside the A21 set. The first generated id stays put."""
    first = (GENERATED / "messages.jsonl").read_text(encoding="utf-8").splitlines()[0]
    assert json.loads(first)["message_id"] == "tr_00001"
    assert (GENERATED / "splits.json").is_file()
    assert "A21" in (GENERATED / "README.md").read_text(encoding="utf-8")
