"""Access tokens (JWT, ES256) and refresh tokens (opaque) (L13).

**Access token:** a JWT signed with ES256 (ECDSA P-256). Asymmetric, so a server
that only verifies never needs the signing key. Claims: `iss`, `aud`, `sub`
(the user's random UUID, nothing personal), `role`, `iat`, `exp` (10 minutes by
default), `jti` and `fam` (the sign-in it belongs to, so revoking that sign-in
also stops its access tokens). The header carries `kid` for key rotation.
Verification pins `algorithms=["ES256"]` and the key id, which blocks `alg: none`
and the HS256-with-the-public-key confusion attack, and requires every claim.

**MFA ticket:** same signer, separate audience (`<aud>:mfa`) and a 5-minute
life. It proves the password step passed and can't be used as an access token.

**Refresh token:** 256 random bits, not a JWT. Only its SHA-256 is stored, it is
single-use, and reuse revokes the whole sign-in (`AuthStore.consume_refresh`).

Both tokens travel only in `HttpOnly` cookies, never in `localStorage`.
"""

from __future__ import annotations

import base64
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

ALGORITHM = "ES256"
MFA_MINUTES = 5


class TokenError(Exception):
    """Any invalid, expired or forged token. The message is safe to log."""


@dataclass(frozen=True)
class AccessClaims:
    user_id: str
    role: str
    family_id: str
    jti: str


def generate_private_key_b64() -> str:
    """A new P-256 private key as base64(PEM), one line for `.env`."""
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    return base64.b64encode(pem).decode("ascii")


def load_private_key(b64_pem: str) -> ec.EllipticCurvePrivateKey:
    try:
        key = serialization.load_pem_private_key(base64.b64decode(b64_pem), password=None)
    except Exception:  # noqa: BLE001 - never echo the value
        raise TokenError("JWT_PRIVATE_KEY is not a base64-encoded PEM private key") from None
    if not isinstance(key, ec.EllipticCurvePrivateKey) or key.curve.name != "secp256r1":
        raise TokenError("JWT_PRIVATE_KEY must be an EC P-256 key (ES256)")
    return key


class TokenService:
    def __init__(self, private_key_b64: str, key_id: str, issuer: str, audience: str, access_minutes: int = 10) -> None:
        self._private = load_private_key(private_key_b64)
        self._public = self._private.public_key()
        self.key_id = key_id
        self.issuer = issuer
        self.audience = audience
        self.access_minutes = access_minutes

    def _sign(self, claims: dict[str, Any]) -> str:
        return jwt.encode(claims, self._private, algorithm=ALGORITHM, headers={"kid": self.key_id})

    def _verify(self, token: str, audience: str, required: list[str]) -> dict[str, Any]:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError:
            raise TokenError("token is malformed") from None
        if header.get("alg") != ALGORITHM or header.get("kid") != self.key_id:
            raise TokenError("token uses an unexpected algorithm or key")
        try:
            return jwt.decode(
                token,
                self._public,
                algorithms=[ALGORITHM],
                audience=audience,
                issuer=self.issuer,
                options={"require": required},
                leeway=5,
            )
        except jwt.ExpiredSignatureError:
            raise TokenError("token expired") from None
        except jwt.PyJWTError:
            raise TokenError("token is invalid") from None

    # -- access ---------------------------------------------------------------

    def issue_access(self, user_id: str, role: str, family_id: str, now: datetime | None = None) -> str:
        now = now or datetime.now(timezone.utc)
        return self._sign(
            {
                "iss": self.issuer,
                "aud": self.audience,
                "sub": user_id,
                "role": role,
                "fam": family_id,
                "iat": now,
                "exp": now + timedelta(minutes=self.access_minutes),
                "jti": uuid.uuid4().hex,
            }
        )

    def verify_access(self, token: str) -> AccessClaims:
        claims = self._verify(token, self.audience, ["iss", "aud", "sub", "role", "fam", "iat", "exp", "jti"])
        return AccessClaims(user_id=claims["sub"], role=claims["role"], family_id=claims["fam"], jti=claims["jti"])

    # -- MFA ticket -----------------------------------------------------------

    def issue_mfa_ticket(self, user_id: str, now: datetime | None = None) -> str:
        now = now or datetime.now(timezone.utc)
        return self._sign(
            {
                "iss": self.issuer,
                "aud": f"{self.audience}:mfa",
                "sub": user_id,
                "iat": now,
                "exp": now + timedelta(minutes=MFA_MINUTES),
                "jti": uuid.uuid4().hex,
            }
        )

    def verify_mfa_ticket(self, token: str) -> str:
        return self._verify(token, f"{self.audience}:mfa", ["iss", "aud", "sub", "iat", "exp", "jti"])["sub"]


def new_refresh_token() -> str:
    return secrets.token_urlsafe(32)


def new_family_id() -> str:
    return uuid.uuid4().hex


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)
