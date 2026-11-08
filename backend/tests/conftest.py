from __future__ import annotations

import os

import pytest

# Tests always run against the mocks, whatever the local .env says.
os.environ["USE_MOCKS"] = "true"


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import _reset_state, app

    get_settings.cache_clear()
    _reset_state()
    with TestClient(app) as test_client:
        yield test_client
    _reset_state()
