"""Seed Nessie for the demo (POC_MVP.md 7.7) and save the IDs to data/nessie_seed.json.

Linda has a checking account and a credit card, about 30 days of purchases at a
few merchants, regular credit card payments, and a recurring T-Mobile bill marked
completed. "Unknown Payee" has one account, which receives the planted $900
transfer 17 minutes after scenario 2's message.

Idempotent: every object has a natural key (name, nickname, or description plus
date plus amount), and anything already in Nessie is reused, so a second run
creates nothing.

Run from `backend/` with NESSIE_API_KEY in .env:
    python -m scripts.seed_nessie            # create what's missing, write the manifest
    python -m scripts.seed_nessie --dry-run  # list what would be created
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

from app.integrations.nessie import SEED_PATH, NessieClient, NessieError, client_from_settings

CENTRAL = timezone(timedelta(hours=-6))  # CST on the demo date
MESSAGE_AT = datetime(2026, 11, 8, 9, 14, tzinfo=CENTRAL)  # scenario 2's received_at
PLANTED_AT = MESSAGE_AT + timedelta(minutes=17)
FIRST_DAY = MESSAGE_AT.date() - timedelta(days=30)

ADDRESS = {"street_number": "800", "street_name": "Demo Way", "city": "Richardson", "state": "TX", "zip": "75080"}
GEOCODE = {"lat": 32.9858, "lng": -96.7501}

CUSTOMERS: dict[str, dict[str, Any]] = {
    "linda": {"first_name": "Linda", "last_name": "Sentinel", "address": ADDRESS},
    "unknown_payee": {"first_name": "Unknown", "last_name": "Payee", "address": {**ADDRESS, "street_number": "1"}},
}

ACCOUNTS: dict[str, tuple[str, dict[str, Any]]] = {
    "linda_checking": ("linda", {"type": "Checking", "nickname": "Linda Everyday Checking", "rewards": 0, "balance": 4200}),
    "linda_credit": ("linda", {"type": "Credit Card", "nickname": "Linda Rewards Card", "rewards": 1200, "balance": 640}),
    "unknown_checking": ("unknown_payee", {"type": "Checking", "nickname": "External Checking", "rewards": 0, "balance": 0}),
}

MERCHANTS: dict[str, dict[str, Any]] = {
    key: {"name": f"Sentinel Demo {name}", "category": category, "address": ADDRESS, "geocode": GEOCODE}
    for key, name, category in [
        ("grocery", "Grocery", "Grocery"),
        ("coffee", "Coffee", "Food"),
        ("fuel", "Fuel", "Gas"),
        ("pharmacy", "Pharmacy", "Health"),
        ("streaming", "Streaming", "Entertainment"),
    ]
}

BILLS: dict[str, tuple[str, dict[str, Any]]] = {
    "tmobile": (
        "linda_checking",
        {
            "status": "completed",
            "payee": "T-Mobile",
            "nickname": "Phone bill",
            "payment_date": "2026-11-01",
            "recurring_date": 1,
            "payment_amount": 85.0,
        },
    )
}


@dataclass(frozen=True)
class PurchasePlan:
    key: str
    account: str
    merchant: str
    day: date
    amount: float
    description: str


@dataclass(frozen=True)
class TransferPlan:
    key: str
    payer: str
    payee: str
    day: date
    at: datetime
    amount: float
    description: str


def purchase_plan() -> list[PurchasePlan]:
    """About 30 days of ordinary purchases, ending the day before the message."""
    schedule = [
        # merchant, account, every n days, first offset, amounts (cycled), description
        ("grocery", "linda_checking", 4, 1, [64.12, 58.40, 71.95, 49.30], "Groceries"),
        ("coffee", "linda_credit", 3, 0, [5.75, 6.25], "Coffee"),
        ("fuel", "linda_credit", 7, 2, [42.10, 39.85], "Fuel"),
        ("pharmacy", "linda_checking", 30, 12, [18.99], "Pharmacy"),
        ("streaming", "linda_credit", 30, 5, [15.49], "Streaming subscription"),
    ]
    plans = []
    for merchant, account, every, offset, amounts, description in schedule:
        for i, n in enumerate(range(offset, 30, every)):
            day = FIRST_DAY + timedelta(days=n)
            plans.append(PurchasePlan(f"{merchant}_{day.isoformat()}", account, merchant, day, amounts[i % len(amounts)], description))
    return plans


def transfer_plan() -> list[TransferPlan]:
    """Monthly-ish card payments set the 30-day median; the planted transfer is 6x it, to a new payee."""
    noon = time(12, 0, tzinfo=CENTRAL)
    payments = [
        TransferPlan(f"card_payment_{d.isoformat()}", "linda_checking", "linda_credit", d, datetime.combine(d, noon), amount, "Credit card payment")
        for d, amount in [(date(2026, 10, 12), 120.0), (date(2026, 10, 24), 150.0), (date(2026, 11, 3), 180.0)]
    ]
    planted = TransferPlan(
        "planted_transfer", "linda_checking", "unknown_checking", PLANTED_AT.date(), PLANTED_AT, 900.0, "Online transfer"
    )
    return [*payments, planted]


@dataclass
class SeedReport:
    created: list[str] = field(default_factory=list)
    found: list[str] = field(default_factory=list)
    manifest: dict[str, Any] = field(default_factory=dict)


def _id_of(obj: dict[str, Any], what: str) -> str:
    if not obj.get("_id"):
        raise NessieError(f"Nessie returned no id for {what}: {json.dumps(obj)[:200]}")
    return obj["_id"]


def _money(value: Any) -> float:
    return round(float(value), 2)


def seed(client: NessieClient, *, dry_run: bool = False) -> SeedReport:
    report = SeedReport()

    def ensure(label: str, existing: dict[str, Any] | None, create) -> str | None:
        if existing is not None:
            report.found.append(label)
            return existing["_id"]
        report.created.append(label)
        return None if dry_run else _id_of(create(), label)

    customers: dict[str, str | None] = {}
    by_name = {(c.get("first_name"), c.get("last_name")): c for c in client.get_customers()}
    for key, body in CUSTOMERS.items():
        customers[key] = ensure(f"customer {key}", by_name.get((body["first_name"], body["last_name"])), lambda b=body: client.create_customer(b))

    accounts: dict[str, str | None] = {}
    for key, (owner, body) in ACCOUNTS.items():
        owner_id = customers[owner]
        existing = {a.get("nickname"): a for a in client.get_accounts(owner_id)} if owner_id else {}
        accounts[key] = ensure(f"account {key}", existing.get(body["nickname"]), lambda o=owner_id, b=body: client.create_account(o, b))

    merchants: dict[str, str | None] = {}
    by_merchant = {m.get("name"): m for m in client.get_merchants()}
    for key, body in MERCHANTS.items():
        merchants[key] = ensure(f"merchant {key}", by_merchant.get(body["name"]), lambda b=body: client.create_merchant(b))

    purchases: dict[str, str | None] = {}
    seen_purchases: dict[str, dict[tuple, dict[str, Any]]] = {}
    for plan in purchase_plan():
        account_id = accounts[plan.account]
        if account_id and plan.account not in seen_purchases:
            seen_purchases[plan.account] = {
                (p.get("description"), p.get("purchase_date"), _money(p.get("amount", 0))): p for p in client.get_purchases(account_id)
            }
        existing = seen_purchases.get(plan.account, {}).get((plan.description, plan.day.isoformat(), _money(plan.amount)))
        body = {
            "merchant_id": merchants[plan.merchant],
            "medium": "balance",
            "purchase_date": plan.day.isoformat(),
            "amount": plan.amount,
            "status": "completed",
            "description": plan.description,
        }
        purchases[plan.key] = ensure(f"purchase {plan.key}", existing, lambda a=account_id, b=body: client.create_purchase(a, b))

    bills: dict[str, str | None] = {}
    for key, (account, body) in BILLS.items():
        account_id = accounts[account]
        existing = {(b.get("payee"), b.get("nickname")): b for b in client.get_bills(account_id)} if account_id else {}
        bills[key] = ensure(f"bill {key}", existing.get((body["payee"], body["nickname"])), lambda a=account_id, b=body: client.create_bill(a, b))

    transfers: dict[str, dict[str, Any]] = {}
    seen_transfers: dict[str, dict[tuple, dict[str, Any]]] = {}
    for plan in transfer_plan():
        payer_id, payee_id = accounts[plan.payer], accounts[plan.payee]
        if payer_id and plan.payer not in seen_transfers:
            seen_transfers[plan.payer] = {
                (t.get("description"), t.get("transaction_date"), _money(t.get("amount", 0))): t for t in client.get_transfers(payer_id)
            }
        existing = seen_transfers.get(plan.payer, {}).get((plan.description, plan.day.isoformat(), _money(plan.amount)))
        body = {
            "medium": "balance",
            "payee_id": payee_id,
            "amount": plan.amount,
            "transaction_date": plan.day.isoformat(),
            "status": "completed",
            "description": plan.description,
        }
        transfer_id = ensure(f"transfer {plan.key}", existing, lambda a=payer_id, b=body: client.create_transfer(a, b))
        transfers[plan.key] = {
            "id": transfer_id,
            "payer_id": payer_id,
            "payee_id": payee_id,
            "amount": plan.amount,
            "date": plan.day.isoformat(),
            "at": plan.at.isoformat(),
        }

    report.manifest = {
        "_note": "Written by scripts/seed_nessie.py. Synthetic demo data. Transfer payer, payee and time live here because Nessie's transfer listings omit them.",
        "base_url": client.base_url,
        "message_at": MESSAGE_AT.isoformat(),
        "customers": customers,
        "accounts": accounts,
        "merchants": merchants,
        "bills": bills,
        "purchases": purchases,
        "transfers": transfers,
    }
    return report


def write_manifest(manifest: dict[str, Any], path: Path = SEED_PATH) -> None:
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed Nessie for the SentinelAI demo (idempotent).")
    parser.add_argument("--dry-run", action="store_true", help="list what would be created; change nothing")
    parser.add_argument("--out", type=Path, default=SEED_PATH)
    args = parser.parse_args(argv)

    try:
        client = client_from_settings(args.out)
        report = seed(client, dry_run=args.dry_run)
    except NessieError as exc:
        print(f"Nessie error: {exc}", file=sys.stderr)
        return 1

    verb = "Would create" if args.dry_run else "Created"
    print(f"{verb} {len(report.created)}, already present {len(report.found)}.")
    for label in report.created:
        print(f"  + {label}")
    if not args.dry_run:
        write_manifest(report.manifest, args.out)
        print(f"IDs saved to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
