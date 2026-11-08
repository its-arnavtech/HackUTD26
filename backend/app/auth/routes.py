"""`/api/auth/*` and `/api/audit` (L13, DATA_SPEC section 8.3).

Mounted only when `AUTH_ENABLED=true`. Every route still goes through the
router-level `authorize` (CSRF, rate limit, access rule).

Sign-in failures always answer the same generic 401, whether the username is
unknown, the password or code is wrong, or the account is locked, so the
response never tells an attacker which usernames exist.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request, Response

from app import contracts as c
from app.auth import mfa
from app.auth.context import CEREMONY_COOKIE, MFA_COOKIE, AuthContext
from app.auth.deps import REFRESH_COOKIE, PrincipalDep, authorize, client_ip_hash
from app.auth.passkeys import PasskeyError
from app.auth.passwords import hash_password, needs_rehash, verify_password
from app.auth.store import RefreshOutcome, User
from app.auth.tokens import TokenError
from app.crypto import CryptoError
from app.errors import ErrorResponse, UnauthorizedError, error_response

GENERIC_FAILURE = "Sign-in failed. Check your details and try again, or wait 15 minutes if you tried many times."

router = APIRouter(
    prefix="/api",
    dependencies=[Depends(authorize)],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 429: {"model": ErrorResponse}},
)


def _ctx(request: Request) -> AuthContext:
    return request.app.state.auth


def _me(ctx: AuthContext, user: User) -> c.Me:
    return c.Me(
        user_id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=c.Role(user.role),
        passkeys=len(ctx.store.passkeys_for(user.id)),
    )


def _fail(ctx: AuthContext, request: Request, event: str, user: User | None, reason: str) -> UnauthorizedError:
    if user is not None:
        user = ctx.store.register_failure(user.id)
        if user.locked():
            ctx.store.audit.record("auth.locked", actor=user.id, outcome="denied", ip_hash=client_ip_hash(ctx, request))
    ctx.store.audit.record(
        event, actor=user.id if user else "anonymous", outcome="failure",
        ip_hash=client_ip_hash(ctx, request), details={"reason": reason},
    )
    return UnauthorizedError(GENERIC_FAILURE)


def _signed_in(ctx: AuthContext, request: Request, response: Response, user: User, method: str) -> c.LoginStep:
    ctx.store.clear_failures(user.id)
    ctx.start_session(response, user)
    ctx.store.audit.record("auth.signin", actor=user.id, ip_hash=client_ip_hash(ctx, request), details={"method": method})
    return c.LoginStep(signed_in=True)


@router.get("/auth/csrf")
def get_csrf(request: Request, response: Response) -> dict[str, bool]:
    """Sets the `sa_csrf` cookie the page copies into `X-CSRF-Token`. Call once before any POST."""
    if not request.cookies.get("sa_csrf"):
        _ctx(request).set_csrf(response)
    return {"ok": True}


# -- password + TOTP -------------------------------------------------------------


@router.post("/auth/login", response_model=c.LoginStep)
def post_login(body: c.PasswordLoginRequest, request: Request, response: Response) -> c.LoginStep:
    ctx = _ctx(request)
    user = ctx.store.user_by_username(body.username)
    ok = verify_password(user.password_hash if user else None, body.password)  # same cost either way
    if user is None or not ok:
        raise _fail(ctx, request, "auth.password", user, "bad_credentials")
    if user.locked():
        raise _fail(ctx, request, "auth.password", None, "locked")
    if needs_rehash(user.password_hash):
        ctx.store.set_password_hash(user.id, hash_password(body.password))
    if user.totp_secret is None:  # MFA is mandatory for password sign-in
        raise _fail(ctx, request, "auth.password", None, "mfa_not_set_up")
    ctx.set_mfa_ticket(response, user)
    ctx.store.audit.record("auth.password", actor=user.id, ip_hash=client_ip_hash(ctx, request))
    return c.LoginStep(signed_in=False, mfa_required=True)


@router.post("/auth/login/totp", response_model=c.LoginStep)
def post_login_totp(body: c.TotpRequest, request: Request, response: Response) -> c.LoginStep:
    ctx = _ctx(request)
    try:
        user_id = ctx.tokens.verify_mfa_ticket(request.cookies.get(MFA_COOKIE, ""))
    except TokenError:
        raise _fail(ctx, request, "auth.totp", None, "no_ticket") from None
    user = ctx.store.user_by_id(user_id)
    if user is None or user.totp_secret is None:
        raise _fail(ctx, request, "auth.totp", None, "no_user")
    if user.locked():
        raise _fail(ctx, request, "auth.totp", None, "locked")
    try:
        secret = ctx.keyring.decrypt_text(user.totp_secret, mfa.aad(user.id))
    except CryptoError:
        raise _fail(ctx, request, "auth.totp", None, "secret_unreadable") from None
    step = mfa.matching_step(secret, body.code)
    if step is None:
        raise _fail(ctx, request, "auth.totp", user, "bad_code")
    if not ctx.store.use_totp_step(user.id, step):
        raise _fail(ctx, request, "auth.totp", user, "code_reused")
    return _signed_in(ctx, request, response, user, "password+totp")


# -- passkeys ---------------------------------------------------------------------


@router.post("/auth/passkey/login/options")
def post_passkey_login_options(request: Request, response: Response) -> dict[str, Any]:
    ctx = _ctx(request)
    ceremony_id, options = ctx.passkeys.login_options()
    ctx.set_ceremony(response, ceremony_id)
    return options


@router.post("/auth/passkey/login/verify", response_model=c.LoginStep)
def post_passkey_login_verify(body: c.PasskeyCredential, request: Request, response: Response) -> c.LoginStep:
    ctx = _ctx(request)
    try:
        user_id = ctx.passkeys.login(request.cookies.get(CEREMONY_COOKIE), body.model_dump())
    except PasskeyError as exc:
        raise _fail(ctx, request, "auth.passkey", None, "verify_failed") from exc
    user = ctx.store.user_by_id(user_id)
    if user is None or user.locked():
        raise _fail(ctx, request, "auth.passkey", None, "locked_or_missing")
    response.delete_cookie(CEREMONY_COOKIE, path="/api/auth")
    return _signed_in(ctx, request, response, user, "passkey")


@router.post("/auth/passkey/register/options")
def post_passkey_register_options(principal: PrincipalDep, request: Request, response: Response) -> dict[str, Any]:
    ctx = _ctx(request)
    user = ctx.store.user_by_id(principal.user_id)
    assert user is not None
    ceremony_id, options = ctx.passkeys.registration_options(user.id, user.username, user.display_name)
    ctx.set_ceremony(response, ceremony_id)
    return options


@router.post("/auth/passkey/register/verify", response_model=c.Me)
def post_passkey_register_verify(body: c.PasskeyCredential, principal: PrincipalDep, request: Request, response: Response) -> c.Me:
    ctx = _ctx(request)
    try:
        ctx.passkeys.register(request.cookies.get(CEREMONY_COOKIE), principal.user_id, body.model_dump())
    except PasskeyError as exc:
        ctx.store.audit.record("auth.passkey_added", actor=principal.user_id, outcome="failure",
                               ip_hash=client_ip_hash(ctx, request))
        raise UnauthorizedError(str(exc)) from exc
    response.delete_cookie(CEREMONY_COOKIE, path="/api/auth")
    ctx.store.audit.record("auth.passkey_added", actor=principal.user_id, ip_hash=client_ip_hash(ctx, request))
    user = ctx.store.user_by_id(principal.user_id)
    assert user is not None
    return _me(ctx, user)


# -- session ------------------------------------------------------------------------


@router.post("/auth/refresh", response_model=c.LoginStep)
def post_refresh(request: Request, response: Response):  # a returned Response bypasses response_model
    ctx = _ctx(request)
    outcome, user_id, family_id = ctx.store.consume_refresh(request.cookies.get(REFRESH_COOKIE, ""))
    if outcome == RefreshOutcome.REUSED:
        ctx.store.audit.record("auth.refresh_reuse", actor=user_id or "anonymous", outcome="denied",
                               ip_hash=client_ip_hash(ctx, request))
    user = ctx.store.user_by_id(user_id) if (outcome == RefreshOutcome.OK and user_id) else None
    if user is None or user.locked() or family_id is None:
        # Returned, not raised: a raised error would drop the cookie-clearing headers.
        failed = error_response(401, "unauthorized", "Your session ended. Sign in again.")
        ctx.end_session(failed)
        return failed
    ctx.start_session(response, user, family_id=family_id)
    return c.LoginStep(signed_in=True)


@router.post("/auth/logout", response_model=c.LoginStep)
def post_logout(request: Request, response: Response) -> c.LoginStep:
    ctx = _ctx(request)
    user_id = ctx.store.revoke_family_of(request.cookies.get(REFRESH_COOKIE, ""))
    principal = request.state.principal
    if principal is not None and principal.family_id:
        ctx.store.revoke_family(principal.family_id)
        user_id = user_id or principal.user_id
    ctx.end_session(response)
    if user_id:
        ctx.store.audit.record("auth.signout", actor=user_id, ip_hash=client_ip_hash(ctx, request))
    return c.LoginStep(signed_in=False)


@router.get("/auth/me", response_model=c.Me)
def get_me(principal: PrincipalDep, request: Request) -> c.Me:
    ctx = _ctx(request)
    user = ctx.store.user_by_id(principal.user_id)
    if user is None:
        raise UnauthorizedError("Sign in to continue")
    return _me(ctx, user)


@router.get("/audit", response_model=c.AuditView)
def get_audit(request: Request, limit: int = 100) -> c.AuditView:
    ctx = _ctx(request)
    intact, broken = ctx.store.audit.verify_chain()
    events = [c.AuditEventView(**e.__dict__) for e in ctx.store.audit.recent(limit)]
    return c.AuditView(chain_intact=intact, first_broken_id=broken, events=events)
