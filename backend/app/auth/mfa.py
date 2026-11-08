"""TOTP second factor (RFC 6238) for the password sign-in (L13).

The shared secret is stored encrypted (`app.crypto`, AAD `totp:<user_id>`). A
code is accepted for the current 30-second step or one step either side (clock
drift), and each step can be used once (`AuthStore.use_totp_step`), so a code
seen over someone's shoulder can't be replayed.
"""

from __future__ import annotations

import time

import pyotp

ISSUER = "SentinelAI"


def new_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, username: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=ISSUER)


def matching_step(secret: str, code: str, now: float | None = None) -> int | None:
    """The time step `code` is valid for (current or one either side), else None."""
    code = code.strip().replace(" ", "")
    if not (code.isdigit() and len(code) == 6):
        return None
    totp = pyotp.TOTP(secret)
    t = time.time() if now is None else now
    step = int(t // totp.interval)
    for candidate in (step, step - 1, step + 1):
        if pyotp.utils.strings_equal(totp.at(candidate * totp.interval), code):
            return candidate
    return None


def aad(user_id: str) -> bytes:
    return f"totp:{user_id}".encode()
