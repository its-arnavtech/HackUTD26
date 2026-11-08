"""Scam-wave early warning (L15 feature 4).

Scams arrive in waves: one template sent to thousands within hours. Catching
the wave early lets a carrier or bank warn customers before the text reaches
them.

Every message SentinelAI sees is reduced to a **template fingerprint**:
lowercase, digits become 0, links and redaction tags become `url` or a tag
word, punctuation is dropped, and the claimed brand and the link's domain
pattern are added. The text itself is not kept; only the fingerprint, counts,
and one already-redacted example.

A fingerprint becomes a **wave** when it is seen 5 or more times in the last 60
minutes, or at least 3 times as often as in the hour before.

`simulate()` replays one of Arnav's seeded campaigns (set A wording, 5 to 15
variants each) through the fingerprinting only, with no model calls, so the
demo can show a wave forming in seconds. Warnings are simulated broadcasts.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import DATA_DIR

CAMPAIGNS = DATA_DIR / "generated" / "campaigns.jsonl"
WINDOW = timedelta(minutes=60)
MIN_COUNT = 5
GROWTH = 3.0
MAX_EVENTS = 20_000

_TAG = re.compile(r"<(URL|PERSON|PHONE_HASH|PHONE|EMAIL|ACCOUNT|ADDRESS)[^>]*>")
_LINK = re.compile(r"https?://\S+|\b[\w-]+\.(?:com|net|org|info|top|xyz|test|io|co)\b\S*", re.I)


def skeleton(text_redacted: str) -> str:
    """The wording with numbers, links and redaction tags removed (stable across amounts and links)."""
    text = _TAG.sub(" ", text_redacted)
    text = _LINK.sub(" ", text.lower())
    text = re.sub(r"\d+", " ", text)
    text = re.sub(r"[^a-z ]+", " ", text)
    return " ".join(text.split())


def fingerprint(text_redacted: str, brand: str | None = None, category: str | None = None) -> str:
    """Which wave a message belongs to.

    Real campaigns rotate their wording and their look-alike domains (even
    swapping in Cyrillic letters), so a wave is defined the way a fraud desk
    describes one: the brand being impersonated plus the scam type ("fake
    Walmart billing texts"). Without a brand, the wording skeleton is used.
    """
    if brand and category:
        raw = f"brand|{brand.strip().lower()}|{category}"
    else:
        raw = f"text|{skeleton(text_redacted)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


@dataclass
class _Seen:
    at: datetime
    key: str


@dataclass
class _Info:
    brand: str | None
    category: str | None
    example: str
    first_seen: datetime
    domain: str | None = None
    warned_at: datetime | None = None


@dataclass
class WaveDetector:
    events: deque = field(default_factory=lambda: deque(maxlen=MAX_EVENTS))
    info: dict[str, _Info] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def observe(self, text_redacted: str, *, brand: str | None = None, domain: str | None = None,
                category: str | None = None, at: datetime | None = None) -> str:
        at = at or datetime.now(timezone.utc)
        if category == "legit":
            return ""  # real messages never count toward a wave
        key = fingerprint(text_redacted, brand, category)
        with self.lock:
            self.events.append(_Seen(at, key))
            if key not in self.info:
                self.info[key] = _Info(brand=brand, category=category, example=text_redacted[:240], first_seen=at, domain=domain)
            elif category and not self.info[key].category:
                self.info[key].category = category
        return key

    def waves(self, now: datetime | None = None) -> list[dict[str, Any]]:
        now = now or datetime.now(timezone.utc)
        with self.lock:
            recent: dict[str, int] = {}
            previous: dict[str, int] = {}
            for e in self.events:
                if now - WINDOW <= e.at <= now:
                    recent[e.key] = recent.get(e.key, 0) + 1
                elif now - 2 * WINDOW <= e.at < now - WINDOW:
                    previous[e.key] = previous.get(e.key, 0) + 1
            out = []
            for key, count in recent.items():
                before = previous.get(key, 0)
                growing = before > 0 and count >= GROWTH * before and count >= 3
                if count < MIN_COUNT and not growing:
                    continue
                info = self.info[key]
                out.append({
                    "id": key,
                    "brand": info.brand,
                    "category": info.category,
                    "count_last_hour": count,
                    "count_previous_hour": before,
                    "trend": "new" if before == 0 else ("growing" if count > before else "steady"),
                    "first_seen": info.first_seen.isoformat(),
                    "example": info.example,
                    "domain_pattern": info.domain,
                    "warned": info.warned_at is not None,
                })
            return sorted(out, key=lambda w: -w["count_last_hour"])

    def warn(self, wave_id: str) -> dict[str, Any]:
        with self.lock:
            info = self.info.get(wave_id)
            if info is None:
                raise KeyError(wave_id)
            info.warned_at = datetime.now(timezone.utc)
            brand = info.brand or "a company"
        text = warning_text(brand, info.category)
        return {"id": wave_id, "text": text, "audience": "customers of this carrier or bank (simulated)", "sent": False}

    def clear(self) -> None:
        with self.lock:
            self.events.clear()
            self.info.clear()


_WHAT = {
    "billing_scam": "overdue-bill",
    "bank_impersonation": "account-locked",
    "delivery_scam": "missed-delivery",
    "account_security": "account-security",
    "toll_government": "unpaid-toll",
    "prize_refund": "prize or refund",
    "job_offer": "job-offer",
    "conversation_lure": "wrong-number",
}


def warning_text(brand: str, category: str | None) -> str:
    """A broadcast with no link and no number, so it can't itself be used as a lure."""
    kind = _WHAT.get(category or "", "suspicious")
    return (
        f"Heads up: a fake {brand} {kind} text is going around right now. {brand} won't ask you to pay, "
        "log in or confirm details through a text link. If you get one, don't tap it."
    )


detector = WaveDetector()


def campaigns() -> list[dict[str, Any]]:
    if not CAMPAIGNS.exists():
        return []
    rows = [json.loads(line) for line in CAMPAIGNS.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [r for r in rows if r.get("template_set") != "B"]


def simulate(campaign_id: str | None = None, *, spacing_seconds: int = 90, d: WaveDetector | None = None) -> dict[str, Any]:
    """Replay one seeded campaign's variants into the detector, spread over the last minutes."""
    d = d or detector
    rows = campaigns()
    ids = sorted({r["campaign_id"] for r in rows})
    if not ids:
        raise KeyError("no campaigns")
    if campaign_id is None:
        # The biggest campaign makes the clearest demo.
        sizes = {cid: sum(1 for r in rows if r["campaign_id"] == cid) for cid in ids}
        campaign_id = max(ids, key=lambda cid: (sizes[cid], cid))
    variants = [r for r in rows if r["campaign_id"] == campaign_id]
    if not variants:
        raise KeyError(campaign_id)
    now = datetime.now(timezone.utc)
    keys = set()
    for i, v in enumerate(variants):
        keys.add(d.observe(
            v["text_redacted"],
            brand=(v.get("sender") or {}).get("claimed_brand"),
            domain=v.get("domain"),
            category=v.get("taxonomy_id"),
            at=now - timedelta(seconds=spacing_seconds * (len(variants) - 1 - i)),
        ))
    return {"campaign_id": campaign_id, "messages": len(variants), "fingerprints": len(keys)}
