"""Nessie tools (A11, POC_MVP.md 7.6, DATA_SPEC.md 3.2).

Return summaries with references (`txn_3`), never payee names, account numbers
or merchant names. Only these tools touch account data. `resolve_ref` turns a
reference into customer-facing details for the app; its output never goes to a
model.

The demo customer is Linda from `data/nessie_seed.json` (A2). Check mode only
looks at activity up to the message's `received_at`; recovery mode looks from
`since` onward, which is how scenario 2 finds the planted $900 that scenario 1 can't.

The planted $900 is a purchase at a merchant named "Unknown Payee" (live Nessie
transfers can't name a receiving account; see the A2 seed). It is flagged as the
first purchase at that merchant and far above the 30-day purchase median, and its
exact time comes from the seed manifest, so `minutes_after_message` is set.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any, Literal, Optional

from app.agent.registry import ToolSpec
from app.contracts import (
    AgentInput,
    AgentMode,
    FlaggedItem,
    NessieBillStatusArgs,
    NessieBillStatusResult,
    NessieRecentActivityArgs,
    NessieRecentActivityResult,
    ToolName,
    WasThisYouItem,
)
from app.integrations.nessie import NessieClient, NessieError, client_from_settings, load_seed

MEDIAN_WINDOW_DAYS = 30
MEDIAN_FACTOR = 3.0
MIN_HISTORY_FOR_MEDIAN = 2
MIN_PURCHASE_HISTORY_FOR_MEDIAN = 5  # purchases are many and small; don't judge from the first few days
# Purchases mix $5 coffees with $70 grocery runs, so the median is low and ordinary
# groceries reach 4-5x it. "Far above" for a purchase means 10x (the planted $900 is ~45x).
PURCHASE_MEDIAN_FACTOR = 10.0
DEMO_CUSTOMER = "linda"

ItemType = Literal["transfer", "purchase"]


@dataclass(frozen=True)
class Activity:
    ref: str
    type: ItemType
    amount: float
    when: datetime
    exact_time: bool
    account_id: str
    counterparty_id: Optional[str]  # payee account for transfers, merchant for purchases


# ref -> customer-facing details, filled while scanning and read by resolve_ref.
_REF_DETAILS: dict[str, WasThisYouItem] = {}


def _parse_day(value: Any, tz: tzinfo) -> Optional[datetime]:
    try:
        return datetime.combine(date.fromisoformat(str(value)[:10]), time(0, 0), tzinfo=tz)
    except ValueError:
        return None


def _parse_at(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _demo_customer(seed: Optional[dict[str, Any]]) -> str:
    customer_id = (seed or {}).get("customers", {}).get(DEMO_CUSTOMER)
    if not customer_id:
        raise NessieError("data/nessie_seed.json has no demo customer; run python -m scripts.seed_nessie")
    return customer_id


def _context(client: NessieClient | None, seed: dict[str, Any] | None) -> tuple[NessieClient, dict[str, Any]]:
    seed = seed if seed is not None else load_seed()
    return (client or client_from_settings()), (seed or {})


def _seed_tz(seed: dict[str, Any]) -> tzinfo:
    """The demo's timezone. Refs depend on how dated and timed items interleave, so it must not vary per call."""
    message_at = _parse_at(seed.get("message_at"))
    return (message_at.tzinfo if message_at and message_at.tzinfo else None) or datetime.now().astimezone().tzinfo


def _scan(client: NessieClient, seed: dict[str, Any], tz: tzinfo) -> tuple[list[dict[str, Any]], list[Activity]]:
    """All of the demo customer's purchases and outgoing transfers, oldest first, with stable refs."""
    accounts = client.get_accounts(_demo_customer(seed))
    rows: list[tuple[datetime, str, Activity, dict[str, Any]]] = []
    for account in accounts:
        account_id = account["_id"]
        for p in client.get_purchases(account_id):
            at = _parse_at(p.get("at"))  # exact time from the seed manifest (the planted purchase), else None
            when = at or _parse_day(p.get("purchase_date"), tz)
            if when is None:
                continue
            item = Activity("", "purchase", float(p.get("amount", 0)), when, at is not None, account_id, p.get("merchant_id"))
            rows.append((when, p["_id"], item, p))
        for t in client.get_transfers(account_id):
            at = _parse_at(t.get("at"))
            when = at or _parse_day(t.get("transaction_date"), tz)
            if when is None:
                continue
            item = Activity("", "transfer", float(t.get("amount", 0)), when, at is not None, account_id, t.get("payee_id"))
            rows.append((when, t["_id"], item, t))
    rows.sort(key=lambda row: (row[0], row[1]))
    activity = [
        Activity(f"txn_{i}", a.type, a.amount, a.when, a.exact_time, a.account_id, a.counterparty_id)
        for i, (_, _, a, _) in enumerate(rows, start=1)
    ]
    return accounts, activity


