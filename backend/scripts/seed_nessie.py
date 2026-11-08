"""Seed Nessie for the demo (POC_MVP.md 7.7) and save the IDs to data/nessie_seed.json.

Linda has a checking account and a credit card, about 30 days of purchases at a
few merchants, regular credit card payments, and a recurring T-Mobile bill marked
completed. The planted $900 is a **purchase at a new merchant, "Unknown Payee"**,
17 minutes after scenario 2's message: live Nessie's transfers can't name a
receiving account (checked 2026-11-07: `POST /accounts/{id}/transfers` accepts only
`transaction_date`, `status`, `amount` and `description`; every receiver field is
"extra fields not permitted"), so a transfer can't show who got the money.

Linda is the customer named "Linda Sentinel" at **802** Demo Way. An earlier seed
run left duplicate purchases on the customer at 800 Demo Way, and Nessie has no
DELETE for purchases, so that customer is abandoned, not cleaned up.

Nessie stores no time of day for purchases or transfers. The planted purchase's
exact time and the card payments' payee and time live in the manifest, and the
client fills them in (`integrations/nessie.py`).

Idempotent: every object has a natural key (name plus street number, nickname, or
description plus date plus amount), and anything already in Nessie is reused, so a
second run creates nothing.

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

# 802, not 800: the customer at 800 Demo Way holds an earlier run's duplicate purchases.
ADDRESS = {"street_number": "802", "street_name": "Demo Way", "city": "Richardson", "state": "TX", "zip": "75080"}
GEOCODE = {"lat": 32.9858, "lng": -96.7501}

CUSTOMERS: dict[str, dict[str, Any]] = {
    "linda": {"first_name": "Linda", "last_name": "Sentinel", "address": ADDRESS},
}

ACCOUNTS: dict[str, tuple[str, dict[str, Any]]] = {
    "linda_checking": ("linda", {"type": "Checking", "nickname": "Linda Everyday Checking", "rewards": 0, "balance": 4200}),
    "linda_credit": ("linda", {"type": "Credit Card", "nickname": "Linda Rewards Card", "rewards": 1200, "balance": 640}),
}

MERCHANTS: dict[str, dict[str, Any]] = {
    **{
        key: {"name": f"Sentinel Demo {name}", "category": category, "address": ADDRESS, "geocode": GEOCODE}
        for key, name, category in [
            ("grocery", "Grocery", "Grocery"),
            ("coffee", "Coffee", "Food"),
            ("fuel", "Fuel", "Gas"),
            ("pharmacy", "Pharmacy", "Health"),
            ("streaming", "Streaming", "Entertainment"),
        ]
    },
    "unknown_payee": {"name": "Unknown Payee", "category": "Money transfer", "address": ADDRESS, "geocode": GEOCODE},
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

# The only fields live Nessie accepts on a transfer (anything else is a 400).
TRANSFER_FIELDS = ("transaction_date", "status", "amount", "description")


@dataclass(frozen=True)
class PurchasePlan:
    key: str
    account: str
    merchant: str
    day: date
    amount: float
    description: str
    at: datetime | None = None  # exact time, kept in the manifest (Nessie stores only the date)


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
    """About 30 days of ordinary purchases, ending the day before the message.

    Amounts are whole dollars because Nessie drops the cents of a purchase (49.30
    reads back as 49), and a planned amount must equal the stored one to be found again.
    """
    schedule = [
        # merchant, account, every n days, first offset, amounts (cycled), description
        ("grocery", "linda_checking", 4, 1, [64, 58, 71, 49], "Groceries"),
        ("coffee", "linda_credit", 3, 0, [5, 6], "Coffee"),
        ("fuel", "linda_credit", 7, 2, [42, 39], "Fuel"),
        ("pharmacy", "linda_checking", 30, 12, [18], "Pharmacy"),
        ("streaming", "linda_credit", 30, 5, [15], "Streaming subscription"),
    ]
    plans = []
    for merchant, account, every, offset, amounts, description in schedule:
        for i, n in enumerate(range(offset, 30, every)):
            day = FIRST_DAY + timedelta(days=n)
            plans.append(PurchasePlan(f"{merchant}_{day.isoformat()}", account, merchant, day, amounts[i % len(amounts)], description))
    return plans


def planted_purchase() -> PurchasePlan:
    """The $900 that scenario 2 finds: first purchase at "Unknown Payee", far above the 30-day median."""
    return PurchasePlan("planted_purchase", "linda_checking", "unknown_payee", PLANTED_AT.date(), 900, "Online payment", PLANTED_AT)


def transfer_plan() -> list[TransferPlan]:
    """Card payments from checking to Linda's own credit card. Nessie can't record the
    payee, so the manifest keeps it (an own account is never a "new payee")."""
    noon = time(12, 0, tzinfo=CENTRAL)
    return [
        TransferPlan(f"card_payment_{d.isoformat()}", "linda_checking", "linda_credit", d, datetime.combine(d, noon), amount, "Credit card payment")
        for d, amount in [(date(2026, 10, 12), 120.0), (date(2026, 10, 24), 150.0), (date(2026, 11, 3), 180.0)]
    ]


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


def _customer_key(c: dict[str, Any]) -> tuple:
    address = c.get("address") or {}
    return (c.get("first_name"), c.get("last_name"), str(address.get("street_number", "")), address.get("street_name"))


def seed(client: NessieClient, *, dry_run: bool = False) -> SeedReport:
    """Create what's missing and return the manifest. Never deletes anything."""
    report = SeedReport()

    def ensure(label: str, existing: dict[str, Any] | None, create) -> str | None:
        if existing is not None:
            report.found.append(label)
            return existing["_id"]
        report.created.append(label)
        return None if dry_run else _id_of(create(), label)

    customers: dict[str, str | None] = {}
    by_key = {_customer_key(c): c for c in client.get_customers()}
    for key, body in CUSTOMERS.items():
        customers[key] = ensure(f"customer {key}", by_key.get(_customer_key(body)), lambda b=body: client.create_customer(b))

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
    purchase_times: dict[str, str] = {}
    seen_purchases: dict[str, dict[tuple, dict[str, Any]]] = {}
    planted = planted_purchase()
    for plan in [*purchase_plan(), planted]:
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
        if plan.at is not None and purchases[plan.key]:
            purchase_times[purchases[plan.key]] = plan.at.isoformat()

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
        body = {"transaction_date": plan.day.isoformat(), "status": "completed", "amount": plan.amount, "description": plan.description}
        assert tuple(body) == TRANSFER_FIELDS
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
        "_note": (
            "Written by scripts/seed_nessie.py. Synthetic demo data. Nessie stores no time of day and transfers can't name "
            "a payee, so purchase times, transfer payees and transfer times live here. The planted $900 is a purchase "
            "at merchant 'Unknown Payee'."
        ),
        "base_url": client.base_url,
        "message_at": MESSAGE_AT.isoformat(),
        "customers": customers,
        "accounts": accounts,
        "merchants": merchants,
        "bills": bills,
        "purchases": purchases,
        "purchase_times": purchase_times,
        "planted": {
            "type": "purchase",
            "id": purchases[planted.key],
            "account_id": accounts[planted.account],
            "merchant_id": merchants[planted.merchant],
            "amount": planted.amount,
            "at": planted.at.isoformat(),
        },
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
