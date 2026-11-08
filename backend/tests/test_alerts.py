"""Trusted-contact call and email (L16). Fake Twilio, no network."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from datetime import datetime, timezone

import pytest

from app import alerts, trusted_contact
from app.alerts import classify_call
from app.audit import AuditLog
from app.config import SettingsError, validate_settings
from app.contracts import AgentMode, MessageIn
from app.integrations.email_alert import EmailAlertError
from app.integrations.twilio import TwilioClient, TwilioError
from app.state import StateStore
from tests.conftest import make_settings

PHONE = "+15125550199"
CALLER = "+15125550100"
EMAIL = "maya.trusted@example.com"
FROM = "alerts@example.com"
TOKEN = "twilio-auth-token-secret"
APP_PASSWORD = "gmail-app-password-secret"
ACCOUNT = "AC_test_account_sid"
MESSAGE = "Pay $900 at http://evil.test or call 512-555-0199 right now."
SECRETS = (PHONE, CALLER, EMAIL, FROM, TOKEN, APP_PASSWORD, ACCOUNT, "5125550199", "15125550199", "512-555-0199", "$900", "http://evil.test")
ALERT_KEYS = {
    "message_id", "state", "call_outcome", "email_sent", "simulated",
    "called_at", "email_sent_at", "alert_text", "detail",
}


def voice_settings(**overrides):
    base = dict(
        USE_MOCKS=True,
        DEMO_MODE="live",
        VOICE_ALERTS_ENABLED=True,
        TWILIO_ACCOUNT_SID=ACCOUNT,
        TWILIO_AUTH_TOKEN=TOKEN,
        TWILIO_FROM_NUMBER=CALLER,
        TRUSTED_CONTACT_PHONE=PHONE,
        ALERT_EMAIL_FROM=FROM,
        ALERT_EMAIL_APP_PASSWORD=APP_PASSWORD,
        TRUSTED_CONTACT_EMAIL=EMAIL,
        PHONE_HASH_SALT="salt-not-a-phone",
    )
    base.update(overrides)
    return make_settings(**base)


class ScriptTwilio:
    def __init__(self, steps: list[tuple[str, str | None]], fail: str | None = None) -> None:
        self.steps = steps
        self.fail = fail
        self.created: list[dict] = []
        self.reads = 0

    def create_call(self, to, from_, twiml, timeout=25, machine_detection="DetectMessageEnd"):
        self.created.append({
            "to": to, "from": from_, "twiml": twiml, "timeout": timeout, "machine_detection": machine_detection,
        })
        if self.fail == "create":
            raise TwilioError("Twilio unreachable (ConnectError)")
        return "CA_test_sid"

    def get_call(self, sid):
        assert sid == "CA_test_sid"
        if self.fail == "poll":
            raise TwilioError("Twilio refused the call lookup (HTTP 500, code n/a)")
        status, who = self.steps[min(self.reads, len(self.steps) - 1)]
        self.reads += 1
        return {"status": status, "answered_by": who}


def _run(steps, *, fail=None, email_error=False, settings=None, store=None, audit=None, message_id="msg_alert", **kwargs):
    alerts.clear()
    twilio = ScriptTwilio(steps, fail=fail)
    emails: list[tuple[str, datetime]] = []

    def send(text, called_at):
        if email_error:
            raise EmailAlertError("email could not be sent (SMTPException)")
        emails.append((text, called_at))

    status = alerts.start_alert(
        message_id, "user-1",
        settings=settings or voice_settings(),
        store=store, audit=audit, twilio=twilio, send_email=send,
        poll_interval=kwargs.pop("poll_interval", 0.01),
        poll_timeout=kwargs.pop("poll_timeout", 0.25),
        simulate_delay=kwargs.pop("simulate_delay", 0.05),
        **kwargs,
    )
    final = alerts.wait_alert(message_id, timeout=2)
    return status, final, twilio, emails


def test_classify_call_outcomes():
    assert classify_call("completed", "human") == "answered"
    assert classify_call("completed", "machine_end_beep") == "voicemail"
    assert classify_call("in-progress", "machine_end_silence") == "voicemail"
    assert classify_call("busy", None) == "no_answer"
    assert classify_call("no-answer", None) == "no_answer"
    assert classify_call("canceled", None) == "no_answer"
    assert classify_call("failed", None) == "failed"
    assert classify_call("completed", None) == "no_answer"
    assert classify_call("completed", "unknown") == "no_answer"
    assert classify_call("ringing", None) is None
    assert classify_call("in-progress", "human") is None


@pytest.mark.parametrize(
    "steps,outcome,emailed",
    [
        ([("completed", "human")], "answered", False),
        ([("ringing", None), ("completed", "human")], "answered", False),
        ([("completed", "machine_end_beep")], "voicemail", True),
        ([("in-progress", "machine_start")], "voicemail", True),
        ([("busy", None)], "no_answer", True),
        ([("no-answer", None)], "no_answer", True),
        ([("canceled", None)], "no_answer", True),
        ([("failed", None)], "failed", True),
        ([("completed", "fax")], "no_answer", True),
    ],
)
def test_every_call_outcome(steps, outcome, emailed):
    started, final, twilio, emails = _run(steps)
    assert started.state == "calling" and started.call_outcome is None and started.email_sent is False
    assert final is not None and final.state == "done"
    assert final.call_outcome == outcome
    assert final.email_sent is emailed
    assert final.simulated is False and final.detail is None
    assert final.called_at is not None
    assert (final.email_sent_at is not None) is emailed
    text = trusted_contact.alert_text("Linda", False)
    assert final.alert_text == text
    assert twilio.created[0]["twiml"].count(text) == 2
    assert '<Pause length="1"/>' in twilio.created[0]["twiml"]
    assert twilio.created[0]["to"] == PHONE and twilio.created[0]["machine_detection"] == "DetectMessageEnd"
    if emailed:
        assert emails == [(text, final.called_at)] or emails[0][0] == text
    else:
        assert emails == []


def test_ringing_until_the_poll_times_out_counts_as_no_answer():
    _, final, twilio, emails = _run([("ringing", None)], poll_timeout=0.05, poll_interval=0.01)
    assert final.call_outcome == "no_answer" and final.email_sent is True
    assert twilio.reads >= 2 and emails


def test_still_talking_to_a_person_when_the_poll_ends_is_answered():
    _, final, _, emails = _run([("in-progress", "human")], poll_timeout=0.05, poll_interval=0.01)
    assert final.call_outcome == "answered" and emails == []


def test_twilio_errors_fail_and_still_email():
    for fail in ("create", "poll"):
        _, final, _, emails = _run([("completed", "human")], fail=fail)
        assert final.call_outcome == "failed" and final.email_sent is True and final.state == "done"
        assert emails and final.detail is None


def test_email_error_sets_detail_and_email_sent_false():
    _, final, _, emails = _run([("busy", None)], email_error=True)
    assert final.call_outcome == "no_answer"
    assert final.email_sent is False and final.email_sent_at is None
    assert final.detail == "The email could not be sent."
    assert emails == []


def test_cooldown_returns_the_existing_alert():
    clock = {"t": 1_000.0}
    alerts.clear()
    twilio = ScriptTwilio([("no-answer", None)])
    emails: list = []

    def send(text, called_at):
        emails.append(text)

    kwargs = dict(
        settings=voice_settings(), twilio=twilio, send_email=send,
        poll_interval=0.01, poll_timeout=0.2, clock=lambda: clock["t"],
    )
    first = alerts.start_alert("msg_cool", "user-1", **kwargs)
    assert first.state == "calling"
    done = alerts.wait_alert("msg_cool", timeout=2)
    assert done.call_outcome == "no_answer" and len(twilio.created) == 1
    again = alerts.start_alert("msg_cool", "user-1", **kwargs)
    assert again.state == "done" and again.call_outcome == "no_answer"
    assert len(twilio.created) == 1
    clock["t"] = 1_061.0
    third = alerts.start_alert("msg_cool", "user-1", **kwargs)
    assert third.state == "calling"
    alerts.wait_alert("msg_cool", timeout=2)
    assert len(twilio.created) == 2


@pytest.mark.parametrize("overrides", [{"VOICE_ALERTS_ENABLED": False}, {"VOICE_ALERTS_ENABLED": True, "DEMO_MODE": "replay"}])
def test_flag_off_and_replay_simulate_without_calling_or_emailing(overrides):
    started, final, twilio, emails = _run(
        [("completed", "human")], settings=voice_settings(**overrides), simulate_delay=0.05,
    )
    assert started.state == "calling" and started.simulated is True
    assert final.state == "done" and final.call_outcome == "no_answer"
    assert final.email_sent is True and final.simulated is True
    assert final.called_at is not None and final.email_sent_at is not None
    assert twilio.created == [] and emails == []


def test_nothing_sensitive_is_logged_stored_or_audited(caplog):
    store = StateStore()
    when = datetime(2026, 11, 8, 15, 0, tzinfo=timezone.utc)
    store.add_message(MessageIn(text=MESSAGE, sender="611611", received_at=when), message_id="msg_priv")
    store.start_run("msg_priv", AgentMode.recovery)
    audit = AuditLog(sqlite3.connect(":memory:", check_same_thread=False))
    with caplog.at_level(logging.DEBUG):
        _, final, twilio, emails = _run(
            [("completed", "machine_end_other")], store=store, audit=audit, message_id="msg_priv",
        )
    assert twilio.created[0]["to"] == PHONE
    assert "shared details" in final.alert_text
    assert "http" not in final.alert_text and "$" not in final.alert_text and "512" not in final.alert_text
    blob = caplog.text + final.model_dump_json() + twilio.created[0]["twiml"] + emails[0][0]
    privacy = store.privacy("msg_priv")
    blob += json.dumps([item.model_dump(mode="json") for item in privacy])
    rows = audit.recent()
    blob += json.dumps([{"event": row.event, "actor": row.actor, "target": row.target, "details": row.details} for row in rows])
    for secret in SECRETS:
        assert secret not in blob
    recipients = {item.recipient for item in privacy}
    assert recipients == {"twilio", "gmail"}
    for item in privacy:
        assert item.payload["alert_text"] == final.alert_text
        assert item.payload["to_hmac"] and PHONE not in item.payload["to_hmac"] and "@" not in item.payload["to_hmac"]
    assert rows[0].event == "alert.trusted_contact" and rows[0].outcome == "success"
    assert rows[0].details == {"call": "voicemail", "email": True, "simulated": False}


def test_response_shape_matches_the_interface(make_client, monkeypatch):
    monkeypatch.setattr(alerts, "SIMULATE_DELAY_S", 0.05)
    alerts.clear()
    trusted_contact.clear()
    client = make_client()
    assert client.get("/api/trusted-contact/alerts/msg_0001").status_code == 404
    other = client.post("/api/actions", json={"message_id": "msg_0001", "action": "block_sender"}).json()
    assert set(other) == {"message_id", "action", "status", "note"}
    assert "alert" not in other
    saved = client.put("/api/trusted-contact", json={"name": "Maya", "phone": "+15125554471"}).json()
    assert saved["contact"]["phone_masked"] == "•••• 4471"
    body = client.post("/api/actions", json={"message_id": "msg_shape", "action": "alert_trusted_contact"}).json()
    assert set(body) == {"message_id", "action", "status", "note", "alert"}
    assert body["status"] == "simulated" and body["action"] == "alert_trusted_contact"
    assert "Maya" in body["note"] and "15125554471" not in body["note"]
    alert = body["alert"]
    assert set(alert) == ALERT_KEYS
    assert alert["state"] == "calling" and alert["call_outcome"] is None and alert["simulated"] is True
    assert alert["email_sent"] is False and alert["detail"] is None
    assert alert["alert_text"] == trusted_contact.alert_text("Linda", False)
    got = {}
    for _ in range(50):
        got = client.get("/api/trusted-contact/alerts/msg_shape").json()
        if got["state"] == "done":
            break
        time.sleep(0.02)
    assert set(got) == ALERT_KEYS
    assert got["state"] == "done" and got["call_outcome"] == "no_answer"
    assert got["email_sent"] is True and got["simulated"] is True
    datetime.fromisoformat(got["called_at"])
    datetime.fromisoformat(got["email_sent_at"])
    assert "15125554471" not in json.dumps(got) and "http" not in got["alert_text"]


def test_live_route_uses_twilio_and_gmail_without_logging_them(make_client, monkeypatch, caplog):
    created: list[dict] = []
    sent: list[dict] = []

    def create_call(self, to, from_, twiml, timeout=25, machine_detection="DetectMessageEnd"):
        created.append({"to": to, "from": from_, "twiml": twiml, "timeout": timeout, "machine_detection": machine_detection})
        return "CA_route"

    def get_call(self, sid):
        return {"status": "busy", "answered_by": None}

    def send_alert_email(alert_text, called_at, **kwargs):
        sent.append({"text": alert_text, **kwargs})

    monkeypatch.setattr(TwilioClient, "create_call", create_call)
    monkeypatch.setattr(TwilioClient, "get_call", get_call)
    monkeypatch.setattr("app.alerts.send_alert_email", send_alert_email)
    alerts.clear()
    client = make_client(**{
        "VOICE_ALERTS_ENABLED": True,
        "TWILIO_ACCOUNT_SID": ACCOUNT,
        "TWILIO_AUTH_TOKEN": TOKEN,
        "TWILIO_FROM_NUMBER": CALLER,
        "TRUSTED_CONTACT_PHONE": PHONE,
        "ALERT_EMAIL_FROM": FROM,
        "ALERT_EMAIL_APP_PASSWORD": APP_PASSWORD,
        "TRUSTED_CONTACT_EMAIL": EMAIL,
        "PHONE_HASH_SALT": "salt-not-a-phone",
    })
    with caplog.at_level(logging.DEBUG):
        body = client.post("/api/actions", json={"message_id": "msg_live", "action": "alert_trusted_contact"}).json()
        assert body["alert"]["state"] == "calling" and body["alert"]["simulated"] is False
        final = alerts.wait_alert("msg_live", timeout=2)
    assert final.call_outcome == "no_answer" and final.email_sent is True
    assert created[0]["to"] == PHONE and created[0]["from"] == CALLER
    assert created[0]["timeout"] == 25 and created[0]["machine_detection"] == "DetectMessageEnd"
    assert sent[0]["mail_to"] == EMAIL and sent[0]["mail_from"] == FROM and sent[0]["app_password"] == APP_PASSWORD
    assert sent[0]["text"] == final.alert_text
    assert created[0]["twiml"].count(final.alert_text) == 2
    for secret in SECRETS:
        assert secret not in caplog.text
    shown = client.get("/api/trusted-contact/alerts/msg_live").json()
    assert shown["call_outcome"] == "no_answer" and shown["email_sent"] is True


def test_voice_flag_lists_every_missing_setting_and_replay_only_warns():
    with pytest.raises(SettingsError) as exc:
        validate_settings(make_settings(VOICE_ALERTS_ENABLED=True, DEMO_MODE="live", USE_MOCKS=True))
    message = str(exc.value)
    for name in (
        "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER", "TRUSTED_CONTACT_PHONE",
        "ALERT_EMAIL_FROM", "ALERT_EMAIL_APP_PASSWORD", "TRUSTED_CONTACT_EMAIL",
    ):
        assert name in message
    assert TOKEN not in message and "VOICE_ALERTS_ENABLED=false" in message
    warnings = validate_settings(make_settings(VOICE_ALERTS_ENABLED=True, DEMO_MODE="replay", USE_MOCKS=False, PHONE_HASH_SALT="s"))
    assert {item.variable for item in warnings} >= {"TRUSTED_CONTACT_PHONE", "ALERT_EMAIL_FROM", "TRUSTED_CONTACT_EMAIL"}
    assert all(item.level == "warning" for item in warnings)
    quiet = validate_settings(voice_settings(PUBLIC_BASE_URL="https://example.test", SMS_ALLOWED_NUMBERS="+15125550100"))
    assert "TRUSTED_CONTACT_PHONE" not in {item.variable for item in quiet}


def test_constants_match_the_spec():
    assert alerts.POLL_INTERVAL_S == 2
    assert alerts.POLL_TIMEOUT_S == 90
    assert alerts.COOLDOWN_S == 60
    assert alerts.SIMULATE_DELAY_S == 3
