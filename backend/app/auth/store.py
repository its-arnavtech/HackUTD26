"""Auth store: users, passkeys, refresh tokens and the audit log in `data/auth.sqlite` (L13).

Separate from the message store on purpose: messages live in memory only
(DATA_SPEC section 5); accounts must survive a restart. What is stored:

- `users`: id (random UUID, never an email or phone number), username, display
  name, role, Argon2id password hash, TOTP secret encrypted with AES-256-GCM
  (`app.crypto`), the last TOTP time step used (so a code can't be replayed),
  failed sign-in count and lock time.
- `passkeys`: credential id, public key and sign count. Public keys are not
  secret; the private key never leaves the customer's device.
- `refresh_tokens`: only the SHA-256 of each token, its family, expiry and
  whether it was used or revoked. A stolen database can't be replayed as tokens.
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.audit import AuditLog

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id             TEXT PRIMARY KEY,
    username       TEXT NOT NULL UNIQUE,
    display_name   TEXT NOT NULL,
    role           TEXT NOT NULL CHECK (role IN ('customer', 'admin')),
    password_hash  TEXT NOT NULL,
    totp_secret    TEXT,
    totp_last_step INTEGER NOT NULL DEFAULT 0,
    failed_count   INTEGER NOT NULL DEFAULT 0,
    locked_until   TEXT,
    created_at     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS passkeys (
    credential_id TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    public_key    BLOB NOT NULL,
    sign_count    INTEGER NOT NULL,
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS refresh_tokens (
    token_hash TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    family_id  TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used       INTEGER NOT NULL DEFAULT 0,
    revoked    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS refresh_by_family ON refresh_tokens (family_id);
"""

MAX_FAILED = 5
LOCK_MINUTES = 15


def _now() -> datetime:
    return datetime.now(timezone.utc)


def token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class User:
    id: str
    username: str
    display_name: str
    role: str
    password_hash: str
    totp_secret: str | None
    totp_last_step: int
    failed_count: int
    locked_until: datetime | None

    def locked(self, now: datetime | None = None) -> bool:
        return self.locked_until is not None and self.locked_until > (now or _now())


@dataclass(frozen=True)
class Passkey:
    credential_id: str
    user_id: str
    public_key: bytes
    sign_count: int


class RefreshOutcome:
    OK = "ok"
    UNKNOWN = "unknown"
    EXPIRED = "expired"
    REUSED = "reused"  # an already-used token came back: the family is revoked


