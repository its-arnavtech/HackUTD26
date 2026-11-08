"""Live demo helpers (L14, local only): sample messages, and "plug into any system".

**Sample messages.** `sample_messages()` draws from Arnav's 320 synthetic linked
scenarios (`data/generated/linked_scenarios.jsonl`, template set A only, so the
held-out test split is never touched). Each comes back as a message you could
receive (synthetic name and the scenario's own fake link put back in) plus its
ground truth, so the demo can show the right answer next to the agent's.

**Plug into any system.** A bank or carrier keeps account activity in its own
format. Arnav's adapters (`app/adapters/mapping_loader.py`, one YAML file per
system under `data/generated/schema_mappings/`) map any of them into one
canonical event. `preview()` takes records in a system's native format, maps
each one, and computes the fraud signals the agent reasons about from the
canonical events, whatever system they came from:

- a payee or merchant never seen before
- an amount far above the customer's usual
- a channel never used before
- a SIM change, eSIM transfer, port-out or new device before a payment
- activity within three hours after the suspicious text

Adding a new system is a new YAML file, not a code change. All data here is
synthetic.
"""

from __future__ import annotations

import json
import random
import re
import statistics
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any

from app.adapters.mapping_loader import apply_mapping, available_mappings, load_mapping
from app.config import DATA_DIR

SCENARIOS_PATH = DATA_DIR / "generated" / "linked_scenarios.jsonl"
DEMO_NAME = "Linda"
TAG = re.compile(r"<(URL|PERSON|PHONE|PHONE_HASH|EMAIL|ACCOUNT|ADDRESS)(?:_[A-Za-z0-9]+)?>")

LABELS = {
    "nessie": "Capital One Nessie (bank)",
    "paysim": "PaySim (mobile money)",
    "sparkov": "Sparkov (credit cards)",
    "ibm_aml": "IBM AML (bank transfers)",
    "generic_card_processor": "Card processor auth feed",
    "telecom_billing": "Carrier billing and SIM events",
}

