"""The auth services for one app, built from settings when `AUTH_ENABLED=true` (L13)."""

from __future__ import annotations

from fastapi import Response

from app.auth.deps import ACCESS_COOKIE, CSRF_COOKIE, REFRESH_COOKIE, Principal, RateLimiter
from app.auth.passkeys import PasskeyService
from app.auth.store import AuthStore, User
from app.auth.tokens import TokenError, TokenService, new_csrf_token, new_family_id, new_refresh_token
from app.config import Settings
from app.crypto import KeyRing, keyed_hash

MFA_COOKIE = "sa_mfa"
CEREMONY_COOKIE = "sa_wa"
AUTH_PATH = "/api/auth"


class AuthContext:
    def __init__(self, settings: Settings, store: AuthStore | None = None) -> None:
        assert settings.JWT_PRIVATE_KEY is not None and settings.DATA_ENCRYPTION_KEYS is not None
        self.settings = settings
        self.store = store or AuthStore(settings.auth_db_path)
        self.keyring = KeyRing.parse(settings.DATA_ENCRYPTION_KEYS.get_secret_value())
        self.tokens = TokenService(
            settings.JWT_PRIVATE_KEY.get_secret_value(),
            settings.JWT_KEY_ID,
            settings.JWT_ISSUER,
            settings.JWT_AUDIENCE,
            settings.ACCESS_TOKEN_MINUTES,
        )
        self.passkeys = PasskeyService(self.store, settings.WEBAUTHN_RP_ID, settings.webauthn_origins)
        self.limiter = RateLimiter(settings.AUTH_RATE_LIMIT_PER_MINUTE)
        self._ip_key = self.keyring.derive("audit-ip")

    def close(self) -> None:
        self.store.close()

    def ip_hash(self, host: str) -> str:
        return keyed_hash(self._ip_key, host)

    def principal_from_cookie(self, token: str | None) -> Principal | None:
        if not token:
            return None
        try:
            claims = self.tokens.verify_access(token)
        except TokenError:
            return None
        if self.store.family_revoked(claims.family_id):
            return None
        user = self.store.user_by_id(claims.user_id)
        if user is None:
            return None
        return Principal(user_id=user.id, role=user.role, username=user.username, family_id=claims.family_id)

    # -- cookies ----------------------------------------------------------------

    def _cookie(self, response: Response, name: str, value: str, max_age: int, path: str, http_only: bool = True) -> None:
        response.set_cookie(
            name, value, max_age=max_age, path=path, httponly=http_only, secure=self.settings.COOKIE_SECURE, samesite="strict"
        )

    def set_csrf(self, response: Response) -> str:
        token = new_csrf_token()
        self._cookie(response, CSRF_COOKIE, token, max_age=12 * 3600, path="/", http_only=False)
        return token

    def start_session(self, response: Response, user: User, family_id: str | None = None) -> None:
        """Issue an access token and a fresh single-use refresh token. A new sign-in gets a new family and CSRF token."""
        new_signin = family_id is None
        family_id = family_id or new_family_id()
        refresh = new_refresh_token()
        self.store.add_refresh(refresh, user.id, family_id, self.settings.REFRESH_TOKEN_HOURS)
        access = self.tokens.issue_access(user.id, user.role, family_id)
        self._cookie(response, ACCESS_COOKIE, access, self.settings.ACCESS_TOKEN_MINUTES * 60, "/api")
        self._cookie(response, REFRESH_COOKIE, refresh, self.settings.REFRESH_TOKEN_HOURS * 3600, AUTH_PATH)
        if new_signin:
            self.set_csrf(response)  # rotate on sign-in (no session fixation through the CSRF token)
            response.delete_cookie(MFA_COOKIE, path=AUTH_PATH)

    def end_session(self, response: Response) -> None:
        for name, path in ((ACCESS_COOKIE, "/api"), (REFRESH_COOKIE, AUTH_PATH), (MFA_COOKIE, AUTH_PATH), (CEREMONY_COOKIE, AUTH_PATH)):
            response.delete_cookie(name, path=path, secure=self.settings.COOKIE_SECURE, samesite="strict", httponly=True)

    def set_mfa_ticket(self, response: Response, user: User) -> None:
        self._cookie(response, MFA_COOKIE, self.tokens.issue_mfa_ticket(user.id), 300, AUTH_PATH)

    def set_ceremony(self, response: Response, ceremony_id: str) -> None:
        self._cookie(response, CEREMONY_COOKIE, ceremony_id, 300, AUTH_PATH)
