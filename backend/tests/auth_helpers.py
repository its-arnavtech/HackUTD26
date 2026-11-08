"""Test helpers for L13: auth-enabled apps, signing in, and a software passkey authenticator."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import struct
from dataclasses import dataclass, field

import cbor2
import pyotp
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from app.auth.deps import DEMO_CUSTOMER_ID
from app.auth.mfa import aad
from app.auth.passwords import hash_password
from app.auth.store import AuthStore
from app.auth.tokens import generate_private_key_b64
from app.crypto import KeyRing, generate_key

BASE_URL = "https://testserver"
ORIGIN = "https://testserver"
PASSWORD = "correct horse battery staple"

# Hashing with Argon2id is slow on purpose; reuse one hash across tests.
_PASSWORD_HASH = hash_password(PASSWORD)


def auth_settings(**overrides) -> dict:
    return {
        "AUTH_ENABLED": True,
        "JWT_PRIVATE_KEY": generate_private_key_b64(),
        "DATA_ENCRYPTION_KEYS": f"k1:{generate_key()}",
        "WEBAUTHN_RP_ID": "testserver",
        "WEBAUTHN_ORIGINS": ORIGIN,
        **overrides,
    }


@dataclass
class TestUser:
    id: str
    username: str
    role: str
    totp_secret: str


def add_user(store: AuthStore, keyring: KeyRing, username: str, role: str = "customer", user_id: str | None = None) -> TestUser:
    secret = pyotp.random_base32()
    user = store.create_user(username, username.title(), role, _PASSWORD_HASH, user_id=user_id)
    store.set_totp_secret(user.id, keyring.encrypt(secret, aad(user.id)))
    return TestUser(user.id, username, role, secret)


def seed_users(ctx) -> dict[str, TestUser]:
    """The demo customer (owns the seeded inbox), a second customer and an admin."""
    return {
        "demo": add_user(ctx.store, ctx.keyring, "demo", "customer", user_id=DEMO_CUSTOMER_ID),
        "other": add_user(ctx.store, ctx.keyring, "other", "customer"),
        "admin": add_user(ctx.store, ctx.keyring, "admin", "admin"),
    }


def csrf(client) -> str:
    if not client.cookies.get("sa_csrf"):
        client.get("/api/auth/csrf")
    token = client.cookies.get("sa_csrf")
    client.headers["X-CSRF-Token"] = token
    return token


def sign_in(client, ctx, user: TestUser) -> None:
    """Password plus TOTP. Clears the user's last TOTP step so tests can sign in repeatedly."""
    ctx.store._db.execute("UPDATE users SET totp_last_step = 0 WHERE id = ?", (user.id,))
    csrf(client)
    r = client.post("/api/auth/login", json={"username": user.username, "password": PASSWORD})
    assert r.status_code == 200, r.text
    r = client.post("/api/auth/login/totp", json={"code": pyotp.TOTP(user.totp_secret).now()})
    assert r.status_code == 200, r.text
    client.headers["X-CSRF-Token"] = client.cookies.get("sa_csrf")  # rotated on sign-in


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def unb64u(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


@dataclass
class SoftAuthenticator:
    """A minimal platform authenticator (ES256, 'none' attestation) for tests."""

    rp_id: str = "testserver"
    origin: str = ORIGIN
    sign_count: int = 0
    credential_id: bytes = field(default_factory=lambda: os.urandom(16))
    key: ec.EllipticCurvePrivateKey = field(default_factory=lambda: ec.generate_private_key(ec.SECP256R1()))
    user_handle: bytes = b""

    def _client_data(self, kind: str, challenge: str) -> bytes:
        return json.dumps({"type": kind, "challenge": challenge, "origin": self.origin, "crossOrigin": False}).encode()

    def _cose_key(self) -> bytes:
        numbers = self.key.public_key().public_numbers()
        return cbor2.dumps({1: 2, 3: -7, -1: 1, -2: numbers.x.to_bytes(32, "big"), -3: numbers.y.to_bytes(32, "big")})

    def register(self, options: dict) -> dict:
        self.user_handle = unb64u(options["user"]["id"])
        client_data = self._client_data("webauthn.create", options["challenge"])
        attested = b"\x00" * 16 + struct.pack(">H", len(self.credential_id)) + self.credential_id + self._cose_key()
        auth_data = hashlib.sha256(self.rp_id.encode()).digest() + bytes([0x45]) + struct.pack(">I", self.sign_count) + attested
        attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        return {
            "id": b64u(self.credential_id),
            "rawId": b64u(self.credential_id),
            "type": "public-key",
            "response": {"clientDataJSON": b64u(client_data), "attestationObject": b64u(attestation), "transports": ["internal"]},
            "clientExtensionResults": {},
        }

    def assert_(self, options: dict, sign_count: int | None = None, tamper: bool = False) -> dict:
        if sign_count is None:
            self.sign_count += 1
            sign_count = self.sign_count
        client_data = self._client_data("webauthn.get", options["challenge"])
        auth_data = hashlib.sha256(self.rp_id.encode()).digest() + bytes([0x05]) + struct.pack(">I", sign_count)
        signature = self.key.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))
        if tamper:
            signature = signature[:-1] + bytes([signature[-1] ^ 0x01])
        return {
            "id": b64u(self.credential_id),
            "rawId": b64u(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": b64u(client_data),
                "authenticatorData": b64u(auth_data),
                "signature": b64u(signature),
                "userHandle": b64u(self.user_handle),
            },
            "clientExtensionResults": {},
        }
