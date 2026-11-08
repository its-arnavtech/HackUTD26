"""Password hashing with Argon2id (L13).

`argon2-cffi`'s defaults follow RFC 9106's recommended low-memory profile
(Argon2id, 64 MiB memory, 3 passes, 4 lanes) with a random salt per hash.
Passwords are a fallback; passkeys are the primary sign-in.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()
# Verified against when the username doesn't exist, so a wrong username and a
# wrong password take the same time (no username enumeration by timing).
_DUMMY_HASH = _hasher.hash("sentinelai-dummy-password-for-timing")

MIN_LENGTH = 12


class WeakPasswordError(ValueError):
    pass


def check_strength(password: str) -> None:
    """NIST SP 800-63B style: length over composition rules."""
    if len(password) < MIN_LENGTH:
        raise WeakPasswordError(f"password must be at least {MIN_LENGTH} characters")
    if len(password) > 256:
        raise WeakPasswordError("password must be at most 256 characters")


def hash_password(password: str) -> str:
    check_strength(password)
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """Constant-shape check: always runs one Argon2id verification."""
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)
