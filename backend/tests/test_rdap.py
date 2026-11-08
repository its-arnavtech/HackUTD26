from __future__ import annotations

from datetime import datetime

import httpx
import pytest

from app.config import get_settings
from app.integrations import rdap


def client_for(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def live_mode(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "live")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_registration_date_parsed(live_mode):
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, json={"events": [{"eventAction": "last changed", "eventDate": "2026-11-06T00:00:00Z"}, {"eventAction": "registration", "eventDate": "2026-11-05T12:00:00Z"}]})

    record = rdap.lookup_registration("capone-verify-alert.com", client=client_for(handler))
    assert record == {"found": True, "registered_at": "2026-11-05T12:00:00Z"}
    assert seen == ["https://rdap.org/domain/capone-verify-alert.com"]
    assert rdap.domain_age_days(record, datetime.fromisoformat("2026-11-08T09:14:00-06:00")) == 3


def test_not_found(live_mode):
    record = rdap.lookup_registration("nothing.com", client=client_for(lambda r: httpx.Response(404)))
    assert record == {"found": False, "registered_at": None}
    assert rdap.domain_age_days(record, datetime.now()) is None


def test_server_error_returns_none(live_mode):
    assert rdap.lookup_registration("x.com", client=client_for(lambda r: httpx.Response(503))) is None


def test_network_error_returns_none(live_mode):
    def handler(request):
        raise httpx.ConnectError("offline")

    assert rdap.lookup_registration("x.com", client=client_for(handler)) is None


def test_replay_mode_never_calls_out(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "replay")
    get_settings.cache_clear()

    def handler(request):
        raise AssertionError("network call in replay mode")

    try:
        assert rdap.lookup_registration("x.com", client=client_for(handler)) is None
    finally:
        get_settings.cache_clear()


def test_age_handles_naive_times_and_future_dates():
    as_of = datetime(2026, 11, 8)
    assert rdap.domain_age_days({"registered_at": "2026-11-01T00:00:00"}, as_of) == 7
    assert rdap.domain_age_days({"registered_at": "2026-12-01T00:00:00Z"}, as_of) == 0
    assert rdap.domain_age_days({"registered_at": "not a date"}, as_of) is None
