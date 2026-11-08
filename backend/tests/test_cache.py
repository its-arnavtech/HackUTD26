"""L1: record and replay cache."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone

import pytest
from pydantic import BaseModel

from app.contracts import DemoMode
from app.integrations import cache
from app.integrations.cache import FixtureCorruptError, FixtureMissingError, cached_call, request_key


@pytest.fixture
def fixtures(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "FIXTURES_DIR", tmp_path)
    return tmp_path


class Counter:
    def __init__(self, value):
        self.calls, self.value = 0, value

    def __call__(self):
        self.calls += 1
        return self.value


REQ = {"method": "GET", "path": "/accounts/acc_1/bills"}


# --- keys -------------------------------------------------------------------


def test_key_is_stable_and_order_independent():
    a = request_key("nessie", {"path": "/x", "params": {"a": 1, "b": 2}})
    b = request_key("nessie", {"params": {"b": 2, "a": 1}, "path": "/x"})
    assert a == b and len(a) == 32


def test_key_depends_on_service_and_request():
    assert request_key("nessie", REQ) != request_key("rdap", REQ)
    assert request_key("nessie", REQ) != request_key("nessie", {**REQ, "path": "/other"})


def test_secrets_never_change_the_key():
    base = request_key("nessie", REQ)
    assert request_key("nessie", {**REQ, "key": "abc123"}) == base
    assert request_key("nessie", {**REQ, "headers": {"Authorization": "Bearer x"}}) == base
    assert request_key("nessie", {**REQ, "params": {"api_key": "x"}}) == request_key("nessie", {**REQ, "params": {}})


def test_volatile_fields_are_ignored():
    a = request_key("nessie", {**REQ, "now": "2026-11-07T18:00"}, volatile=["now"])
    b = request_key("nessie", {**REQ, "now": "2026-11-08T09:30"}, volatile=["now"])
    assert a == b == request_key("nessie", REQ)


def test_key_handles_models_enums_and_datetimes():
    class Args(BaseModel):
        domain: str

    req = {"args": Args(domain="example.test"), "mode": DemoMode.replay, "since": datetime(2026, 11, 7, tzinfo=timezone.utc)}
    assert request_key("x", req) == request_key(
        "x", {"args": {"domain": "example.test"}, "mode": "replay", "since": "2026-11-07T00:00:00+00:00"}
    )


def test_unserialisable_request_is_rejected():
    with pytest.raises(TypeError):
        request_key("x", {"thing": object()})


def test_bad_service_name_is_rejected(fixtures):
    with pytest.raises(ValueError):
        cached_call("../evil", REQ, lambda: 1, mode="record")


# --- modes -------------------------------------------------------------------


def test_live_calls_every_time_and_saves_nothing(fixtures):
    fn = Counter({"ok": True})
    assert cached_call("nessie", REQ, fn, mode="live") == {"ok": True}
    cached_call("nessie", REQ, fn, mode="live")
    assert fn.calls == 2
    assert not any(fixtures.rglob("*.json"))


def test_record_then_replay_without_calling(fixtures):
    response = {"bills": [{"payee": "T-Mobile", "status": "completed", "amount": 85.0}]}
    recorded = cached_call("nessie", REQ, Counter(response), mode="record")
    assert recorded == response

    never = Counter(None)
    assert cached_call("nessie", REQ, never, mode="replay") == response
    assert never.calls == 0


def test_fixture_file_layout_and_contents(fixtures):
    cached_call("nessie", {**REQ, "key": "SECRET-NESSIE-KEY"}, lambda: {"ok": 1}, mode="record")
    files = list(fixtures.glob("nessie/*.json"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert "SECRET-NESSIE-KEY" not in text
    data = json.loads(text)
    assert data["service"] == "nessie" and data["key"] == files[0].stem
    assert data["request"] == REQ and data["response"] == {"ok": 1}
    assert data["version"] == cache.FIXTURE_VERSION and data["recorded_at"]


def test_replay_miss_is_a_clear_error(fixtures):
    with pytest.raises(FixtureMissingError) as exc:
        cached_call("gemini", {"q": "never recorded"}, Counter(1), mode="replay")
    assert "DEMO_MODE=record" in str(exc.value) and exc.value.service == "gemini"


def test_record_overwrites_with_the_latest_response(fixtures):
    cached_call("rdap", REQ, lambda: {"age_days": 1}, mode="record")
    cached_call("rdap", REQ, lambda: {"age_days": 2}, mode="record")
    assert cached_call("rdap", REQ, Counter(None), mode="replay") == {"age_days": 2}
    assert len(cache.list_fixtures("rdap")) == 1


def test_errors_propagate_and_are_not_recorded(fixtures):
    def boom():
        raise ConnectionError("network down")

    with pytest.raises(ConnectionError):
        cached_call("nemotron", REQ, boom, mode="record")
    assert not cache.has_fixture("nemotron", REQ)


def test_pydantic_response_round_trips_with_decode(fixtures):
    class Out(BaseModel):
        verdict: str
        sources: list[str]

    out = Out(verdict="likely_scam", sources=["https://example.test/a"])
    assert cached_call("gemini", REQ, lambda: out, mode="record") is out
    assert cached_call("gemini", REQ, Counter(None), mode="replay") == out.model_dump(mode="json")
    assert cached_call("gemini", REQ, Counter(None), mode="replay", decode=Out.model_validate) == out


def test_response_keeps_fields_named_like_secrets(fixtures):
    # Only requests drop secret-looking names; a response replays exactly as recorded.
    response = {"key": "txn_3", "token_count": 12, "headers": ["a"]}
    cached_call("nessie", REQ, lambda: response, mode="record")
    assert cached_call("nessie", REQ, Counter(None), mode="replay") == response


def test_mode_defaults_to_demo_mode_setting(fixtures, monkeypatch):
    monkeypatch.setattr(cache, "_current_mode", lambda: DemoMode.record)
    cached_call("nessie", REQ, lambda: {"ok": 1})
    monkeypatch.setattr(cache, "_current_mode", lambda: DemoMode.replay)
    assert cached_call("nessie", REQ, Counter(None)) == {"ok": 1}


def test_demo_mode_comes_from_settings(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("DEMO_MODE", "replay")
    get_settings.cache_clear()
    try:
        assert cache._current_mode() == DemoMode.replay
    finally:
        get_settings.cache_clear()


def test_corrupt_fixture_is_reported(fixtures):
    path = cache.fixture_path("nessie", request_key("nessie", REQ))
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(FixtureCorruptError):
        cached_call("nessie", REQ, Counter(None), mode="replay")


def test_parallel_records_leave_one_valid_file(fixtures):
    errors: list[BaseException] = []

    def record(i: int) -> None:
        try:
            cached_call("nessie", REQ, lambda: {"n": i}, mode="record")
        except BaseException as exc:  # surface thread failures in the test
            errors.append(exc)

    threads = [threading.Thread(target=record, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    files = list(fixtures.glob("nessie/*"))
    assert len(files) == 1  # no leftover temp files
    assert "n" in cached_call("nessie", REQ, Counter(None), mode="replay")


def test_list_and_has_fixture(fixtures):
    cached_call("nessie", REQ, lambda: 1, mode="record")
    cached_call("rdap", {"domain": "example.test"}, lambda: 2, mode="record")
    assert len(cache.list_fixtures()) == 2 and len(cache.list_fixtures("rdap")) == 1
    assert cache.has_fixture("rdap", {"domain": "example.test"})
    assert not cache.has_fixture("rdap", {"domain": "other.test"})


def test_nemotron_call_shape_from_a4(fixtures):
    """A4 calls cached_call(service, request, fn) positionally; record then replay must work for it."""
    request = {
        "base_url": "https://integrate.api.nvidia.com/v1",
        "operation": "chat",
        "model": "nvidia/nemotron-3.5-bolt-e4b",
        "messages": [{"role": "user", "content": "[REDACTED] verify your account"}],
        "temperature": 0,
    }
    completion = {"choices": [{"message": {"role": "assistant", "tool_calls": [{"function": {"name": "check_link"}}]}}]}
    assert cache.cached_call("nemotron", request, lambda: completion, mode=DemoMode.record) == completion
    assert cache.cached_call("nemotron", request, Counter(None), mode=DemoMode.replay) == completion
