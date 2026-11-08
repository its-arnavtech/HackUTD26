"""Customer protection extras (L15b): official contact routes, opt-in scam memory, delete my data.

**Official contact.** `official_contact(brand)` returns only what `data/brands.json`
verified from the brand's own pages (official domains and short codes). It never
uses a number or link from the message, so the "contact them yourself" advice
can't be hijacked by the scammer.

**Personal scam memory (opt-in).** With the customer's consent, each checked
message leaves only minimized indicators: claimed brand, scam type, the link's
registered domain, and a wording fingerprint (a hash, not the text). A new
message is compared against them to say "same domain as a message you checked
on Nov 8". No message text, phone numbers or names are kept. In memory for this
server; the customer can turn it off and delete it at any time.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from app.config import DATA_DIR

BRANDS = DATA_DIR / "brands.json"


@lru_cache(maxsize=1)
def _brands() -> dict[str, dict[str, Any]]:
    data = json.loads(BRANDS.read_text(encoding="utf-8")) if BRANDS.exists() else {"brands": []}
    extra = DATA_DIR / "brands_extra.json"
    rows = list(data.get("brands", [])) + (json.loads(extra.read_text(encoding="utf-8"))["brands"] if extra.exists() else [])
    out: dict[str, dict[str, Any]] = {}
    for b in rows:
        for name in [b["name"], *b.get("aliases", [])]:
            out[name.strip().lower()] = b
    return out


def official_contact(brand: str | None) -> dict[str, Any]:
    """Verified contact routes for a brand, or generic safe advice when we don't have them."""
    b = _brands().get((brand or "").strip().lower())
    if not b:
        return {
            "brand": brand,
            "verified": False,
            "advice": "Use the company's official app, or type its website address yourself. For a bank, call the number on the back of your card.",
            "domains": [],
            "short_codes": [],
        }
    return {
        "brand": b["name"],
        "verified": True,
        "advice": f"Open the official {b['name']} app, or type the address below yourself. Never use a link or number from the message.",
        "domains": b.get("official_domains", []),
        "short_codes": b.get("official_short_codes", []),
        "source": (b.get("sources") or [{}])[0].get("url"),
    }


# ---------------------------------------------------------------------------
# Personal scam memory
# ---------------------------------------------------------------------------


@dataclass
class Indicator:
    at: datetime
    message_id: str
    brand: str | None
    category: str | None
    domain: str | None
    wording: str  # hash of the wording skeleton, not the text


@dataclass
class _Memory:
    consent: bool = False
    items: list[Indicator] = field(default_factory=list)


_lock = threading.Lock()
_memory: dict[str, _Memory] = {}


def _mem(owner: str) -> _Memory:
    return _memory.setdefault(owner, _Memory())


def set_consent(owner: str, on: bool) -> dict[str, Any]:
    with _lock:
        m = _mem(owner)
        m.consent = on
        if not on:
            m.items.clear()  # turning it off deletes what was kept
    return view(owner)


def view(owner: str) -> dict[str, Any]:
    with _lock:
        m = _mem(owner)
        return {
            "consent": m.consent,
            "items": [
                {"at": i.at.isoformat(), "brand": i.brand, "category": i.category, "domain": i.domain} for i in m.items
            ],
        }


def indicators_from_privacy(payload: dict[str, Any]) -> dict[str, Any]:
    """Minimized indicators from what Nemotron received (already redacted)."""
    from app.waves import skeleton

    urls = payload.get("urls") or []
    text = str(payload.get("text_redacted") or "")
    return {
        "brand": (payload.get("sender") or {}).get("claimed_brand"),
        "category": (payload.get("classifier") or {}).get("category"),
        "domain": urls[0].get("registered_domain") if urls else None,
        "wording": hashlib.sha256(skeleton(text).encode()).hexdigest()[:12],
    }


def remember(owner: str, message_id: str, ind: dict[str, Any]) -> dict[str, Any]:
    """Compare with earlier indicators, then keep this one (only with consent)."""
    with _lock:
        m = _mem(owner)
        if not m.consent:
            return {"consent": False, "matches": []}
        matches = []
        for old in m.items:
            if old.message_id == message_id:
                continue
            same = []
            if ind["domain"] and old.domain == ind["domain"]:
                same.append("the same link domain")
            if ind["wording"] == old.wording:
                same.append("the same wording")
            if ind["brand"] and old.brand == ind["brand"] and ind["category"] and old.category == ind["category"] and ind["category"] != "legit":
                same.append(f"the same {ind['brand']} lure")
            if same:
                matches.append({"at": old.at.isoformat(), "brand": old.brand, "why": " and ".join(same)})
        if not any(i.message_id == message_id for i in m.items):
            m.items.append(Indicator(datetime.now(timezone.utc), message_id, ind["brand"], ind["category"], ind["domain"], ind["wording"]))
        return {"consent": True, "matches": matches}


def forget(owner: str) -> None:
    with _lock:
        _memory.pop(owner, None)


def clear() -> None:
    with _lock:
        _memory.clear()
