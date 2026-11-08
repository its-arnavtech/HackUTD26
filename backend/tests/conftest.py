from __future__ import annotations

import os

import pytest

# Tests always run against the mocks, whatever the local .env says.
os.environ["USE_MOCKS"] = "true"

# `TEST_AUTH=1 python -m pytest` reruns the whole suite with AUTH_ENABLED=true (L13):
# every `client` / `make_client` signs in first, as the demo customer with the
# admin role (so ownership of the seeded inbox and demo reset both still work).
# Role and ownership refusals are covered on their own in test_auth.py.
TEST_AUTH = os.environ.get("TEST_AUTH") == "1"


def make_settings(**overrides):
    """Settings that ignore the local .env file, so tests don't depend on anyone's keys."""
    from app.config import Settings

    base = {"USE_MOCKS": True, "MOCK_ROUTES": "", "LIVE_ROUTES": "", "DEMO_MODE": "live"}
    if TEST_AUTH and "AUTH_ENABLED" not in overrides:
        from tests.auth_helpers import auth_settings

        base.update(auth_settings())
    return Settings(_env_file=None, **{**base, **overrides})


def _client_for(settings, **kwargs):
    """A TestClient for `settings`; signed in when auth is on."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    if not settings.AUTH_ENABLED:
        return TestClient(create_app(settings), **kwargs)
    from app.auth.context import AuthContext
    from app.auth.deps import DEMO_CUSTOMER_ID
    from app.auth.store import AuthStore
    from tests.auth_helpers import BASE_URL, add_user, sign_in

    ctx = AuthContext(settings, store=AuthStore(":memory:"))
    test_client = TestClient(create_app(settings, auth_context=ctx), base_url=BASE_URL, **kwargs)
    sign_in(test_client, ctx, add_user(ctx.store, ctx.keyring, "demo", "admin", user_id=DEMO_CUSTOMER_ID))
    return test_client


@pytest.fixture
def client():
    from app.config import get_settings
    from app.main import _reset_state

    get_settings.cache_clear()
    _reset_state()
    with _client_for(make_settings()) as test_client:
        yield test_client
    _reset_state()


@pytest.fixture
def make_client():
    """Build a client for an app created with custom settings: `make_client(USE_MOCKS=False)`."""
    from app.main import _reset_state

    clients = []

    def _make(raise_server_exceptions: bool = True, **overrides):
        _reset_state()
        test_client = _client_for(make_settings(**overrides), raise_server_exceptions=raise_server_exceptions)
        clients.append(test_client)
        return test_client

    yield _make
    for test_client in clients:
        test_client.close()
    _reset_state()


@pytest.fixture
def auth_app():
    """An auth-enabled app (mocked routes) with three users: demo customer, other customer, admin.

    Returns `(make, ctx, users)`; `make()` gives a fresh signed-out client, so
    tests can hold several sessions at once.
    """
    from fastapi.testclient import TestClient

    from app.auth.context import AuthContext
    from app.auth.store import AuthStore
    from app.main import _reset_state, create_app
    from tests.auth_helpers import BASE_URL, auth_settings, seed_users

    _reset_state()
    settings = make_settings(**auth_settings())
    ctx = AuthContext(settings, store=AuthStore(":memory:"))
    app = create_app(settings, auth_context=ctx)
    users = seed_users(ctx)
    clients: list[TestClient] = []

    def make() -> TestClient:
        test_client = TestClient(app, base_url=BASE_URL)
        clients.append(test_client)
        return test_client

    yield make, ctx, users
    for test_client in clients:
        test_client.close()
    _reset_state()
