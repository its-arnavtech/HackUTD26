"""Who is calling and what they may do: deny-by-default authorization (L13).

Every `/api` route goes through `authorize`, a router-level dependency:

1. **Deny by default.** The route must have an entry in `ROUTE_PERMISSIONS`. A
   route without one is refused for everyone, even with auth off, so a new route
   can't ship open by accident (a test checks every mounted route has a rule).
2. **Auth off** (`AUTH_ENABLED=false`, the default): the caller is the fixed demo
   customer `DEMO_PRINCIPAL`, so the demo behaves exactly as before.
3. **CSRF.** Every POST needs an `X-CSRF-Token` header equal to the `sa_csrf`
   cookie (double-submit). Cookies are also `SameSite=Strict`.
4. **Authentication.** The `sa_at` cookie must hold a valid ES256 access token
   whose sign-in hasn't been revoked, for a user that still exists. The role
   comes from the database, not the token, so a role change applies at once.
5. **Authorization (RBAC).** The role must hold the route's permission.
   Ownership of a specific message (ABAC) is checked in the route itself, and an
   unowned id answers 404, the same as an unknown one.

Every refusal is written to the audit log.
"""

from __future__ import annotations

import hmac
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Annotated, TYPE_CHECKING

from fastapi import Depends, Request

from app.errors import ForbiddenError, RateLimitedError, UnauthorizedError

if TYPE_CHECKING:
    from app.auth.context import AuthContext

PUBLIC = "public"  # anyone, no session (auth routes run their own checks)
SESSION = "session"  # any signed-in user
WEBHOOK = "webhook"  # an outside service calling us (no session or CSRF); the route checks its signature

# The demo customer. With auth off every request is this user; with auth on,
# `scripts.create_user --demo` creates the account with this id, so the seeded
# demo inbox belongs to it.
DEMO_CUSTOMER_ID = "00000000-0000-4000-8000-000000000001"

CUSTOMER_PERMISSIONS = frozenset(
    {"messages:read", "messages:write", "actions:write", "privacy:read", "campaigns:read", "metrics:read"}
)
ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "customer": CUSTOMER_PERMISSIONS,
    "admin": CUSTOMER_PERMISSIONS | {"demo:reset", "audit:read"},
}

ROUTE_PERMISSIONS: dict[tuple[str, str], str] = {
    ("GET", "/api/health"): PUBLIC,
    ("GET", "/api/inbox"): "messages:read",
    ("POST", "/api/messages"): "messages:write",
    ("GET", "/api/messages/{message_id}/result"): "messages:read",
    ("GET", "/api/messages/{message_id}/agent"): "messages:read",
    ("POST", "/api/messages/{message_id}/clicked"): "messages:write",
    ("POST", "/api/transactions/{ref}/confirm"): "messages:write",
    ("POST", "/api/actions"): "actions:write",
    ("GET", "/api/privacy/{message_id}"): "privacy:read",
    ("GET", "/api/campaigns"): "campaigns:read",
    ("GET", "/api/metrics"): "metrics:read",
    ("GET", "/api/demo/samples"): "messages:read",
    ("GET", "/api/connect/sources"): "metrics:read",
    ("GET", "/api/connect/active"): "metrics:read",
    ("POST", "/api/connect/active"): "messages:write",
    ("DELETE", "/api/connect/active"): "messages:write",
    ("GET", "/api/agent-metrics"): "metrics:read",
    ("GET", "/api/trusted-contact"): "messages:read",
    ("PUT", "/api/trusted-contact"): "messages:write",
    ("DELETE", "/api/trusted-contact"): "messages:write",
    ("GET", "/api/waves"): "campaigns:read",
    ("POST", "/api/waves/simulate"): "messages:write",
    ("POST", "/api/waves/{wave_id}/warn"): "messages:write",
    ("POST", "/api/connect/{source}/preview"): "metrics:read",
    ("POST", "/api/demo/reset"): "demo:reset",
    ("GET", "/api/audit"): "audit:read",
    ("GET", "/api/auth/csrf"): PUBLIC,
    ("POST", "/api/auth/login"): PUBLIC,
    ("POST", "/api/auth/login/totp"): PUBLIC,
    ("POST", "/api/auth/passkey/login/options"): PUBLIC,
    ("POST", "/api/auth/passkey/login/verify"): PUBLIC,
    ("POST", "/api/auth/refresh"): PUBLIC,
    ("POST", "/api/auth/logout"): PUBLIC,
    ("POST", "/api/sms/inbound"): WEBHOOK,
    ("GET", "/api/whatsapp/webhook"): WEBHOOK,
    ("POST", "/api/whatsapp/webhook"): WEBHOOK,
    ("GET", "/api/auth/me"): SESSION,
    ("POST", "/api/auth/passkey/register/options"): SESSION,
    ("POST", "/api/auth/passkey/register/verify"): SESSION,
}

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
ACCESS_COOKIE = "sa_at"
REFRESH_COOKIE = "sa_rt"
CSRF_COOKIE = "sa_csrf"
CSRF_HEADER = "x-csrf-token"


