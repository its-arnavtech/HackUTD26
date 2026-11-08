"""A12 SQLite persistence: hashes, controlled metadata and observation times only.

No message text, normalized wording, sender, raw URL, raw message ID or example
is persisted. Session-only message links are kept separately in memory.
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ALGORITHM = "a12-simhash-v4"
DEFAULT_FILENAME = "campaigns-v4.sqlite3"


def utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Campaign timestamps must include a timezone")
    return value.astimezone(timezone.utc)


def stamp(value: datetime) -> str:
    return utc(value).isoformat(timespec="microseconds")


@dataclass(frozen=True)
class Fingerprint:
    event_hash: str
    domain_pattern: str
    template_hash: str
    wording_simhash: str
    claimed_brand: str
    category: str
    observed_at: str

    def __post_init__(self):
        for field in (self.event_hash, self.template_hash):
            if not re.fullmatch(r"[a-f0-9]{64}", field):
                raise ValueError("Invalid campaign hash")
        if not re.fullmatch(r"[a-f0-9]{32}", self.wording_simhash):
            raise ValueError("Invalid wording fingerprint")
        if stamp(datetime.fromisoformat(self.observed_at)) != self.observed_at:
            raise ValueError("Campaign timestamps must be canonical UTC")


@dataclass(frozen=True)
class Member:
    fingerprint: Fingerprint
    campaign_id: str


class CampaignStore:
    def __init__(self, path: str | Path = ":memory:"):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._links: dict[str, str] = {}
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS fingerprints (
                event_hash TEXT PRIMARY KEY, campaign_id TEXT NOT NULL,
                domain_pattern TEXT NOT NULL, template_hash TEXT NOT NULL,
                wording_simhash TEXT NOT NULL, claimed_brand TEXT NOT NULL,
                category TEXT NOT NULL, observed_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS campaign_time ON fingerprints(campaign_id, observed_at);
            CREATE TABLE IF NOT EXISTS calibration (singleton INTEGER PRIMARY KEY CHECK(singleton=1), report TEXT NOT NULL);
        """)

    def close(self) -> None:
        with self._lock:
            self._db.close()
            self._links.clear()

    @property
    def calibration(self) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT report FROM calibration WHERE singleton=1").fetchone()
            return json.loads(row[0]) if row else None

    @property
    def threshold(self) -> float:
        report = self.calibration
        if report is None:
            raise ValueError("Calibrate on the validation split before recording campaigns")
        if report["algorithm"] != ALGORITHM:
            raise ValueError("Campaign algorithm changed; rebuild a fresh store")
        return report["threshold"]

    @property
    def semantic_weight(self) -> float:
        _ = self.threshold  # Validate presence/version first.
        return self.calibration["semantic_weight"]

    def set_calibration(self, report: dict) -> None:
        keys = {"algorithm", "split_digest", "threshold", "semantic_weight", "training_fingerprints", "validation_rows",
                "validation_positive", "true_positive", "false_positive", "false_negative", "precision", "recall", "f1"}
        if set(report) != keys or report["algorithm"] != ALGORITHM or not re.fullmatch(r"[a-f0-9]{64}", report["split_digest"]):
            raise ValueError("Invalid campaign calibration metadata")
        numbers = [value for key, value in report.items() if key not in {"algorithm", "split_digest"}]
        if any(not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 for value in numbers):
            raise ValueError("Calibration must contain aggregate numbers only")
        if not 0 < report["threshold"] <= 1 or not 0 <= report["semantic_weight"] <= 1:
            raise ValueError("Invalid campaign threshold")
        with self._lock, self._db:
            previous = self.calibration
            if previous != report and self._db.execute("SELECT 1 FROM fingerprints LIMIT 1").fetchone():
                raise ValueError("Calibration changed; rebuild into a fresh campaign database")
            self._db.execute("INSERT OR REPLACE INTO calibration VALUES (1, ?)", (json.dumps(report, sort_keys=True),))

    def members(self, *, as_of: datetime | None = None, exclude: str | None = None) -> list[Member]:
        conditions, values = [], []
        if as_of is not None:
            conditions.append("observed_at <= ?"); values.append(stamp(as_of))
        if exclude is not None:
            conditions.append("event_hash <> ?"); values.append(exclude)
        query = "SELECT * FROM fingerprints" + (" WHERE " + " AND ".join(conditions) if conditions else "") + " ORDER BY observed_at, event_hash"
        with self._lock:
            rows = self._db.execute(query, values).fetchall()
        return [Member(Fingerprint(**{key: row[key] for key in Fingerprint.__dataclass_fields__}), row["campaign_id"]) for row in rows]

    def count(self) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM fingerprints").fetchone()[0]

    def add(self, fingerprints: Iterable[Fingerprint], score: Callable[[Fingerprint, Fingerprint], float],
            *, link: tuple[str, str] | None = None) -> int:
        # One transaction: duplicate/conflicting input cannot leave a partial seed.
        items = sorted(fingerprints, key=lambda fp: (fp.observed_at, fp.event_hash))
        with self._lock, self._db:
            threshold = self.threshold
            existing = self.members()
            by_id = {member.fingerprint.event_hash: member for member in existing}
            added = 0
            for fp in items:
                if fp.event_hash in by_id:
                    if fp != by_id[fp.event_hash].fingerprint:
                        raise ValueError("Observation ID already has a different fingerprint")
                    continue
                candidates = [(score(fp, member.fingerprint), member) for member in existing
                              if member.fingerprint.category == fp.category]
                candidates.sort(key=lambda pair: (-pair[0], pair[1].fingerprint.event_hash))
                matched = candidates[0] if candidates and candidates[0][0] >= threshold else None
                campaign_id = matched[1].campaign_id if matched else "camp_" + fp.event_hash[:16]
                self._db.execute("INSERT INTO fingerprints VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                 (fp.event_hash, campaign_id, fp.domain_pattern, fp.template_hash, fp.wording_simhash,
                                  fp.claimed_brand, fp.category, fp.observed_at))
                member = Member(fp, campaign_id)
                existing.append(member); by_id[fp.event_hash] = member; added += 1
            if link is not None:
                self._links[link[0]] = link[1]
            return added

    def links(self, event_hashes: Iterable[str]) -> list[str]:
        with self._lock:
            return [self._links[key] for key in event_hashes if key in self._links]
