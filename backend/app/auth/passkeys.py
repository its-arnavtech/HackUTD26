"""Passkeys (WebAuthn / FIDO2), the primary sign-in (L13).

A passkey is phishing-resistant: the browser signs only for our origin, so a
lookalike scam site can't collect anything reusable. That matters for an app
whose whole job is scams. User verification (biometric or device PIN) is
required, so a passkey sign-in counts as two factors on its own.

Ceremonies (one-time challenges) are kept in memory for 5 minutes, keyed by a
random id that travels in an `HttpOnly` cookie. Each challenge can be used once.

Registration needs a signed-in session: accounts are invite-only, so a passkey
is added to an existing account, never used to create one.
"""

from __future__ import annotations

import json
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import bytes_to_base64url
from webauthn.helpers.exceptions import InvalidAuthenticationResponse, InvalidRegistrationResponse
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.auth.store import AuthStore

CEREMONY_SECONDS = 300
RP_NAME = "SentinelAI"


class PasskeyError(Exception):
    """Verification failed. The message is safe to log and show."""


@dataclass
class _Ceremony:
    kind: str  # "register" | "login"
    challenge: bytes
    user_id: str | None
    expires: float


class PasskeyService:
    def __init__(self, store: AuthStore, rp_id: str, origins: list[str]) -> None:
        self.store = store
        self.rp_id = rp_id
        self.origins = origins
        self._ceremonies: dict[str, _Ceremony] = {}
        self._lock = threading.Lock()

    def _start(self, kind: str, challenge: bytes, user_id: str | None) -> str:
        ceremony_id = secrets.token_urlsafe(24)
        now = time.monotonic()
        with self._lock:
            for key in [k for k, c in self._ceremonies.items() if c.expires < now]:
                del self._ceremonies[key]
            self._ceremonies[ceremony_id] = _Ceremony(kind, challenge, user_id, now + CEREMONY_SECONDS)
        return ceremony_id

    def _take(self, ceremony_id: str | None, kind: str) -> _Ceremony:
        with self._lock:
            ceremony = self._ceremonies.pop(ceremony_id or "", None)
        if ceremony is None or ceremony.kind != kind or ceremony.expires < time.monotonic():
            raise PasskeyError("sign-in request expired; start again")
        return ceremony

    # -- registration (signed in) ------------------------------------------------

    def registration_options(self, user_id: str, username: str, display_name: str) -> tuple[str, dict[str, Any]]:
        options = generate_registration_options(
            rp_id=self.rp_id,
            rp_name=RP_NAME,
            user_id=user_id.encode("utf-8"),
            user_name=username,
            user_display_name=display_name,
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.REQUIRED,
                user_verification=UserVerificationRequirement.REQUIRED,
            ),
            exclude_credentials=[
                PublicKeyCredentialDescriptor(id=_b64url_bytes(p.credential_id)) for p in self.store.passkeys_for(user_id)
            ],
        )
        return self._start("register", options.challenge, user_id), json.loads(options_to_json(options))

    def register(self, ceremony_id: str | None, user_id: str, credential: dict[str, Any]) -> str:
        ceremony = self._take(ceremony_id, "register")
        if ceremony.user_id != user_id:
            raise PasskeyError("sign-in request expired; start again")
        try:
            verified = verify_registration_response(
                credential=credential,
                expected_challenge=ceremony.challenge,
                expected_rp_id=self.rp_id,
                expected_origin=self.origins,
                require_user_verification=True,
            )
        except (InvalidRegistrationResponse, ValueError, KeyError, TypeError):
            raise PasskeyError("passkey could not be verified") from None
        credential_id = bytes_to_base64url(verified.credential_id)
        if self.store.passkey(credential_id) is not None:
            raise PasskeyError("this passkey is already registered")
        self.store.add_passkey(user_id, credential_id, verified.credential_public_key, verified.sign_count)
        return credential_id

    # -- sign-in --------------------------------------------------------------------

    def login_options(self) -> tuple[str, dict[str, Any]]:
        # Discoverable credentials: no username needed, so nothing to enumerate.
        options = generate_authentication_options(rp_id=self.rp_id, user_verification=UserVerificationRequirement.REQUIRED)
        return self._start("login", options.challenge, None), json.loads(options_to_json(options))

    def login(self, ceremony_id: str | None, credential: dict[str, Any]) -> str:
        """Verify an assertion and return the user id. Rejects a bad signature or a sign count that went backward."""
        ceremony = self._take(ceremony_id, "login")
        credential_id = credential.get("rawId") or credential.get("id")
        passkey = self.store.passkey(str(credential_id)) if credential_id else None
        if passkey is None:
            raise PasskeyError("passkey could not be verified")
        try:
            verified = verify_authentication_response(
                credential=credential,
                expected_challenge=ceremony.challenge,
                expected_rp_id=self.rp_id,
                expected_origin=self.origins,
                credential_public_key=passkey.public_key,
                credential_current_sign_count=passkey.sign_count,
                require_user_verification=True,
            )
        except (InvalidAuthenticationResponse, ValueError, KeyError, TypeError):
            raise PasskeyError("passkey could not be verified") from None
        self.store.update_sign_count(passkey.credential_id, verified.new_sign_count)
        return passkey.user_id


def _b64url_bytes(value: str) -> bytes:
    import base64

    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
