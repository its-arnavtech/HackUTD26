from __future__ import annotations

from datetime import datetime

import httpx
import pytest

from app.integrations import cache, rdap


def client_for(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def fixtures(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "FIXTURES_DIR", tmp_path)
    return tmp_path


def registered(request):
    return httpx.Response(200, json={"events": [{"eventAction": "registration", "eventDate": "2026-11-05T12:00:00Z"}]})


def test_registration_date_parsed():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, json={"events": [{"eventAction": "last changed", "eventDate": "2026-11-06T00:00:00Z"}, {"eventAction": "registration", "eventDate": "2026-11-05T12:00:00Z"}]})

    record = rdap.lookup_registration("capone-verify-alert.com", client=client_for(handler), mode="live")
    assert record == {"found": True, "registered_at": "2026-11-05T12:00:00Z"}
    assert seen == ["https://rdap.org/domain/capone-verify-alert.com"]
    assert rdap.domain_age_days(record, datetime.fromisoformat("2026-11-08T09:14:00-06:00")) == 3


def test_not_found():
    record = rdap.lookup_registration("nothing.com", client=client_for(lambda r: httpx.Response(404)), mode="live")
    assert record == {"found": False, "registered_at": None}
    assert rdap.domain_age_days(record, datetime.now()) is None


def test_server_error_returns_none():
    assert rdap.lookup_registration("x.com", client=client_for(lambda r: httpx.Response(503)), mode="live") is None


def test_network_error_returns_none():
    def handler(request):
        raise httpx.ConnectError("offline")

    assert rdap.lookup_registration("x.com", client=client_for(handler), mode="live") is None


def test_replay_miss_is_unavailable_and_never_calls_out(fixtures):
    def handler(request):
        raise AssertionError("network call in replay mode")

    assert rdap.lookup_registration("x.com", client=client_for(handler), mode="replay") is None


def test_record_then_replay_serves_the_fixture(fixtures):
    recorded = rdap.lookup_registration("capone-verify-alert.com", client=client_for(registered), mode="record")
    [path] = cache.list_fixtures("rdap")
    assert '"request": {\n    "domain": "capone-verify-alert.com"\n  }' in path.read_text(encoding="utf-8")

    def offline(request):
        raise AssertionError("network call in replay mode")

    replayed = rdap.lookup_registration("capone-verify-alert.com", client=client_for(offline), mode="replay")
    assert replayed == recorded == {"found": True, "registered_at": "2026-11-05T12:00:00Z"}


def test_failed_lookup_is_not_recorded(fixtures):
    assert rdap.lookup_registration("x.com", client=client_for(lambda r: httpx.Response(503)), mode="record") is None
    assert cache.list_fixtures("rdap") == []


def test_age_handles_naive_times_and_future_dates():
    as_of = datetime(2026, 11, 8)
    assert rdap.domain_age_days({"registered_at": "2026-11-01T00:00:00"}, as_of) == 7
    assert rdap.domain_age_days({"registered_at": "2026-12-01T00:00:00Z"}, as_of) == 0
    assert rdap.domain_age_days({"registered_at": "not a date"}, as_of) is None
