"""L2: settings validation, per-route mocks and integration modes."""

from __future__ import annotations

import pytest

from app.config import (
    ROUTES,
    SettingsError,
    check_settings,
    integration_modes,
    load_settings,
    validate_settings,
)
from tests.conftest import make_settings

FAKE_KEY = "nvapi-test-not-a-real-key-123"


def test_defaults_are_valid_with_mocks_and_no_keys():
    s = make_settings()
    warnings = validate_settings(s)
    assert all(w.level == "warning" for w in warnings)
    assert {w.variable for w in warnings} >= {"NVIDIA_API_KEY", "GEMINI_API_KEY", "NESSIE_API_KEY"}


def test_blank_key_counts_as_missing():
    assert make_settings(NVIDIA_API_KEY="   ").NVIDIA_API_KEY is None


def test_missing_nvidia_key_is_an_error_when_real_routes_call_out():
    s = make_settings(USE_MOCKS=False, DEMO_MODE="live")
    with pytest.raises(SettingsError) as exc:
        validate_settings(s)
    message = str(exc.value)
    assert "NVIDIA_API_KEY" in message and ".env" in message
    assert "USE_MOCKS=true or DEMO_MODE=replay" in message


def test_one_live_route_is_enough_to_require_the_key():
    with pytest.raises(SettingsError):
        validate_settings(make_settings(USE_MOCKS=True, LIVE_ROUTES="result"))


def test_replay_mode_needs_no_keys():
    s = make_settings(USE_MOCKS=False, DEMO_MODE="replay")
    assert all(i.level == "warning" for i in check_settings(s))


def test_record_mode_with_key_is_valid_and_gemini_is_only_a_warning():
    s = make_settings(USE_MOCKS=False, DEMO_MODE="record", NVIDIA_API_KEY=FAKE_KEY)
    warnings = validate_settings(s)
    assert "GEMINI_API_KEY" in {w.variable for w in warnings}


def test_same_api_and_web_port_is_an_error():
    with pytest.raises(SettingsError, match="API_PORT"):
        validate_settings(make_settings(API_PORT=5173, WEB_PORT=5173))


def test_bad_demo_mode_gives_a_clear_message(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "turbo")
    with pytest.raises(SettingsError) as exc:
        load_settings()
    message = str(exc.value)
    assert "DEMO_MODE" in message and "live, record or replay" in message
    assert "turbo" not in message  # never echo values: one could be a pasted key


def test_unknown_route_name_lists_valid_names(monkeypatch):
    monkeypatch.setenv("MOCK_ROUTES", "inbox,nope")
    with pytest.raises(SettingsError) as exc:
        load_settings()
    assert "nope" in str(exc.value) and "campaigns" in str(exc.value)


def test_route_switches():
    s = make_settings(USE_MOCKS=False, MOCK_ROUTES="campaigns, metrics", NVIDIA_API_KEY=FAKE_KEY)
    assert s.route_is_mocked("campaigns") and s.route_is_mocked("metrics")
    assert not s.route_is_mocked("inbox")

    s = make_settings(USE_MOCKS=True, LIVE_ROUTES="inbox")
    assert not s.route_is_mocked("inbox")
    assert all(s.route_is_mocked(r) for r in ROUTES if r != "inbox")

    s = make_settings(MOCK_ROUTES="inbox", LIVE_ROUTES="inbox")
    assert s.route_is_mocked("inbox")  # MOCK_ROUTES wins

    with pytest.raises(KeyError):
        s.route_is_mocked("not_a_route")


def test_integration_modes():
    assert {v["mode"] for v in integration_modes(make_settings()).values()} == {"mock"}

    replay = integration_modes(make_settings(USE_MOCKS=False, DEMO_MODE="replay"))
    assert {v["mode"] for v in replay.values()} == {"replay"}

    live = integration_modes(make_settings(USE_MOCKS=False, DEMO_MODE="live", NVIDIA_API_KEY=FAKE_KEY))
    assert live["nemotron"] == {"mode": "live", "configured": True}
    assert live["gemini"] == {"mode": "disabled", "configured": False}
    assert live["rdap"] == {"mode": "live", "configured": True}


def test_secrets_never_appear_in_repr_or_errors():
    s = make_settings(USE_MOCKS=False, DEMO_MODE="live", NVIDIA_API_KEY=FAKE_KEY, API_PORT=1, WEB_PORT=1)
    assert FAKE_KEY not in repr(s)
    with pytest.raises(SettingsError) as exc:
        validate_settings(s)
    assert FAKE_KEY not in str(exc.value)
