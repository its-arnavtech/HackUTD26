"""L16 trial-account calls: To/From/Url only, and the signed TwiML route. No network."""

from __future__ import annotations

from urllib.parse import parse_qsl

import httpx
import pytest

from app import alerts
from app.alerts import classify_trial_call
from app.contracts import DemoMode
from app.integrations.twilio import TwilioClient, expected_signature
from tests.test_alerts import ACCOUNT, CALLER, PHONE, TOKEN, ScriptTwilio, voice_settings

BASE = "https://unit-test.trycloudflare.com"


class TrialTwilio(ScriptTwilio):
    """Records create_call_url; create_call (inline TwiML) must never be used in trial mode."""

    def __init__(self, steps, fail=None):
        super().__init__(steps, fail=fail)
        self.urls: list[dict] = []

    def create_call(self, *args, **kwargs):  # pragma: no cover - failing here is the assertion
        raise AssertionError("trial mode must not send inline Twiml")

    def create_call_url(self, to, from_, url):
        self.urls.append({"to": to, "from": from_, "url": url})
        return "CA_test_sid"


def _run_trial(steps, settings, email_error=True):
    alerts.clear()
    twilio = TrialTwilio(steps)
    sent: list[str] = []

    def send(text, called_at):
        if email_error:
            from app.integrations.email_alert import EmailAlertError

            raise EmailAlertError("email is not configured")
        sent.append(text)

    alerts.start_alert("msg_trial", "user-1", settings=settings, twilio=twilio, send_email=send,
                       poll_interval=0.01, poll_timeout=0.3)
    return alerts.wait_alert("msg_trial", timeout=2), twilio


def test_classify_trial_call():
    assert classify_trial_call("completed") == "answered"
    for status in ("busy", "no-answer", "failed", "canceled"):
        assert classify_trial_call(status) == "no_answer"
    assert classify_trial_call("ringing") is None
    assert classify_trial_call("in-progress") is None


def test_trial_client_sends_only_to_from_and_url():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(parse_qsl(request.content.decode())))
        return httpx.Response(201, json={"sid": "CA1"})

    client = TwilioClient(ACCOUNT, TOKEN, CALLER, DemoMode.live, transport=httpx.MockTransport(handler))
    assert client.create_call_url(PHONE, CALLER, f"{BASE}/api/voice/twiml/abc") == "CA1"
    assert set(seen) == {"To", "From", "Url"}


def test_trial_answered_uses_url_with_a_fresh_token():
    final, twilio = _run_trial([("ringing", None), ("in-progress", None), ("completed", None)],
                               voice_settings(TWILIO_TRIAL_MODE=True, PUBLIC_BASE_URL=BASE + "/"))
    assert final.state == "done" and final.call_outcome == "answered"
    assert twilio.created == []
    (call,) = twilio.urls
    assert call["to"] == PHONE and call["from"] == CALLER
    prefix = f"{BASE}/api/voice/twiml/"
    assert call["url"].startswith(prefix)
    assert len(call["url"][len(prefix):]) >= 43  # 32 random bytes, urlsafe base64


def test_trial_no_answer_shows_the_fallback():
    final, _ = _run_trial([("ringing", None), ("no-answer", None)],
                          voice_settings(TWILIO_TRIAL_MODE=True, PUBLIC_BASE_URL=BASE))
    assert final.call_outcome == "no_answer"
    assert final.email_sent is False


def test_trial_without_public_base_url_fails_fast_with_a_clear_detail():
    final, twilio = _run_trial([("completed", None)], voice_settings(TWILIO_TRIAL_MODE=True, PUBLIC_BASE_URL=""))
    assert final.call_outcome == "failed"
    assert "PUBLIC_BASE_URL" in (final.detail or "")
    assert twilio.urls == [] and twilio.created == []


def test_non_trial_still_sends_inline_twiml():
    alerts.clear()
    twilio = ScriptTwilio([("completed", "human")])
    alerts.start_alert("msg_live", "user-1", settings=voice_settings(), twilio=twilio,
                       send_email=lambda *_: None, poll_interval=0.01, poll_timeout=0.3)
    final = alerts.wait_alert("msg_live", timeout=2)
    assert final.call_outcome == "answered"
    assert twilio.created[0]["machine_detection"] == "DetectMessageEnd"
    assert twilio.created[0]["twiml"].startswith("<Response>")


def test_tokens_are_single_use_and_expire():
    alerts.clear()
    token = alerts.issue_twiml_token("Hi")
    assert alerts.consume_twiml_token(token) == "Hi"
    assert alerts.consume_twiml_token(token) is None
    clock = iter([100.0, 100.0 + alerts.TWIML_TOKEN_TTL_S + 1]).__next__
    old = alerts.issue_twiml_token("Hi", clock=clock)
    assert alerts.consume_twiml_token(old, clock=clock) is None


# --- the route -------------------------------------------------------------------------------------

@pytest.fixture
def voice_client(make_client):
    return make_client(TWILIO_AUTH_TOKEN=TOKEN, PUBLIC_BASE_URL=BASE)


def _signed(path: str, params: dict[str, str] | None = None) -> dict[str, str]:
    return {"X-Twilio-Signature": expected_signature(TOKEN, BASE + path, params or {})}


