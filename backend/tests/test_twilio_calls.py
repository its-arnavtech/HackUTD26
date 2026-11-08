"""Twilio voice calls (L16): create_call, get_call, and inline TwiML. No network."""

from __future__ import annotations

import logging
from urllib.parse import parse_qsl

import httpx
import pytest

from app.contracts import DemoMode
from app.integrations.twilio import TwilioClient, TwilioError, voice_twiml

TOKEN = "twilio-auth-token-secret"
PHONE = "+15125550199"
CALLER = "+15125550100"
SID_ACCOUNT = "AC_test_account"


def _client(handler, mode: DemoMode = DemoMode.live) -> TwilioClient:
    return TwilioClient(SID_ACCOUNT, TOKEN, CALLER, mode, transport=httpx.MockTransport(handler))


def test_voice_twiml_says_the_alert_twice_and_escapes():
    twiml = voice_twiml("Hello & <there>")
    assert twiml == '<Response><Say>Hello &amp; &lt;there&gt;</Say><Pause length="1"/><Say>Hello &amp; &lt;there&gt;</Say></Response>'
    assert twiml.count("<Say>") == 2


def test_create_call_posts_inline_twiml_and_returns_the_sid():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.content.decode()
        assert request.headers["authorization"].startswith("Basic ")
        return httpx.Response(201, json={"sid": "CA123", "to": PHONE})

    sid = _client(handler).create_call(PHONE, CALLER, voice_twiml("Please call Linda."), timeout=25, machine_detection="DetectMessageEnd")
    assert sid == "CA123"
    assert seen["url"] == f"https://api.twilio.com/2010-04-01/Accounts/{SID_ACCOUNT}/Calls.json"
    form = dict(parse_qsl(seen["body"]))
    assert form["To"] == PHONE
    assert form["From"] == CALLER
    assert form["Timeout"] == "25"
    assert form["MachineDetection"] == "DetectMessageEnd"
    assert form["Twiml"].count("<Say>") == 2
    assert '<Pause length="1"/>' in form["Twiml"]
    assert "Please call Linda." in form["Twiml"]


def test_get_call_returns_only_status_and_answered_by():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/Calls/CA123.json")
        return httpx.Response(200, json={"status": "completed", "answered_by": "human", "to": PHONE, "from": CALLER})

    assert _client(handler).get_call("CA123") == {"status": "completed", "answered_by": "human"}


def test_missing_answered_by_is_null():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ringing"})

    assert _client(handler).get_call("CA1") == {"status": "ringing", "answered_by": None}


def test_twilio_errors_hide_the_number_and_the_token():
    def refuse(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"code": 21211, "message": f"bad {PHONE} token {TOKEN}"})

    with pytest.raises(TwilioError) as refused:
        _client(refuse).create_call(PHONE, CALLER, "<Response></Response>")
    text = str(refused.value)
    assert "HTTP 400" in text and "21211" in text
    assert PHONE not in text and TOKEN not in text and SID_ACCOUNT not in text

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dial failed")

    with pytest.raises(TwilioError) as unreachable:
        _client(down).get_call("CA1")
    assert "ConnectError" in str(unreachable.value)
    assert PHONE not in str(unreachable.value)


def test_replay_never_calls_twilio(caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("replay placed a call")

    client = _client(handler, DemoMode.replay)
    with caplog.at_level(logging.INFO):
        assert client.create_call(PHONE, CALLER, voice_twiml("Hi")) is None
        assert client.get_call("CA1") == {"status": "no-answer", "answered_by": None}
    assert PHONE not in caplog.text and TOKEN not in caplog.text and CALLER not in caplog.text


def test_call_logs_do_not_include_numbers(caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/Calls.json"):
            return httpx.Response(201, json={"sid": "CA9"})
        return httpx.Response(200, json={"status": "busy", "answered_by": None, "to": PHONE})

    client = _client(handler)
    with caplog.at_level(logging.INFO, logger="app.integrations.twilio"):
        assert client.create_call(PHONE, CALLER, voice_twiml("Hi")) == "CA9"
        client.get_call("CA9")
    assert PHONE not in caplog.text and CALLER not in caplog.text and TOKEN not in caplog.text