@dataclass(frozen=True)
class Principal:
    user_id: str
    role: str
    username: str
    family_id: str | None = None

    def can(self, permission: str) -> bool:
        return permission in ROLE_PERMISSIONS.get(self.role, frozenset())


DEMO_PRINCIPAL = Principal(user_id=DEMO_CUSTOMER_ID, role="customer", username="demo")


class RateLimiter:
    """Sliding window per key (an HMAC of the client IP), in memory. Single process is enough here."""

    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str, now: float | None = None) -> bool:
        t = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= t - 60:
                hits.popleft()
            if len(hits) >= self.per_minute:
                return False
            hits.append(t)
            return True


def _route_key(request: Request) -> tuple[str, str] | None:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return (request.method, path) if path else None


def client_ip_hash(ctx: "AuthContext", request: Request) -> str:
    host = request.client.host if request.client else "unknown"
    return ctx.ip_hash(host)


def authorize(request: Request) -> None:
    key = _route_key(request)
    permission = ROUTE_PERMISSIONS.get(key) if key else None
    ctx: AuthContext | None = request.app.state.auth
    if permission is None:
        if ctx is not None:
            ctx.store.audit.record("access.no_rule", target=key[1] if key else "", outcome="denied",
                                   ip_hash=client_ip_hash(ctx, request))
        raise ForbiddenError("This route has no access rule")

    if ctx is None:  # auth off
        request.state.principal = DEMO_PRINCIPAL
        return
    if permission == WEBHOOK:
        request.state.principal = None
        return

    ip_hash = client_ip_hash(ctx, request)
    if request.url.path.startswith("/api/auth/") and not ctx.limiter.check(ip_hash):
        ctx.store.audit.record("auth.rate_limited", target=request.url.path, outcome="denied", ip_hash=ip_hash)
        raise RateLimitedError("Too many attempts. Wait a minute and try again.")

    if request.method in UNSAFE_METHODS:
        cookie = request.cookies.get(CSRF_COOKIE, "")
        header = request.headers.get(CSRF_HEADER, "")
        if not cookie or not header or not hmac.compare_digest(cookie, header):
            ctx.store.audit.record("access.csrf_failed", target=request.url.path, outcome="denied", ip_hash=ip_hash)
            raise ForbiddenError("Security check failed. Reload the page and try again.", code="csrf_failed")

    principal = ctx.principal_from_cookie(request.cookies.get(ACCESS_COOKIE))
    request.state.principal = principal
    if permission == PUBLIC:
        return
    if principal is None:
        raise UnauthorizedError("Sign in to continue")
    if permission != SESSION and not principal.can(permission):
        ctx.store.audit.record("access.forbidden", actor=principal.user_id, target=request.url.path,
                               outcome="denied", ip_hash=ip_hash, details={"permission": permission})
        raise ForbiddenError("Your account can't do this")


def current_principal(request: Request) -> Principal:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise UnauthorizedError("Sign in to continue")
    return principal


PrincipalDep = Annotated[Principal, Depends(current_principal)]