def test_valid_post_signature_returns_escaped_twiml_once(voice_client):
    token = alerts.issue_twiml_token('Call Linda <now> & say "hi"')
    path = f"/api/voice/twiml/{token}"
    form = {"CallSid": "CA1", "CallStatus": "in-progress"}
    r = voice_client.post(path, data=form, headers=_signed(path, form))
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/xml")
    assert "<Say>Call Linda &lt;now&gt; &amp; say \"hi\"</Say><Pause length=\"1\"/><Say>" in r.text
    assert "<now>" not in r.text
    again = voice_client.post(path, data=form, headers=_signed(path, form))
    assert again.status_code == 404  # single use


def test_signature_over_the_url_with_port_443_is_accepted(voice_client):
    token = alerts.issue_twiml_token("Please call Linda.")
    path = f"/api/voice/twiml/{token}"
    form = {"CallSid": "CA1", "From": "+15125550100"}
    with_port = BASE.replace(".com", ".com:443") + path
    sig = expected_signature(TOKEN, with_port, form)
    assert voice_client.post(path, data=form, headers={"X-Twilio-Signature": sig}).status_code == 200


def test_tokens_never_reach_the_logs():
    from app.logs import redact_path

    line = '127.0.0.1 - "POST /api/voice/twiml/AbC_-123xyz HTTP/1.1" 403'
    assert "AbC_-123xyz" not in redact_path(line)
    assert "/api/voice/twiml/[redacted]" in redact_path(line)


def test_valid_get_signature_returns_twiml(voice_client):
    token = alerts.issue_twiml_token("Please call Linda.")
    path = f"/api/voice/twiml/{token}"
    r = voice_client.get(path, headers=_signed(path))
    assert r.status_code == 200 and r.text.count("<Say>Please call Linda.</Say>") == 2


def test_invalid_signature_is_403_and_keeps_the_token(voice_client):
    token = alerts.issue_twiml_token("Please call Linda.")
    path = f"/api/voice/twiml/{token}"
    assert voice_client.get(path, headers={"X-Twilio-Signature": "bogus"}).status_code == 403
    assert voice_client.get(path).status_code == 403
    form = {"CallSid": "CA1"}
    tampered = voice_client.post(path, data={"CallSid": "CA2"}, headers=_signed(path, form))
    assert tampered.status_code == 403
    assert voice_client.get(path, headers=_signed(path)).status_code == 200


def test_unknown_or_expired_token_is_404(voice_client):
    path = "/api/voice/twiml/not-a-real-token"
    assert voice_client.get(path, headers=_signed(path)).status_code == 404
    clock = iter([0.0]).__next__
    expired = alerts.issue_twiml_token("Hi", ttl=-1, clock=clock)
    path = f"/api/voice/twiml/{expired}"
    assert voice_client.get(path, headers=_signed(path)).status_code == 404


def test_signature_check_is_on_by_default():
    from tests.conftest import make_settings

    assert make_settings().TWILIO_VERIFY_SIGNATURE is True


def test_verify_off_skips_signature_but_still_needs_the_token(make_client):
    c = make_client(TWILIO_AUTH_TOKEN=TOKEN, PUBLIC_BASE_URL=BASE, TWILIO_VERIFY_SIGNATURE=False)
    token = alerts.issue_twiml_token("Please call Linda.")
    path = f"/api/voice/twiml/{token}"
    r = c.post(path, data={"CallSid": "CA1"}, headers={"X-Twilio-Signature": "bogus"})
    assert r.status_code == 200 and r.text.count("<Say>Please call Linda.</Say>") == 2
    assert c.post(path, data={"CallSid": "CA1"}).status_code == 404  # still single use
    assert c.get("/api/voice/twiml/not-a-real-token").status_code == 404


def test_verify_off_warns_at_startup():
    from app.config import validate_settings
    from tests.conftest import make_settings

    issues = validate_settings(make_settings(TWILIO_VERIFY_SIGNATURE=False))
    assert any(i.variable == "TWILIO_VERIFY_SIGNATURE" and i.level == "warning" for i in issues)
    assert not any(i.variable == "TWILIO_VERIFY_SIGNATURE" for i in validate_settings(make_settings()))


def test_failed_signature_logs_booleans_only(voice_client, caplog):
    token = alerts.issue_twiml_token("Please call Linda.")
    path = f"/api/voice/twiml/{token}"
    with caplog.at_level("INFO"):
        assert voice_client.post(path, data={"CallSid": "CA1"}, headers={"X-Twilio-Signature": "bogus"}).status_code == 403
    text = " ".join(str(getattr(r, "fields", "")) + r.getMessage() for r in caplog.records if r.name.startswith(("app", "uvicorn")))
    assert "signature diagnosis" in text
    assert token not in text and "bogus" not in text and TOKEN not in text


def test_route_refuses_when_public_base_url_is_unset(make_client):
    c = make_client(TWILIO_AUTH_TOKEN=TOKEN, PUBLIC_BASE_URL="")
    token = alerts.issue_twiml_token("Hi")
    path = f"/api/voice/twiml/{token}"
    assert c.get(path, headers=_signed(path)).status_code == 403