class AuthStore:
    def __init__(self, path: str | Path) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(SCHEMA)
        self.audit = AuditLog(self._db, self._lock)

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # -- users ----------------------------------------------------------------

    @staticmethod
    def _user(row: sqlite3.Row | None) -> User | None:
        if row is None:
            return None
        return User(
            id=row["id"],
            username=row["username"],
            display_name=row["display_name"],
            role=row["role"],
            password_hash=row["password_hash"],
            totp_secret=row["totp_secret"],
            totp_last_step=row["totp_last_step"],
            failed_count=row["failed_count"],
            locked_until=datetime.fromisoformat(row["locked_until"]) if row["locked_until"] else None,
        )

    def create_user(
        self,
        username: str,
        display_name: str,
        role: str,
        password_hash: str,
        totp_secret: str | None = None,
        user_id: str | None = None,
    ) -> User:
        uid = user_id or str(uuid.uuid4())
        with self._lock:
            self._db.execute(
                "INSERT INTO users (id, username, display_name, role, password_hash, totp_secret, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (uid, username, display_name, role, password_hash, totp_secret, _now().isoformat()),
            )
        user = self.user_by_id(uid)
        assert user is not None
        return user

    def user_by_id(self, user_id: str) -> User | None:
        with self._lock:
            return self._user(self._db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())

    def user_by_username(self, username: str) -> User | None:
        with self._lock:
            return self._user(self._db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone())

    def set_password_hash(self, user_id: str, password_hash: str) -> None:
        with self._lock:
            self._db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id))

    def set_totp_secret(self, user_id: str, encrypted_secret: str) -> None:
        with self._lock:
            self._db.execute("UPDATE users SET totp_secret = ?, totp_last_step = 0 WHERE id = ?", (encrypted_secret, user_id))

    def use_totp_step(self, user_id: str, step: int) -> bool:
        """Record a TOTP time step as used. False if it (or a later one) was already used: a replay."""
        with self._lock:
            cur = self._db.execute(
                "UPDATE users SET totp_last_step = ? WHERE id = ? AND totp_last_step < ?", (step, user_id, step)
            )
            return cur.rowcount == 1

    def register_failure(self, user_id: str) -> User:
        """Count a failed sign-in; lock the account for 15 minutes on the 5th."""
        with self._lock:
            self._db.execute("UPDATE users SET failed_count = failed_count + 1 WHERE id = ?", (user_id,))
            row = self._db.execute("SELECT failed_count FROM users WHERE id = ?", (user_id,)).fetchone()
            if row and row["failed_count"] >= MAX_FAILED:
                until = (_now() + timedelta(minutes=LOCK_MINUTES)).isoformat()
                self._db.execute("UPDATE users SET locked_until = ?, failed_count = 0 WHERE id = ?", (until, user_id))
        user = self.user_by_id(user_id)
        assert user is not None
        return user

    def clear_failures(self, user_id: str) -> None:
        with self._lock:
            self._db.execute("UPDATE users SET failed_count = 0, locked_until = NULL WHERE id = ?", (user_id,))

    # -- passkeys -------------------------------------------------------------

    def add_passkey(self, user_id: str, credential_id: str, public_key: bytes, sign_count: int) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO passkeys (credential_id, user_id, public_key, sign_count, created_at) VALUES (?, ?, ?, ?, ?)",
                (credential_id, user_id, public_key, sign_count, _now().isoformat()),
            )

    def passkey(self, credential_id: str) -> Passkey | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM passkeys WHERE credential_id = ?", (credential_id,)).fetchone()
        if row is None:
            return None
        return Passkey(row["credential_id"], row["user_id"], bytes(row["public_key"]), row["sign_count"])

    def passkeys_for(self, user_id: str) -> list[Passkey]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM passkeys WHERE user_id = ?", (user_id,)).fetchall()
        return [Passkey(r["credential_id"], r["user_id"], bytes(r["public_key"]), r["sign_count"]) for r in rows]

    def update_sign_count(self, credential_id: str, sign_count: int) -> None:
        with self._lock:
            self._db.execute("UPDATE passkeys SET sign_count = ? WHERE credential_id = ?", (sign_count, credential_id))

    # -- refresh tokens ---------------------------------------------------------

    def add_refresh(self, raw: str, user_id: str, family_id: str, hours: int) -> None:
        expires = (_now() + timedelta(hours=hours)).isoformat()
        with self._lock:
            self._db.execute(
                "INSERT INTO refresh_tokens (token_hash, user_id, family_id, expires_at) VALUES (?, ?, ?, ?)",
                (token_hash(raw), user_id, family_id, expires),
            )

    def consume_refresh(self, raw: str) -> tuple[str, str | None, str | None]:
        """Mark a refresh token used. Returns `(outcome, user_id, family_id)`.

        A token can be used once. If a used token comes back, someone else has a
        copy, so the whole family (every token from that sign-in) is revoked.
        """
        with self._lock:
            row = self._db.execute("SELECT * FROM refresh_tokens WHERE token_hash = ?", (token_hash(raw),)).fetchone()
            if row is None:
                return RefreshOutcome.UNKNOWN, None, None
            if row["used"] or row["revoked"]:
                self._db.execute("UPDATE refresh_tokens SET revoked = 1 WHERE family_id = ?", (row["family_id"],))
                return RefreshOutcome.REUSED, row["user_id"], row["family_id"]
            if datetime.fromisoformat(row["expires_at"]) <= _now():
                return RefreshOutcome.EXPIRED, row["user_id"], row["family_id"]
            self._db.execute("UPDATE refresh_tokens SET used = 1 WHERE token_hash = ?", (row["token_hash"],))
            return RefreshOutcome.OK, row["user_id"], row["family_id"]

    def revoke_family_of(self, raw: str) -> str | None:
        with self._lock:
            row = self._db.execute("SELECT family_id, user_id FROM refresh_tokens WHERE token_hash = ?", (token_hash(raw),)).fetchone()
            if row is None:
                return None
            self._db.execute("UPDATE refresh_tokens SET revoked = 1 WHERE family_id = ?", (row["family_id"],))
            return row["user_id"]

    def revoke_family(self, family_id: str) -> None:
        with self._lock:
            self._db.execute("UPDATE refresh_tokens SET revoked = 1 WHERE family_id = ?", (family_id,))

    def family_revoked(self, family_id: str) -> bool:
        with self._lock:
            row = self._db.execute(
                "SELECT MAX(revoked) FROM refresh_tokens WHERE family_id = ?", (family_id,)
            ).fetchone()
        return bool(row and row[0])