# ---------------------------------------------------------------------------
# Sample messages
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _scenarios() -> tuple[dict[str, Any], ...]:
    if not SCENARIOS_PATH.exists():
        return ()
    rows = [json.loads(line) for line in SCENARIOS_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    # Template set A only: set B is the held-out test wording.
    return tuple(r for r in rows if (r.get("message") or {}).get("template_set") != "B")


def _restore_text(message: dict[str, Any]) -> str:
    """Put synthetic values back where the scenario has redaction tags, so it reads like a real text."""
    urls = message.get("urls") or []
    source_url = message.get("source_url")

    def fill(match: re.Match[str]) -> str:
        kind, token = match.group(1), match.group(0)
        if kind == "URL":
            index = int(re.sub(r"\D", "", token) or 1) - 1
            if index == 0 and source_url:
                return str(source_url)
            if 0 <= index < len(urls) and urls[index].get("registered_domain"):
                return f"https://{urls[index]['registered_domain']}/"
            return str(source_url or "https://example.test/")
        if kind == "PERSON":
            return DEMO_NAME
        if kind in ("PHONE", "PHONE_HASH"):
            return "+1 555 010 0199"
        if kind == "EMAIL":
            return "linda@example.test"
        return token

    return TAG.sub(fill, str(message.get("text_redacted", "")))


def _restore_sender(sender: dict[str, Any], scenario_id: str) -> str:
    value = str(sender.get("value") or "")
    if sender.get("type") == "short_code" and value.isdigit():
        return value
    if sender.get("type") == "alphanumeric" and value and not value.startswith("<"):
        return value
    digits = "".join(ch for ch in scenario_id if ch.isdigit()).rjust(4, "0")[-4:]
    return f"+1555010{digits}"


def categories() -> list[str]:
    return sorted({r["taxonomy_id"] for r in _scenarios()})


def sample_messages(category: str | None = None, n: int = 1, seed: int | None = None) -> list[dict[str, Any]]:
    pool = [r for r in _scenarios() if not category or r["taxonomy_id"] == category]
    if not pool:
        return []
    rng = random.Random(seed)
    picks = rng.sample(pool, min(max(1, n), len(pool)))
    out = []
    for r in picks:
        message, truth = r.get("message") or {}, r.get("ground_truth") or {}
        out.append({
            "scenario_id": r["scenario_id"],
            "category": r["taxonomy_id"],
            "text": _restore_text(message),
            "sender": _restore_sender(message.get("sender") or {}, r["scenario_id"]),
            "claimed_brand": (message.get("sender") or {}).get("claimed_brand"),
            "truth": {
                # The message: a scam unless its category is `legit`.
                "is_scam": r["taxonomy_id"] != "legit",
                # The account: whether money was really lost after the click in this scenario.
                "account_fraud": bool(truth.get("is_fraud")),
                "fraud_type": truth.get("fraud_type"),
                "explanation": truth.get("explanation"),
                "signals": truth.get("signals") or [],
            },
        })
    return out


# ---------------------------------------------------------------------------
# Plug into any system
# ---------------------------------------------------------------------------

MESSAGE_AT = "2026-11-08T15:00:00Z"

# One short synthetic story per system, in that system's own column names: a few normal
# events before the text, then what happened after it.
SAMPLES: dict[str, list[dict[str, Any]]] = {
    "nessie": [
        {"_object": "purchase", "purchase_date": "2026-11-01T10:12:00Z", "account_id": "acc_chk", "merchant_id": "m_heb", "description": "H-E-B", "amount": 62.10, "category": "grocery"},
        {"_object": "purchase", "purchase_date": "2026-11-03T18:40:00Z", "account_id": "acc_chk", "merchant_id": "m_shell", "description": "Shell", "amount": 41.75, "category": "fuel"},
        {"_object": "bill", "payment_date": "2026-11-05T09:00:00Z", "account_id": "acc_chk", "payee": "T-Mobile", "payment_amount": 85.00, "status": "completed"},
        {"_object": "purchase", "purchase_date": "2026-11-08T15:17:00Z", "account_id": "acc_chk", "merchant_id": "m_unknown", "description": "Unknown Payee", "amount": 900.00, "category": "money_transfer"},
    ],
    "paysim": [
        {"step": 7400, "type": "PAYMENT", "amount": 54.20, "nameOrig": "C1093", "nameDest": "M5521", "newbalanceOrig": 2210.30, "isFraud": 0},
        {"step": 7430, "type": "PAYMENT", "amount": 38.00, "nameOrig": "C1093", "nameDest": "M7710", "newbalanceOrig": 2172.30, "isFraud": 0},
        {"step": 7455, "type": "PAYMENT", "amount": 61.15, "nameOrig": "C1093", "nameDest": "M5521", "newbalanceOrig": 2111.15, "isFraud": 0},
        {"step": 7480, "type": "TRANSFER", "amount": 1850.00, "nameOrig": "C1093", "nameDest": "C9988", "newbalanceOrig": 261.15, "isFraud": 1},
    ],
    "sparkov": [
        {"trans_date_trans_time": "2026-11-02 12:05:00", "cc_num": "4111000011112222", "merchant": "fraud_Kroger", "category": "grocery_pos", "amt": 48.33, "is_fraud": 0},
        {"trans_date_trans_time": "2026-11-04 19:22:00", "cc_num": "4111000011112222", "merchant": "fraud_Netflix", "category": "entertainment", "amt": 15.49, "is_fraud": 0},
        {"trans_date_trans_time": "2026-11-06 08:10:00", "cc_num": "4111000011112222", "merchant": "fraud_Kroger", "category": "grocery_pos", "amt": 52.80, "is_fraud": 0},
        {"trans_date_trans_time": "2026-11-08 15:40:00", "cc_num": "4111000011112222", "merchant": "fraud_GiftCardHub", "category": "shopping_net", "amt": 750.00, "is_fraud": 1},
    ],
    "ibm_aml": [
        {"Timestamp": "2026-11-01 09:00", "Account": "8000A1", "Account.1": "8000B7", "Amount Paid": 1200.00, "Payment Currency": "US Dollar", "Payment Format": "ACH", "Is Laundering": 0},
        {"Timestamp": "2026-11-04 09:00", "Account": "8000A1", "Account.1": "8000B7", "Amount Paid": 1150.00, "Payment Format": "ACH", "Is Laundering": 0},
        {"Timestamp": "2026-11-06 14:30", "Account": "8000A1", "Account.1": "8000C2", "Amount Paid": 300.00, "Payment Format": "Cheque", "Is Laundering": 0},
        {"Timestamp": "2026-11-08 16:05", "Account": "8000A1", "Account.1": "80F9Z4", "Amount Paid": 9500.00, "Payment Format": "Wire", "Is Laundering": 1},
    ],
    "generic_card_processor": [
        {"txn_type": "purchase", "auth_ts": "2026-11-02T11:00:00Z", "card_token": "tok_77a", "merchant_id": "mch_coffee", "merchant_name": "Corner Coffee", "amount_cents": 650, "entry_mode": "CP", "mcc": "5814"},
        {"txn_type": "purchase", "auth_ts": "2026-11-05T17:30:00Z", "card_token": "tok_77a", "merchant_id": "mch_target", "merchant_name": "Target", "amount_cents": 8420, "entry_mode": "CP", "mcc": "5310"},
        {"txn_type": "purchase", "auth_ts": "2026-11-07T12:15:00Z", "card_token": "tok_77a", "merchant_id": "mch_coffee", "merchant_name": "Corner Coffee", "amount_cents": 700, "entry_mode": "CP", "mcc": "5814"},
        {"txn_type": "purchase", "auth_ts": "2026-11-08T15:25:00Z", "card_token": "tok_77a", "merchant_id": "mch_xr91", "merchant_name": "XR91 Digital Goods", "amount_cents": 49900, "entry_mode": "ECOM", "mcc": "5816"},
    ],
    "telecom_billing": [
        {"event_code": "AUTOPAY", "event_time": "2026-11-01T06:00:00Z", "msisdn": "+15550100123", "biller": "T-Mobile", "charge": 85.00, "bill_status": "paid"},
        {"event_code": "MRC", "event_time": "2026-11-01T06:00:00Z", "msisdn": "+15550100123", "biller": "T-Mobile", "charge": 85.00, "bill_status": "closed"},
        {"event_code": "SIM_CHANGE", "event_time": "2026-11-08T15:05:00Z", "msisdn": "+15550100123", "dealer": "Unknown dealer", "sim_iccid": "8901260000000000999"},
        {"event_code": "PORT_OUT", "event_time": "2026-11-08T15:20:00Z", "msisdn": "+15550100123", "dealer": "Unknown dealer"},
    ],
}

MONEY_OUT = {"purchase", "transfer_out", "withdrawal", "bill_payment", "bill"}
TAKEOVER = {"sim_change", "esim_transfer", "port_out", "port_out_request", "device_add", "new_device"}


def _is_takeover(event_type: Any) -> bool:
    t = str(event_type or "")
    return t in TAKEOVER or any(word in t for word in ("sim", "port_out", "device"))


def sources() -> list[dict[str, Any]]:
    out = []
    for name in available_mappings():
        m = load_mapping(name)
        out.append({
            "name": name,
            "label": LABELS.get(name, name),
            "description": " ".join(m.description.split()),
            "fields": [
                {"canonical": path, "from": list(spec.source), "transform": spec.transform, "notes": spec.notes}
                for path, spec in m.fields.items()
            ],
            "sample": SAMPLES.get(name, []),
        })
    return out


def _when(event: dict[str, Any]) -> datetime | None:
    ts = event.get("timestamp")
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def signals(events: list[dict[str, Any]], message_at: str = MESSAGE_AT) -> list[dict[str, str]]:
    """Fraud signals from canonical events, the same whatever system they came from."""
    try:
        sent = datetime.fromisoformat(message_at.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        sent = datetime.fromisoformat(MESSAGE_AT.replace("Z", "+00:00"))
    before = [e for e in events if (_when(e) or sent) < sent]
    after = [e for e in events if (_when(e) or sent) >= sent]
    usual = [e["amount_minor"] for e in before if isinstance(e.get("amount_minor"), int) and e["amount_minor"] > 0]
    median = statistics.median(usual) if usual else None
    known_payees = {e.get("counterparty_id") for e in before if e.get("counterparty_id")}
    known_channels = {e.get("channel") for e in before if e.get("channel")}
    found: list[dict[str, str]] = []

    for e in after:
        index = events.index(e)
        when = _when(e)
        label = e.get("counterparty_name") or e.get("counterparty_id") or e.get("event_type") or "event"
        minutes = int((when - sent).total_seconds() // 60) if when else None
        if _is_takeover(e.get("event_type")):
            found.append({"event_index": index, "signal": "account_takeover_step", "detail": f"{e['event_type'].replace('_', ' ')} {minutes} min after the text"})
            continue
        if e.get("event_type") not in MONEY_OUT:
            continue
        if e.get("counterparty_id") and e["counterparty_id"] not in known_payees:
            found.append({"event_index": index, "signal": "new_payee", "detail": f"first payment ever to {label}"})
        amount = e.get("amount_minor")
        if median and isinstance(amount, int) and amount >= 5 * median:
            found.append({"event_index": index, "signal": "amount_far_above_usual", "detail": f"${amount / 100:,.2f} is {amount / median:.0f}x the usual ${median / 100:,.2f}"})
        if e.get("channel") and known_channels and e["channel"] not in known_channels:
            found.append({"event_index": index, "signal": "new_channel", "detail": f"first {e['channel']} payment"})
        if minutes is not None and 0 <= minutes <= 180:
            found.append({"event_index": index, "signal": "soon_after_text", "detail": f"{minutes} min after the text"})
        if any(_is_takeover(t.get("event_type")) and (_when(t) or sent) <= (when or sent) for t in after):
            found.append({"event_index": index, "signal": "takeover_before_payment", "detail": "SIM or device change came before this payment"})
    return found


def preview(source: str, records: list[dict[str, Any]] | None = None, message_at: str = MESSAGE_AT) -> dict[str, Any]:
    if source not in available_mappings():
        raise KeyError(source)
    mapping = load_mapping(source)
    raw = records if records is not None else SAMPLES.get(source, [])
    events = [apply_mapping(r, mapping) for r in raw[:200]]
    return {
        "source": source,
        "label": LABELS.get(source, source),
        "message_at": message_at,
        "records": raw[:200],
        "canonical": events,
        "signals": signals(events, message_at),
    }


def _now() -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=0)).strftime("%Y-%m-%dT%H:%M:%SZ")
