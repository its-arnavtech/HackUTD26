"""L2: app factory, /api/health, JSON errors, structured logs with message_id."""

from __future__ import annotations

import json
import logging

import pytest

from app.config import ROUTES, SettingsError
from app.logs import JsonFormatter, TextFormatter, _ContextFilter, bind_message_id
from app.main import create_app
from tests.conftest import make_settings

FAKE_KEY = "nvapi-test-not-a-real-key-123"


def _assert_error_shape(body: dict, code: str) -> None:
    assert set(body) == {"detail", "error"}
    assert body["error"]["code"] == code
    assert body["error"]["message"] == body["detail"]


# --- app factory -----------------------------------------------------------


def test_factory_builds_independent_apps():
    a, b = create_app(make_settings()), create_app(make_settings(DEMO_MODE="replay", LIVE_ROUTES="inbox"))
    assert a is not b
    assert a.state.settings.route_is_mocked("inbox") and not b.state.settings.route_is_mocked("inbox")


def test_factory_refuses_invalid_settings():
    with pytest.raises(SettingsError, match="NVIDIA_API_KEY"):
        create_app(make_settings(USE_MOCKS=False, DEMO_MODE="live"))


def test_module_level_app_exists_for_uvicorn():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200


# --- health ----------------------------------------------------------------


def test_health_with_mocks(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["demo_mode"] == "live" and body["use_mocks"] is True
    assert set(body["integrations"]) == {"nemotron", "gemini", "nessie", "rdap", "huggingface"}
    assert {v["mode"] for v in body["integrations"].values()} == {"mock"}
    assert set(body["mocked_routes"]) == set(ROUTES) and all(body["mocked_routes"].values())
    assert any("NVIDIA_API_KEY" in w for w in body["warnings"])


def test_health_in_live_mode_never_shows_keys(make_client):
    client = make_client(USE_MOCKS=False, DEMO_MODE="live", NVIDIA_API_KEY=FAKE_KEY, MOCK_ROUTES="campaigns")
    r = client.get("/api/health")
    assert FAKE_KEY not in r.text
    body = r.json()
    assert body["integrations"]["nemotron"] == {"mode": "live", "configured": True}
    assert body["integrations"]["gemini"]["mode"] == "disabled"
    assert body["mocked_routes"]["campaigns"] is True and body["mocked_routes"]["inbox"] is False


# --- per-route mocks and JSON errors ----------------------------------------


def test_route_without_mock_returns_json_501(make_client):
    client = make_client(USE_MOCKS=False, DEMO_MODE="replay", MOCK_ROUTES="campaigns")
    assert client.get("/api/campaigns").status_code == 200
    r = client.post("/api/transactions/txn_1/confirm", json={"was_me": False})
    assert r.status_code == 501
    body = r.json()
    _assert_error_shape(body, "not_implemented")
    assert body["error"]["details"] == {"issue": "L11"}


def test_live_route_override_with_mocks_on(make_client):
    client = make_client(USE_MOCKS=True, DEMO_MODE="replay", LIVE_ROUTES="metrics")
    assert client.get("/api/inbox").status_code == 200
    assert client.get("/api/metrics").json()["error"]["details"] == {"issue": "A13"}


def test_404_is_json_and_carries_message_id(client):
    r = client.get("/api/messages/msg_nope/result")
    assert r.status_code == 404
    body = r.json()
    _assert_error_shape(body, "not_found")
    assert body["error"]["message_id"] == "msg_nope"


def test_unknown_path_is_json_404(client):
    r = client.get("/api/does-not-exist")
    assert r.status_code == 404
    _assert_error_shape(r.json(), "not_found")


def test_validation_error_is_json_and_does_not_echo_input(client):
    r = client.post("/api/messages", json={"text": "my secret 4111111111111111"})
    assert r.status_code == 422
    body = r.json()
    _assert_error_shape(body, "validation_error")
    assert body["error"]["details"]["errors"]
    assert "4111111111111111" not in r.text


def test_unhandled_exception_is_json_500(make_client):
    client = make_client(raise_server_exceptions=False)

    @client.app.get("/api/_boom")
    def boom():
        raise RuntimeError("internal detail that must not leak")

    r = client.get("/api/_boom")
    assert r.status_code == 500
    _assert_error_shape(r.json(), "internal_error")
    assert "must not leak" not in r.text


# --- structured logs -----------------------------------------------------------


def _record(msg: str = "hello", **extra) -> logging.LogRecord:
    record = logging.makeLogRecord({"name": "app.test", "levelno": logging.INFO, "levelname": "INFO", "msg": msg, **extra})
    _ContextFilter().filter(record)
    return record


def test_json_log_line_carries_message_id_and_fields():
    with bind_message_id("msg_0001"):
        record = _record(fields={"tool": "check_link", "ms": 412})
    line = json.loads(JsonFormatter().format(record))
    assert line["message_id"] == "msg_0001"
    assert line["msg"] == "hello" and line["level"] == "info" and line["logger"] == "app.test"
    assert line["tool"] == "check_link" and line["ms"] == 412


def test_message_id_is_none_outside_a_binding():
    assert json.loads(JsonFormatter().format(_record()))["message_id"] is None


def test_text_log_line_carries_message_id():
    with bind_message_id("msg_0003"):
        record = _record(fields={"tool": "nessie_bill_status"})
    assert "[msg_0003]" in TextFormatter().format(record)


def test_request_logs_carry_message_id(client, caplog):
    caplog.set_level(logging.INFO, logger="app.request")
    client.get("/api/messages/msg_0001/result")
    lines = [r for r in caplog.records if r.name == "app.request"]
    assert lines, "expected one request log line"
    assert lines[-1].message_id == "msg_0001"
    assert lines[-1].fields["status"] == 200 and lines[-1].fields["path"] == "/api/messages/msg_0001/result"
