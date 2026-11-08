"""Use any payment system as the agent's account-activity source (L15 feature 2).

By default the agent's `nessie_recent_activity` tool reads Capital One Nessie.
`set_active(source, records)` swaps in another system instead: its records (in
that system's own format) are mapped by its YAML file into canonical events
(`app/adapters/mapping_loader.py`), and the same fraud signals the "Plug into
any system" page shows (`app.connect.signals`) become the tool's flagged items.
The result keeps the existing `NessieRecentActivityResult` shape, so the agent,
guardrails, UI and "Was this you?" all work unchanged.

- Events are shifted so the sample's "text arrived" time lines up with the
  message being checked.
- Check mode sees activity up to the text; recovery mode sees activity after it,
  the same window rules as the Nessie tool.
- Flagged items carry references (`evt_3`) only. The payee name goes only into
  the customer-side "Was this you?" details, as the contract requires.
- Payment systems only. Carrier SIM and port-out events have no place in the
  bank result's item types, so `telecom_billing` stays preview-only until there
  is a carrier-events tool.

In memory, for this server process; `clear()` returns to Nessie.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from app import connect
from app.adapters.mapping_loader import apply_mapping, load_mapping
from app.contracts import AgentInput, AgentMode, FlaggedItem, NessieRecentActivityArgs, NessieRecentActivityResult, WasThisYouItem

PAYMENT_SOURCES = ("nessie", "paysim", "sparkov", "ibm_aml", "generic_card_processor")

_TYPE = {
    "purchase": "purchase",
    "transfer_out": "transfer",
    "transfer": "transfer",
    "withdrawal": "withdrawal",
    "bill_payment": "bill",
    "bill": "bill",
    "deposit": "deposit",
    "transfer_in": "deposit",
}

_lock = threading.Lock()
_active: dict[str, Any] | None = None


class UnsupportedSource(ValueError):
    pass


def set_active(source: str, records: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if source not in PAYMENT_SOURCES:
        raise UnsupportedSource(f"{source} can be previewed but not used as the agent's bank activity yet")
    load_mapping(source)  # raises if the YAML file is missing
    raw = records if records is not None else connect.SAMPLES.get(source, [])
    global _active
    with _lock:
        _active = {"source": source, "records": list(raw)[:500], "message_at": connect.MESSAGE_AT}
    return status()


def clear() -> None:
    global _active
    with _lock:
        _active = None


def status() -> dict[str, Any]:
    with _lock:
        if _active is None:
            return {"source": "nessie", "label": connect.LABELS["nessie"], "live_nessie": True, "records": 0}
        return {
            "source": _active["source"],
            "label": connect.LABELS.get(_active["source"], _active["source"]),
            "live_nessie": False,
            "records": len(_active["records"]),
        }


def is_active() -> bool:
    with _lock:
        return _active is not None


def _shifted_events(agent_input: AgentInput) -> tuple[list[dict[str, Any]], datetime]:
    with _lock:
        assert _active is not None
        source, records, sample_at = _active["source"], list(_active["records"]), _active["message_at"]
    mapping = load_mapping(source)
    events = [apply_mapping(r, mapping) for r in records]
    sample_sent = datetime.fromisoformat(sample_at.replace("Z", "+00:00"))
    received = agent_input.received_at if agent_input.received_at.tzinfo else agent_input.received_at.replace(tzinfo=timezone.utc)
    delta = received.astimezone(timezone.utc) - sample_sent
    for e in events:
        when = connect._when(e)
        if when is not None:
            e["timestamp"] = (when + delta).strftime("%Y-%m-%dT%H:%M:%SZ")
    return events, received.astimezone(timezone.utc)


def recent_activity(args: NessieRecentActivityArgs, agent_input: AgentInput) -> NessieRecentActivityResult:
    """The `nessie_recent_activity` result, computed from the active source's canonical events."""
    from app.tools import nessie_tools  # the same reference store "Was this you?" reads

    events, sent = _shifted_events(agent_input)
    signals = connect.signals(events, sent.strftime("%Y-%m-%dT%H:%M:%SZ"))
    by_event: dict[int, list[str]] = {}
    for s in signals:
        by_event.setdefault(int(s["event_index"]), []).append(s["detail"])

    if agent_input.mode == AgentMode.recovery or args.since is not None:
        start = args.since or sent
        start = start if start.tzinfo else start.replace(tzinfo=timezone.utc)
        in_window = [i for i, e in enumerate(events) if (connect._when(e) or sent) >= start]
    else:
        start = sent - timedelta(days=args.days or 7)
        in_window = [i for i, e in enumerate(events) if start <= (connect._when(e) or sent) <= sent]

    flagged: list[FlaggedItem] = []
    for i in in_window:
        e = events[i]
        kind = _TYPE.get(str(e.get("event_type")))
        if i not in by_event or kind is None:
            continue
        ref = f"evt_{i}"
        amount = round((e.get("amount_minor") or 0) / 100, 2)
        when = connect._when(e)
        minutes = int((when - sent).total_seconds() // 60) if when and when >= sent else None
        reasons = [d for d in by_event[i] if "min after the text" not in d]
        flagged.append(FlaggedItem(
            ref=ref,
            type=kind,  # type: ignore[arg-type]
            amount=amount,
            new_payee=any(d.startswith("first payment ever") for d in by_event[i]),
            minutes_after_message=minutes,
            reason="; ".join(_neutral(r) for r in reasons) or "activity right after the text",
        ))
        nessie_tools._REF_DETAILS[ref] = WasThisYouItem(
            ref=ref,
            type=kind,  # type: ignore[arg-type]
            amount=amount,
            payee=str(e.get("counterparty_name") or e.get("counterparty_id") or "a payee"),
            at=when or sent,
        )
    accounts = {e.get("account_id") for e in events if e.get("account_id")}
    return NessieRecentActivityResult(accounts_checked=len(accounts) or 1, items_checked=len(in_window), flagged=flagged)


def _neutral(detail: str) -> str:
    """Signals for the model, without payee names (the contract allows references only)."""
    if detail.startswith("first payment ever to"):
        return "new payee"
    return detail