def _counterparty_names(client: NessieClient, activity: list[Activity]) -> dict[str, str]:
    """App-side labels for payee accounts and merchants. Never returned to the agent."""
    names: dict[str, str] = {}
    for customer in client.get_customers():
        label = " ".join(p for p in (customer.get("first_name"), customer.get("last_name")) if p)
        for account in client.get_accounts(customer["_id"]):
            names[account["_id"]] = label or "another account"
    for merchant_id in {a.counterparty_id for a in activity if a.type == "purchase" and a.counterparty_id}:
        try:
            names[merchant_id] = client.get_merchant(merchant_id).get("name") or "a merchant"
        except NessieError:
            names[merchant_id] = "a merchant"
    return names


def _remember(client: NessieClient, activity: list[Activity], refs: set[str]) -> None:
    if not refs:
        return
    names = _counterparty_names(client, activity)
    for a in activity:
        if a.ref in refs:
            _REF_DETAILS[a.ref] = WasThisYouItem(
                ref=a.ref,
                type=a.type,
                amount=a.amount,
                payee=names.get(a.counterparty_id or "", "an unknown account" if a.type == "transfer" else "a merchant"),
                at=a.when,
            )


def _ratio_text(ratio: float) -> str:
    return f"{round(ratio, 1):g}x"


