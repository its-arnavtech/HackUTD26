"""Encryption at rest: AES-256-GCM with a key ring (L13).

Use this module for any secret value written to disk (today: each user's TOTP
secret in `data/auth.sqlite`). Message text never reaches disk at all (it lives
in the in-memory state store, DATA_SPEC section 5), which is stronger than
encrypting it.

- **Algorithm:** AES-256-GCM from `cryptography` (authenticated: a changed byte
  fails to decrypt instead of returning garbage). Never roll our own.
- **Nonce:** 96 random bits per encryption.
- **Associated data (AAD):** callers bind each ciphertext to where it lives, for
  example `b"totp:<user_id>"`, so a ciphertext copied onto another user's row
  fails to decrypt.
- **Key ring:** `DATA_ENCRYPTION_KEYS="k2:<base64>,k1:<base64>"`. The first key
  encrypts; every listed key can decrypt, so a new key can be added in front
  while old rows still read. Each ciphertext names its key id.

Ciphertext format: `v1.<key_id>.<base64url nonce>.<base64url ciphertext+tag>`.

Generate a key with `python -m scripts.auth_keys` (it writes `.env` and never
prints the key).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
import re
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

KEY_BYTES = 32  # AES-256
NONCE_BYTES = 12
_VERSION = "v1"
_KEY_ID = re.compile(r"^[A-Za-z0-9_-]{1,16}$")


class CryptoError(Exception):
    """Base class. Messages never include key material or plaintext."""


class KeyRingError(CryptoError):
    """`DATA_ENCRYPTION_KEYS` is missing or malformed."""


class DecryptionError(CryptoError):
    """Wrong key, unknown key id, tampered ciphertext or wrong associated data."""


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64u(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def generate_key() -> str:
    """A new random 256-bit key, base64-encoded for `.env`."""
    return base64.b64encode(os.urandom(KEY_BYTES)).decode("ascii")


@dataclass(frozen=True)
class KeyRing:
    """Ordered keys; `keys[0]` is the current (encrypting) key."""

    keys: tuple[tuple[str, bytes], ...]

    @classmethod
    def parse(cls, setting: str) -> "KeyRing":
        """Parse `"k2:<base64>,k1:<base64>"`. Raises `KeyRingError` without echoing the value."""
        entries: list[tuple[str, bytes]] = []
        seen: set[str] = set()
        for position, part in enumerate(p.strip() for p in setting.split(",") if p.strip()):
            key_id, sep, encoded = part.partition(":")
            if not sep or not _KEY_ID.match(key_id):
                raise KeyRingError(f"DATA_ENCRYPTION_KEYS entry {position + 1}: expected <key_id>:<base64 key>")
            if key_id in seen:
                raise KeyRingError(f"DATA_ENCRYPTION_KEYS: key id {key_id} appears twice")
            try:
                key = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError):
                raise KeyRingError(f"DATA_ENCRYPTION_KEYS key {key_id}: not valid base64") from None
            if len(key) != KEY_BYTES:
                raise KeyRingError(f"DATA_ENCRYPTION_KEYS key {key_id}: must be 32 bytes (AES-256)")
            seen.add(key_id)
            entries.append((key_id, key))
        if not entries:
            raise KeyRingError("DATA_ENCRYPTION_KEYS is empty; run `python -m scripts.auth_keys`")
        return cls(tuple(entries))

    @property
    def current_id(self) -> str:
        return self.keys[0][0]

    def _key(self, key_id: str) -> bytes | None:
        return next((k for kid, k in self.keys if kid == key_id), None)

    def encrypt(self, plaintext: bytes | str, aad: bytes) -> str:
        data = plaintext.encode("utf-8") if isinstance(plaintext, str) else plaintext
        key_id, key = self.keys[0]
        nonce = os.urandom(NONCE_BYTES)
        sealed = AESGCM(key).encrypt(nonce, data, aad)
        return f"{_VERSION}.{key_id}.{_b64u(nonce)}.{_b64u(sealed)}"

    def decrypt(self, token: str, aad: bytes) -> bytes:
        try:
            version, key_id, nonce_b64, sealed_b64 = token.split(".")
            nonce, sealed = _unb64u(nonce_b64), _unb64u(sealed_b64)
        except (ValueError, binascii.Error):
            raise DecryptionError("ciphertext is malformed") from None
        if version != _VERSION or len(nonce) != NONCE_BYTES:
            raise DecryptionError("ciphertext is malformed")
        key = self._key(key_id)
        if key is None:
            raise DecryptionError("ciphertext uses a key that is not in DATA_ENCRYPTION_KEYS")
        try:
            return AESGCM(key).decrypt(nonce, sealed, aad)
        except InvalidTag:
            raise DecryptionError("ciphertext failed authentication") from None

    def decrypt_text(self, token: str, aad: bytes) -> str:
        return self.decrypt(token, aad).decode("utf-8")

    def needs_reencrypt(self, token: str) -> bool:
        """True when `token` was written with an older key (re-encrypt it on next write)."""
        parts = token.split(".")
        return len(parts) != 4 or parts[1] != self.current_id

    def derive(self, purpose: str) -> bytes:
        """A separate 32-byte key for `purpose` (for example HMAC of IPs in the audit log), via HKDF."""
        return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=f"sentinelai:{purpose}".encode()).derive(
            self.keys[0][1]
        )


def keyed_hash(key: bytes, value: str, length: int = 16) -> str:
    """HMAC-SHA256 of `value`, hex, truncated. For pseudonymizing identifiers (never a plain hash)."""
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()[:length]
