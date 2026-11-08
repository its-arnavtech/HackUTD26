from __future__ import annotations

import os

import pytest

# Tests always run against the mocks, whatever the local .env says.
os.environ["USE_MOCKS"] = "true"


def make_settings(**overrides):
    """Settings that ignore the local .env file, so tests don't depend on anyone's keys."""
    from app.config import Settings

    base = {"USE_MOCKS": True, "MOCK_ROUTES": "", "LIVE_ROUTES": "", "DEMO_MODE": "live"}
    return Settings(_env_file=None, **{**base, **overrides})


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import _reset_state, create_app

    get_settings.cache_clear()
    _reset_state()
    with TestClient(create_app(make_settings())) as test_client:
        yield test_client
    _reset_state()


@pytest.fixture
def make_client():
    """Build a client for an app created with custom settings: `make_client(USE_MOCKS=False)`."""
    from fastapi.testclient import TestClient

    from app.main import _reset_state, create_app

    clients = []

    def _make(raise_server_exceptions: bool = True, **overrides):
        _reset_state()
        test_client = TestClient(create_app(make_settings(**overrides)), raise_server_exceptions=raise_server_exceptions)
        clients.append(test_client)
        return test_client

    yield _make
    for test_client in clients:
        test_client.close()
    _reset_state()
