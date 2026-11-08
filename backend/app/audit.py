"""Security audit log: append-only, content-free, tamper-evident (L13).

Every security event (sign-in, failed sign-in, lockout, MFA failure, refresh
reuse, sign-out, denied request, demo reset) gets one row. A row records who,
what, when and the outcome. It never records message text, passwords, codes,
tokens or a raw IP address: the IP is stored as an HMAC (`crypto.keyed_hash`),
so repeated attempts from one address can be linked without keeping the address.

**Tamper evidence.** Each row stores the SHA-256 of the previous row's hash plus
its own fields. Editing, deleting or reordering any row breaks every hash after
it, and `verify_chain()` reports the first broken row. There is no update or
delete method: the log is append-only from the app's point of view.

This is not the L6 privacy log (what each model and tool received per message).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,
    event     TEXT NOT NULL,
    actor     TEXT NOT NULL,
    target    TEXT NOT NULL,
    outcome   TEXT NOT NULL,
    ip_hash   TEXT NOT NULL,
    details   TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    hash      TEXT NOT NULL
);
"""

GENESIS = "0" * 64
OUTCOMES = frozenset({"success", "failure", "denied"})
# Details must stay content-free: short scalars only, and never these keys.
_MAX_DETAIL_LEN = 64
_FORBIDDEN_DETAIL_KEYS = frozenset({"text", "message", "password", "code", "token", "secret", "ip", "body"})


class AuditError(ValueError):
    """An event that would put content into the audit log."""


@dataclass(frozen=True)
class AuditEvent:
    id: int
    ts: str
    event: str
    actor: str
    target: str
    outcome: str
    ip_hash: str
    details: dict[str, Any]


def _row_hash(prev_hash: str, ts: str, event: str, actor: str, target: str, outcome: str, ip_hash: str, details: str) -> str:
    payload = json.dumps([prev_hash, ts, event, actor, target, outcome, ip_hash, details], separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _clean_details(details: dict[str, Any] | None) -> str:
    clean: dict[str, Any] = {}
    for key, value in (details or {}).items():
        if key.lower() in _FORBIDDEN_DETAIL_KEYS:
            raise AuditError(f"audit details may not include {key!r}")
        if not isinstance(value, (str, int, bool)) or value is None:
            raise AuditError(f"audit detail {key!r} must be a short string, int or bool")
        if isinstance(value, str) and len(value) > _MAX_DETAIL_LEN:
            raise AuditError(f"audit detail {key!r} is longer than {_MAX_DETAIL_LEN} characters")
        clean[key] = value
    return json.dumps(clean, sort_keys=True, separators=(",", ":"))


class AuditLog:
    """Writes to the `audit_events` table of the connection it is given."""

    def __init__(self, db: sqlite3.Connection, lock: threading.RLock | None = None) -> None:
        self._db = db
        self._lock = lock or threading.RLock()
        self._db.executescript(SCHEMA)

    def record(
        self,
        event: str,
        *,
        actor: str = "anonymous",
        target: str = "",
        outcome: str = "success",
        ip_hash: str = "",
        details: dict[str, Any] | None = None,
    ) -> int:
        if outcome not in OUTCOMES:
            raise AuditError(f"outcome must be one of {sorted(OUTCOMES)}")
        details_json = _clean_details(details)
        ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        with self._lock:
            row = self._db.execute("SELECT hash FROM audit_events ORDER BY id DESC LIMIT 1").fetchone()
            prev = row[0] if row else GENESIS
            digest = _row_hash(prev, ts, event, actor, target, outcome, ip_hash, details_json)
            cur = self._db.execute(
                "INSERT INTO audit_events (ts, event, actor, target, outcome, ip_hash, details, prev_hash, hash)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ts, event, actor, target, outcome, ip_hash, details_json, prev, digest),
            )
            return int(cur.lastrowid or 0)

    def recent(self, limit: int = 100) -> list[AuditEvent]:
        with self._lock:
            rows = self._db.execute(
                "SELECT id, ts, event, actor, target, outcome, ip_hash, details FROM audit_events ORDER BY id DESC LIMIT ?",
                (max(1, min(limit, 500)),),
            ).fetchall()
        return [AuditEvent(r[0], r[1], r[2], r[3], r[4], r[5], r[6], json.loads(r[7])) for r in rows]

    def verify_chain(self) -> tuple[bool, int | None]:
        """`(True, None)` if intact, else `(False, id of the first row that doesn't match)`."""
        with self._lock:
            rows = self._db.execute(
                "SELECT id, ts, event, actor, target, outcome, ip_hash, details, prev_hash, hash FROM audit_events ORDER BY id"
            ).fetchall()
        prev = GENESIS
        for r in rows:
            if r[8] != prev or _row_hash(prev, r[1], r[2], r[3], r[4], r[5], r[6], r[7]) != r[9]:
                return False, int(r[0])
            prev = r[9]
        return True, None