def _flag(item: Activity, history: list[Activity], own_accounts: set[str], message_at: datetime) -> Optional[FlaggedItem]:
    earlier = [h for h in history if h.when < item.when]
    reasons: list[str] = []
    new_payee = False

    if item.type == "transfer":
        known_payees = {h.counterparty_id for h in earlier if h.type == "transfer"}
        if item.counterparty_id and item.counterparty_id not in own_accounts and item.counterparty_id not in known_payees:
            new_payee = True
            reasons.append("new payee")
        recent = [h.amount for h in earlier if h.type == "transfer" and h.when >= item.when - timedelta(days=MEDIAN_WINDOW_DAYS)]
        if len(recent) >= MIN_HISTORY_FOR_MEDIAN:
            median = statistics.median(recent)
            if median > 0 and item.amount >= MEDIAN_FACTOR * median:
                reasons.append(f"{_ratio_text(item.amount / median)} the 30-day median")
    else:
        if item.counterparty_id and item.counterparty_id not in {h.counterparty_id for h in earlier if h.type == "purchase"}:
            reasons.append("first purchase at this merchant")
        recent = [h.amount for h in earlier if h.type == "purchase" and h.when >= item.when - timedelta(days=MEDIAN_WINDOW_DAYS)]
        if len(recent) >= MIN_PURCHASE_HISTORY_FOR_MEDIAN:
            median = statistics.median(recent)
            if median > 0 and item.amount >= PURCHASE_MEDIAN_FACTOR * median:
                reasons.append(f"{_ratio_text(item.amount / median)} the 30-day median")

    if not reasons:
        return None
    minutes = None
    if item.exact_time and item.when >= message_at:
        minutes = int((item.when - message_at).total_seconds() // 60)
    return FlaggedItem(
        ref=item.ref,
        type=item.type,
        amount=item.amount,
        new_payee=new_payee,
        minutes_after_message=minutes,
        reason=", ".join(reasons),
    )


def nessie_recent_activity(
    args: NessieRecentActivityArgs,
    agent_input: AgentInput,
    *,
    client: NessieClient | None = None,
    seed: dict[str, Any] | None = None,
) -> NessieRecentActivityResult:
    """Counts plus flagged items: new payee, transfer above the 30-day median, first-time merchant."""
    from app import activity_source  # L15: another payment system can stand in for Nessie

    if client is None and seed is None and activity_source.is_active():
        return activity_source.recent_activity(args, agent_input)
    client, seed = _context(client, seed)
    tz = _seed_tz(seed)
    message_at = agent_input.received_at if agent_input.received_at.tzinfo else agent_input.received_at.replace(tzinfo=tz)
    accounts, activity = _scan(client, seed, tz)

    end = message_at if agent_input.mode == AgentMode.check else None
    start = args.since if args.since is not None else message_at - timedelta(days=args.days or 0)
    if start.tzinfo is None:
        start = start.replace(tzinfo=tz)
    if not args.since:
        # A whole-day item dated inside the window counts, whatever its hidden time.
        start = start.replace(hour=0, minute=0, second=0, microsecond=0)
    in_window = [a for a in activity if a.when >= start and (end is None or a.when <= end)]

    own_accounts = {a["_id"] for a in accounts}
    flagged = [f for f in (_flag(a, activity, own_accounts, message_at) for a in in_window) if f]
    _remember(client, activity, {f.ref for f in flagged})
    return NessieRecentActivityResult(accounts_checked=len(accounts), items_checked=len(in_window), flagged=flagged)


def _same_payee(a: str, b: str) -> bool:
    def key(s: str) -> str:
        return "".join(ch for ch in s.lower() if ch.isalnum())

    return key(a) == key(b)


def nessie_bill_status(
    args: NessieBillStatusArgs,
    agent_input: AgentInput,
    *,
    client: NessieClient | None = None,
    seed: dict[str, Any] | None = None,
) -> NessieBillStatusResult:
    """Last status, last payment date and amount due now for a payee."""
    client, seed = _context(client, seed)
    bills = [
        bill
        for account in client.get_accounts(_demo_customer(seed))
        for bill in client.get_bills(account["_id"])
        if _same_payee(str(bill.get("payee", "")), args.payee)
    ]
    if not bills:
        return NessieBillStatusResult(found=False)

    latest = max(bills, key=lambda b: str(b.get("payment_date") or b.get("creation_date") or ""))
    status = str(latest.get("status") or "") or None
    paid_on = latest.get("payment_date")
    due_now = float(latest.get("payment_amount") or 0) if status == "pending" else 0.0
    return NessieBillStatusResult(
        found=True,
        last_status=status,
        last_payment_date=date.fromisoformat(paid_on[:10]) if paid_on else None,
        amount_due_now=due_now,
        recurring=bool(latest.get("recurring_date")) or status == "recurring",
    )


def resolve_ref(ref: str, *, client: NessieClient | None = None, seed: dict[str, Any] | None = None) -> WasThisYouItem:
    """App-side details for a reference, shown only to the customer."""
    if ref not in _REF_DETAILS:
        client, seed = _context(client, seed)
        _, activity = _scan(client, seed, _seed_tz(seed))
        _remember(client, activity, {ref})
    if ref not in _REF_DETAILS:
        raise KeyError(f"unknown reference {ref!r}")
    return _REF_DETAILS[ref]


# TODO(L5): call app.agent.registry.register(...) for both specs once L5's registry merges.
NESSIE_RECENT_ACTIVITY_SPEC = ToolSpec(
    name=ToolName.nessie_recent_activity,
    description="Check the customer's linked bank accounts for unusual activity in a time window: new payees, transfers far above the 30-day median, first purchases at a merchant. Returns counts and references, never names or account numbers.",
    args_model=NessieRecentActivityArgs,
    result_model=NessieRecentActivityResult,
    fn=nessie_recent_activity,
)

NESSIE_BILL_STATUS_SPEC = ToolSpec(
    name=ToolName.nessie_bill_status,
    description="Look up the customer's bill for a payee: last status, last payment date, amount due now and whether it recurs.",
    args_model=NessieBillStatusArgs,
    result_model=NessieBillStatusResult,
    fn=nessie_bill_status,
)
