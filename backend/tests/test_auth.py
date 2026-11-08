"""Authentication and authorization (L13): the happy path once, then every failure path."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import pyotp
import pytest
from fastapi import Depends
from fastapi.routing import APIRoute

from app.auth.deps import ROUTE_PERMISSIONS, authorize
from app.auth.tokens import TokenError
from tests.auth_helpers import PASSWORD, SoftAuthenticator, b64u, csrf, sign_in


def _cookie_header(response, name: str) -> str:
    return next(h for h in response.headers.get_list("set-cookie") if h.startswith(f"{name}="))


# ---------------------------------------------------------------------------
# Auth off: nothing changes
# ---------------------------------------------------------------------------


def test_auth_off_by_default_routes_work_and_auth_routes_are_absent(client):
    from tests.conftest import TEST_AUTH

    if TEST_AUTH:
        pytest.skip("this suite run has auth on")
    assert client.get("/api/health").json()["auth_enabled"] is False
    assert client.get("/api/inbox").status_code == 200
    assert client.post("/api/messages", json={"text": "hi", "sender": "+1 555 0100", "received_at": "2026-11-08T08:00:00Z"}).status_code == 200
    assert client.get("/api/auth/me").status_code == 404


def test_every_api_route_has_an_access_rule(auth_app):
    make, _, _ = auth_app
    app = make().app
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path.startswith("/api"):
            for method in route.methods - {"HEAD", "OPTIONS"}:
                assert (method, route.path) in ROUTE_PERMISSIONS, f"{method} {route.path} has no access rule"


def test_route_without_a_rule_is_denied_by_default(auth_app):
    make, ctx, users = auth_app
    client = make()

    @client.app.get("/api/sneaky", dependencies=[Depends(authorize)])
    def sneaky() -> dict:
        return {"open": True}

    sign_in(client, ctx, users["admin"])
    r = client.get("/api/sneaky")
    assert r.status_code == 403
    assert any(e.event == "access.no_rule" for e in ctx.store.audit.recent())


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_password_and_totp_sign_in_sets_hardened_cookies_and_no_token_in_body(auth_app):
    make, ctx, users = auth_app
    client = make()
    csrf(client)
    r1 = client.post("/api/auth/login", json={"username": "demo", "password": PASSWORD})
    assert r1.json() == {"signed_in": False, "mfa_required": True}
    r2 = client.post("/api/auth/login/totp", json={"code": pyotp.TOTP(users["demo"].totp_secret).now()})
    assert r2.status_code == 200 and r2.json()["signed_in"] is True
    for name in ("sa_at", "sa_rt"):
        header = _cookie_header(r2, name).lower()
        assert "httponly" in header and "secure" in header and "samesite=strict" in header
    assert "httponly" not in _cookie_header(r2, "sa_csrf").lower()  # the page must read this one
    for body in (r1.text, r2.text):
        assert "eyJ" not in body and "token" not in body.lower()
    client.headers["X-CSRF-Token"] = client.cookies.get("sa_csrf")
    me = client.get("/api/auth/me").json()
    assert me["username"] == "demo" and me["role"] == "customer"
    assert client.get("/api/inbox").status_code == 200
    assert ctx.store.audit.verify_chain() == (True, None)


def test_passkey_register_then_sign_in(auth_app):
    make, ctx, users = auth_app
    client = make()
    sign_in(client, ctx, users["demo"])
    authn = SoftAuthenticator()
    options = client.post("/api/auth/passkey/register/options").json()
    assert options["authenticatorSelection"]["userVerification"] == "required"
    r = client.post("/api/auth/passkey/register/verify", json=authn.register(options))
    assert r.status_code == 200 and r.json()["passkeys"] == 1
    client.post("/api/auth/logout")

    fresh = make()
    csrf(fresh)
    options = fresh.post("/api/auth/passkey/login/options").json()
    assert options.get("allowCredentials", []) == []  # usernameless: nothing to enumerate
    r = fresh.post("/api/auth/passkey/login/verify", json=authn.assert_(options))
    assert r.status_code == 200 and r.json()["signed_in"] is True
    fresh.headers["X-CSRF-Token"] = fresh.cookies.get("sa_csrf")
    assert fresh.get("/api/auth/me").json()["user_id"] == users["demo"].id


# ---------------------------------------------------------------------------
# Unauthenticated, CSRF, rate limit
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/inbox"), ("GET", "/api/metrics"), ("GET", "/api/campaigns"), ("GET", "/api/auth/me"),
    ("GET", "/api/messages/msg_0001/result"), ("GET", "/api/privacy/msg_0001"),
])
def test_routes_need_a_session(auth_app, method, path):
    make, _, _ = auth_app
    r = make().request(method, path)
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"


def test_health_stays_public(auth_app):
    make, _, _ = auth_app
    assert make().get("/api/health").json()["auth_enabled"] is True


def test_post_without_csrf_header_is_refused(auth_app):
    make, ctx, users = auth_app
    client = make()
    sign_in(client, ctx, users["demo"])
    del client.headers["X-CSRF-Token"]
    r = client.post("/api/messages", json={"text": "hi", "sender": "+1 555 0100", "received_at": "2026-11-08T08:00:00Z"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf_failed"
    client.headers["X-CSRF-Token"] = "not-the-cookie"
    assert client.post("/api/actions", json={"message_id": "msg_0001", "action": "block_sender"}).status_code == 403


def test_login_without_csrf_is_refused(auth_app):
    make, _, _ = auth_app
    r = make().post("/api/auth/login", json={"username": "demo", "password": PASSWORD})
    assert r.status_code == 403


def test_auth_routes_are_rate_limited_per_ip(auth_app):
    make, ctx, _ = auth_app
    ctx.limiter.per_minute = 3
    client = make()
    codes = [client.get("/api/auth/csrf").status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200] and codes[3:] == [429, 429]
    assert any(e.event == "auth.rate_limited" for e in ctx.store.audit.recent())


# ---------------------------------------------------------------------------
# Sign-in failures
# ---------------------------------------------------------------------------


def test_unknown_user_and_wrong_password_look_identical(auth_app):
    make, _, _ = auth_app
    client = make()
    csrf(client)
    a = client.post("/api/auth/login", json={"username": "nobody", "password": PASSWORD})
    b = client.post("/api/auth/login", json={"username": "demo", "password": "wrong password!"})
    assert a.status_code == b.status_code == 401
    assert a.json()["error"]["message"] == b.json()["error"]["message"]


def test_lockout_after_five_failures_even_with_the_right_password(auth_app):
    make, ctx, _ = auth_app
    client = make()
    csrf(client)
    for _ in range(5):
        client.post("/api/auth/login", json={"username": "other", "password": "wrong password!"})
    r = client.post("/api/auth/login", json={"username": "other", "password": PASSWORD})
    assert r.status_code == 401
    assert ctx.store.user_by_username("other").locked()
    assert any(e.event == "auth.locked" for e in ctx.store.audit.recent())


def test_bad_totp_and_replayed_totp_are_refused(auth_app):
    make, ctx, users = auth_app
    client = make()
    csrf(client)
    client.post("/api/auth/login", json={"username": "demo", "password": PASSWORD})
    assert client.post("/api/auth/login/totp", json={"code": "000000"}).status_code == 401

    sign_in(client, ctx, users["demo"])  # uses the current step
    again = make()
    csrf(again)
    again.post("/api/auth/login", json={"username": "demo", "password": PASSWORD})
    code = pyotp.TOTP(users["demo"].totp_secret).now()
    assert again.post("/api/auth/login/totp", json={"code": code}).status_code == 401  # same code, replayed


def test_totp_without_password_step_is_refused(auth_app):
    make, _, users = auth_app
    client = make()
    csrf(client)
    r = client.post("/api/auth/login/totp", json={"code": pyotp.TOTP(users["demo"].totp_secret).now()})
    assert r.status_code == 401


def test_passkey_bad_signature_and_rolled_back_counter_are_refused(auth_app):
    make, ctx, users = auth_app
    client = make()
    sign_in(client, ctx, users["demo"])
    authn = SoftAuthenticator()
    authn.register(client.post("/api/auth/passkey/register/options").json())
    options = client.post("/api/auth/passkey/register/options").json()
    authn2 = SoftAuthenticator()
    assert client.post("/api/auth/passkey/register/verify", json=authn2.register(options)).status_code == 200

    fresh = make()
    csrf(fresh)
    opts = fresh.post("/api/auth/passkey/login/options").json()
    assert fresh.post("/api/auth/passkey/login/verify", json=authn2.assert_(opts, tamper=True)).status_code == 401

    opts = fresh.post("/api/auth/passkey/login/options").json()
    assert fresh.post("/api/auth/passkey/login/verify", json=authn2.assert_(opts, sign_count=10)).status_code == 200
    fresh.headers["X-CSRF-Token"] = fresh.cookies.get("sa_csrf")  # rotated on sign-in
    opts = fresh.post("/api/auth/passkey/login/options").json()  # a cloned authenticator replays an older count
    assert fresh.post("/api/auth/passkey/login/verify", json=authn2.assert_(opts, sign_count=5)).status_code == 401


def test_passkey_challenge_is_single_use(auth_app):
    make, ctx, users = auth_app
    client = make()
    sign_in(client, ctx, users["demo"])
    authn = SoftAuthenticator()
    client.post("/api/auth/passkey/register/verify", json=authn.register(client.post("/api/auth/passkey/register/options").json()))
    fresh = make()
    csrf(fresh)
    opts = fresh.post("/api/auth/passkey/login/options").json()
    assertion = authn.assert_(opts)
    ceremony = fresh.cookies.get("sa_wa", path="/api/auth")
    assert ceremony
    assert fresh.post("/api/auth/passkey/login/verify", json=assertion).status_code == 200
    replay = make()
    csrf(replay)
    replay.cookies.set("sa_wa", ceremony, domain="testserver.local", path="/api/auth")
    assert replay.post("/api/auth/passkey/login/verify", json=assertion).status_code == 401


def test_passkey_registration_needs_a_session(auth_app):
    make, _, _ = auth_app
    client = make()
    csrf(client)
    assert client.post("/api/auth/passkey/register/options").status_code == 401


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------


def _forge(header: dict, claims: dict, signature: bytes = b"") -> str:
    enc = lambda d: b64u(json.dumps(d, separators=(",", ":")).encode())  # noqa: E731
    return f"{enc(header)}.{enc(claims)}.{b64u(signature)}"


def _claims(ctx, user_id: str, **over) -> dict:
    now = int(datetime.now(timezone.utc).timestamp())
    base = {"iss": "sentinelai", "aud": "sentinelai-web", "sub": user_id, "role": "admin", "fam": "f", "iat": now, "exp": now + 600, "jti": "j"}
    return {**base, **over}


def test_token_attacks_are_rejected(auth_app):
    make, ctx, users = auth_app
    t = ctx.tokens
    uid = users["demo"].id
    good = t.issue_access(uid, "customer", "fam1")
    assert t.verify_access(good).user_id == uid

    attacks = {
        "alg none": _forge({"alg": "none", "typ": "JWT", "kid": "k1"}, _claims(ctx, uid)),
        "expired": t.issue_access(uid, "customer", "fam1", now=datetime.now(timezone.utc) - timedelta(hours=1)),
        "tampered payload": good.split(".")[0] + "." + b64u(json.dumps(_claims(ctx, uid)).encode()) + "." + good.split(".")[2],
        "wrong kid": _forge({"alg": "ES256", "kid": "k2"}, _claims(ctx, uid), b"x" * 64),
        "mfa ticket as access": t.issue_mfa_ticket(uid),
        "garbage": "not.a.jwt",
    }
    # HS256 signed with the public key: the classic algorithm-confusion attack.
    from cryptography.hazmat.primitives import serialization

    pem = t._public.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    header, payload = b64u(json.dumps({"alg": "HS256", "kid": "k1"}).encode()), b64u(json.dumps(_claims(ctx, uid)).encode())
    attacks["hs256 confusion"] = f"{header}.{payload}.{b64u(hmac.new(pem, f'{header}.{payload}'.encode(), hashlib.sha256).digest())}"
    other_issuer = type(t)(  # same key, wrong issuer / audience
        base64.b64encode(t._private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                   serialization.NoEncryption())).decode(),
        "k1", "evil", "sentinelai-web",
    )
    attacks["wrong issuer"] = other_issuer.issue_access(uid, "admin", "fam1")

    client = make()
    client.cookies.set("sa_at", good, domain="testserver.local", path="/api")
    assert client.get("/api/auth/me").status_code == 200  # control: a valid token sent this way works
    for name, token in attacks.items():
        with pytest.raises(TokenError):
            t.verify_access(token)
        client.cookies.set("sa_at", token, domain="testserver.local", path="/api")
        assert client.get("/api/auth/me").status_code == 401, name


def test_role_comes_from_the_database_not_the_token(auth_app):
    make, ctx, users = auth_app
    client = make()
    sign_in(client, ctx, users["admin"])
    assert client.post("/api/demo/reset").status_code == 200
    ctx.store._db.execute("UPDATE users SET role = 'customer' WHERE id = ?", (users["admin"].id,))
    assert client.post("/api/demo/reset").status_code == 403  # same token, demoted at once


def test_refresh_rotates_and_reuse_revokes_the_whole_sign_in(auth_app):
    make, ctx, users = auth_app
    client = make()
    sign_in(client, ctx, users["demo"])
    first_refresh = client.cookies.get("sa_rt", path="/api/auth")
    assert client.post("/api/auth/refresh").status_code == 200
    assert client.cookies.get("sa_rt", path="/api/auth") != first_refresh
    assert client.get("/api/auth/me").status_code == 200

    thief = make()
    csrf(thief)
    thief.cookies.set("sa_rt", first_refresh, domain="testserver.local", path="/api/auth")
    assert thief.post("/api/auth/refresh").status_code == 401
    assert any(e.event == "auth.refresh_reuse" for e in ctx.store.audit.recent())
    assert client.get("/api/auth/me").status_code == 401  # the real user's session is revoked too
    assert client.post("/api/auth/refresh").status_code == 401


def test_logout_revokes_the_access_token_too(auth_app):
    make, ctx, users = auth_app
    client = make()
    sign_in(client, ctx, users["demo"])
    access = client.cookies.get("sa_at", path="/api")
    assert client.post("/api/auth/logout").json()["signed_in"] is False
    replay = make()
    replay.cookies.set("sa_at", access, domain="testserver.local", path="/api")
    assert replay.get("/api/auth/me").status_code == 401
    still_valid = make()  # control: a live session's token sent the same way works
    sign_in(still_valid, ctx, users["other"])
    probe = make()
    probe.cookies.set("sa_at", still_valid.cookies.get("sa_at", path="/api"), domain="testserver.local", path="/api")
    assert probe.get("/api/auth/me").status_code == 200


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


def test_customer_cannot_call_admin_routes(auth_app):
    make, ctx, users = auth_app
    client = make()
    sign_in(client, ctx, users["demo"])
    assert client.post("/api/demo/reset").status_code == 403
    assert client.get("/api/audit").status_code == 403
    assert any(e.event == "access.forbidden" for e in ctx.store.audit.recent())


def test_customer_cannot_see_or_touch_another_users_messages(auth_app):
    make, ctx, users = auth_app
    owner, intruder = make(), make()
    sign_in(owner, ctx, users["demo"])
    sign_in(intruder, ctx, users["other"])
    assert owner.get("/api/messages/msg_0001/result").status_code == 200
    assert intruder.get("/api/inbox").json() == []
    for r in (
        intruder.get("/api/messages/msg_0001/result"),
        intruder.get("/api/privacy/msg_0001"),
        intruder.post("/api/messages/msg_0001/clicked"),
        intruder.get("/api/messages/msg_9999/result"),
    ):
        assert r.status_code == 404 and r.json()["error"]["message"] == "Unknown message_id"  # same as unknown

    posted = intruder.post("/api/messages", json={"text": "hi", "sender": "+1 555 0100", "received_at": "2026-11-08T08:00:00Z"})
    mid = posted.json()["message_id"]
    assert [i["message_id"] for i in intruder.get("/api/inbox").json()] == [mid]
    assert owner.get(f"/api/messages/{mid}/result").status_code == 404


def test_admin_cannot_read_customer_messages(auth_app):
    make, ctx, users = auth_app
    admin = make()
    sign_in(admin, ctx, users["admin"])
    assert admin.get("/api/messages/msg_0001/result").status_code == 404


def test_audit_view_is_content_free_and_verifiable(auth_app):
    make, ctx, users = auth_app
    client = make()
    csrf(client)
    client.post("/api/auth/login", json={"username": "demo", "password": "wrong password!"})
    sign_in(client, ctx, users["admin"])
    view = client.get("/api/audit").json()
    assert view["chain_intact"] is True
    events = {e["event"] for e in view["events"]}
    assert {"auth.password", "auth.signin"} <= events
    raw = json.dumps(view)
    assert "testclient" not in raw and PASSWORD not in raw and "wrong password" not in raw
    assert all(len(e["ip_hash"]) == 16 for e in view["events"] if e["ip_hash"])


def test_settings_refuse_auth_without_keys():
    from app.config import SettingsError, validate_settings
    from tests.conftest import make_settings

    with pytest.raises(SettingsError) as exc:
        validate_settings(make_settings(AUTH_ENABLED=True, JWT_PRIVATE_KEY="", DATA_ENCRYPTION_KEYS=""))
    assert "JWT_PRIVATE_KEY" in str(exc.value) and "DATA_ENCRYPTION_KEYS" in str(exc.value)
