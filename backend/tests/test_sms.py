"""SMS by Twilio (L14): the conversation, and every way it must fail closed."""

from __future__ import annotations

import logging
import time
from datetime import datetime
from urllib.parse import urlencode

import httpx
import pytest
from fastapi.testclient import TestClient

from app import contracts as c
from app.integrations.twilio import TwilioClient, expected_signature
from app.sms import FAILED, NO_MESSAGE, SmsService
from tests.conftest import make_settings

TOKEN = "test-auth-token"
BASE = "https://sentinel-demo.trycloudflare.com"
URL = f"{BASE}/api/sms/inbound"
PHONE = "+15125550142"
STRANGER = "+15125550999"

SCAM_TEXT = "Capital One Alert: unusual sign-in. Your account will be locked in 2 hours. Verify now: capone-verify-alert.com"
CHECK = c.AgentResult(
    plan=[c.ToolName.check_link],
    verdict=c.Verdict.likely_scam,
    confidence_words=c.ConfidenceWords.very_likely,
    reason="It asks you to verify on capone-verify-alert.com, a site made 3 days ago, or call 512-555-0199.",
    actions=[c.Action.block_sender],
)
RECOVERY = CHECK.model_copy(update={"was_this_you": ["txn_28"], "actions": [c.Action.freeze_card, c.Action.call_number_on_card]})


def detail(ref="txn_28"):
    return c.WasThisYouItem(ref=ref, type="purchase", amount=900, payee="Unknown Payee",
                            at=datetime.fromisoformat("2030-01-01T09:31:00+00:00"))


class FakeTwilio:
    def __init__(self, status: int = 201):
        self.sent: list[dict[str, str]] = []
        self.status = status

    def handler(self, request: httpx.Request) -> httpx.Response:
        from urllib.parse import parse_qsl

        self.sent.append(dict(parse_qsl(request.content.decode())))
        return httpx.Response(self.status, json={"sid": "SM123"} if self.status < 300 else {"code": 21608})

    def wait(self, n: int, timeout: float = 5.0) -> list[str]:
        end = time.monotonic() + timeout
        while len(self.sent) < n and time.monotonic() < end:
            time.sleep(0.02)
        return [m["Body"] for m in self.sent]


@pytest.fixture
def sms_app(monkeypatch):
    """`make(job=..., status=..., demo_mode=...)` → (client, fake_twilio, sms_service)."""
    from app import main
    from app.main import _reset_state, create_app
    from app.tools import nessie_tools

    monkeypatch.setattr(nessie_tools, "resolve_ref", lambda ref: detail(ref))
    clients = []

    def make(job=None, status: int = 201, demo_mode: c.DemoMode = c.DemoMode.live, timeout_s: float = 5.0):
        def default_job(mid, message, trail):
            return RECOVERY if message.mode == c.AgentMode.recovery else CHECK

        monkeypatch.setattr(main, "pipeline_job", job or default_job)
        _reset_state()
        twilio = FakeTwilio(status)
        client_obj = TwilioClient("AC123", TOKEN, "+15125550100", demo_mode, transport=httpx.MockTransport(twilio.handler))
        sms = SmsService(client=client_obj, public_base_url=BASE, phone_salt="test-salt",
                         allowed=frozenset({PHONE}), timeout_s=timeout_s)
        settings = make_settings(
            AUTH_ENABLED=False, DEMO_MODE="replay", PHONE_HASH_SALT="test-salt",
            TWILIO_ACCOUNT_SID="AC123", TWILIO_AUTH_TOKEN=TOKEN, TWILIO_FROM_NUMBER="+15125550100",
            PUBLIC_BASE_URL=BASE, SMS_ALLOWED_NUMBERS=PHONE,
        )
        client = TestClient(create_app(settings, sms_service=sms))
        clients.append(client)
        return client, twilio, sms

    yield make
    for client in clients:
        client.close()
    _reset_state()


def text(client, body: str, sender: str = PHONE, signature: str | None = None):
    params = {"From": sender, "To": "+15125550100", "Body": body, "MessageSid": "SMabc"}
    sig = signature if signature is not None else expected_signature(TOKEN, URL, params)
    return client.post(
        "/api/sms/inbound",
        content=urlencode(params),
        headers={"Content-Type": "application/x-www-form-urlencoded", "X-Twilio-Signature": sig},
    )


def sms_messages(client) -> list:
    return [i for i in client.app.state.store.inbox() if i.source == c.MessageSource.sms]


# ---------------------------------------------------------------------------
# Who may call it
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("signature", ["", "bm90IHRoZSByaWdodCBvbmU="])
def test_missing_or_wrong_signature_is_refused_and_nothing_runs(sms_app, signature):
    client, twilio, _ = sms_app()
    r = text(client, SCAM_TEXT, signature=signature)
    assert r.status_code == 403
    assert sms_messages(client) == [] and twilio.sent == []


def test_signature_for_a_different_body_is_refused(sms_app):
    client, twilio, _ = sms_app()
    forged = expected_signature(TOKEN, URL, {"From": PHONE, "To": "+15125550100", "Body": "hi", "MessageSid": "SMabc"})
    assert text(client, SCAM_TEXT, signature=forged).status_code == 403


def test_numbers_not_on_the_allow_list_get_no_reply(sms_app):
    client, twilio, _ = sms_app()
    r = text(client, SCAM_TEXT, sender=STRANGER)
    assert r.status_code == 200 and "<Message>" not in r.text
    assert sms_messages(client) == [] and twilio.sent == []


def test_per_number_rate_limit(sms_app):
    client, _, sms = sms_app()
    sms.limiter.per_minute = 2
    replies = [text(client, "HELP").text for _ in range(3)]
    assert "<Message>" in replies[0] and "<Message>" in replies[1] and "<Message>" not in replies[2]


# ---------------------------------------------------------------------------
# The conversation
# ---------------------------------------------------------------------------


def test_text_gets_an_ack_then_a_verdict_without_the_scam_link_or_number(sms_app):
    client, twilio, _ = sms_app()
    r = text(client, SCAM_TEXT)
    assert r.status_code == 200 and "Checking this now" in r.text
    [verdict] = twilio.wait(1)
    mid = sms_messages(client)[0].message_id
    assert verdict.startswith("SentinelAI: Very likely a scam.")
    assert f"{BASE}/r/{mid}" in verdict and "Reply CLICKED" in verdict
    assert "capone-verify-alert" not in verdict and "555-0199" not in verdict  # scam's own link and number stripped
    assert twilio.sent[0]["To"] == PHONE


def test_from_line_sets_the_claimed_sender(sms_app):
    client, twilio, _ = sms_app()
    text(client, f"From: 227898\n{SCAM_TEXT}")
    twilio.wait(1)
    stored = client.app.state.store.get_message(sms_messages(client)[0].message_id)
    assert stored.sender == "227898" and stored.text == SCAM_TEXT


def test_clicked_runs_recovery_then_was_this_you_then_checklist(sms_app):
    client, twilio, _ = sms_app()
    text(client, SCAM_TEXT)
    twilio.wait(1)
    r = text(client, "clicked")
    assert "Checking your recent account activity" in r.text
    bodies = twilio.wait(2)
    assert "$900.00 purchase at Unknown Payee" in bodies[1] and "Reply NO or YES" in bodies[1]
    no = text(client, "NO")
    assert "Review your card controls" in no.text and "number on the back of your card" in no.text
    assert client.app.state.store._db.execute("SELECT was_me FROM confirmations").fetchone()[0] == 0


def test_yes_is_recorded_and_thanked(sms_app):
    client, twilio, _ = sms_app()
    text(client, SCAM_TEXT)
    twilio.wait(1)
    text(client, "CLICKED")
    twilio.wait(2)
    assert "Thanks for confirming" in text(client, "yes").text
    assert client.app.state.store._db.execute("SELECT was_me FROM confirmations").fetchone()[0] == 1


@pytest.mark.parametrize("command", ["CLICKED", "BLOCK", "YES"])
def test_commands_before_any_message_get_guidance_not_errors(sms_app, command):
    client, twilio, _ = sms_app()
    r = text(client, command)
    assert r.status_code == 200 and "SentinelAI:" in r.text
    if command != "YES":
        assert "Send us the message" in r.text
    assert sms_messages(client) == []


def test_block_is_simulated(sms_app):
    client, twilio, _ = sms_app()
    text(client, SCAM_TEXT)
    twilio.wait(1)
    assert "simulated for the demo" in text(client, "BLOCK").text


# ---------------------------------------------------------------------------
# Failures
# ---------------------------------------------------------------------------


def test_crashing_check_sends_the_honest_failure_text(sms_app):
    def boom(mid, message, trail):
        raise RuntimeError("nemotron down")

    client, twilio, _ = sms_app(job=boom)
    text(client, SCAM_TEXT)
    [body] = twilio.wait(1)
    assert "couldn't finish" in body and "don't tap" in body.lower()  # the runner stores an honest failure result


def test_slow_check_times_out_with_the_failure_text(sms_app):
    def slow(mid, message, trail):
        time.sleep(1.0)
        return CHECK

    client, twilio, _ = sms_app(job=slow, timeout_s=0.2)
    text(client, SCAM_TEXT)
    assert twilio.wait(1) == [FAILED.text]


def test_twilio_refusing_the_send_is_logged_without_number_or_text(sms_app, caplog):
    client, twilio, _ = sms_app(status=400)
    with caplog.at_level(logging.INFO):
        assert text(client, SCAM_TEXT).status_code == 200
        twilio.wait(1)
        time.sleep(0.1)
    logs = "\n".join(r.getMessage() + str(getattr(r, "fields", "")) for r in caplog.records)
    assert "Twilio refused" in logs
    assert PHONE not in logs and "5125550142" not in logs and "capone-verify" not in logs


def test_raw_phone_number_is_never_stored(sms_app):
    client, twilio, _ = sms_app()
    text(client, SCAM_TEXT)
    twilio.wait(1)
    db = client.app.state.store._db
    dump = "\n".join(str(tuple(row)) for t in ("messages", "trail", "privacy", "redaction") for row in db.execute(f"SELECT * FROM {t}"))
    assert PHONE not in dump and "5125550142" not in dump


def test_replay_mode_sends_nothing(sms_app):
    client, twilio, _ = sms_app(demo_mode=c.DemoMode.replay)
    assert "Checking this now" in text(client, SCAM_TEXT).text
    time.sleep(0.3)
    assert twilio.sent == []


def test_long_body_is_capped(sms_app):
    client, twilio, _ = sms_app()
    text(client, "A" * 5000)
    twilio.wait(1)
    assert len(client.app.state.store.get_message(sms_messages(client)[0].message_id).text) <= 1600


def test_sms_route_is_absent_without_twilio_settings(client):
    assert client.post("/api/sms/inbound", content="Body=hi").status_code in (403, 404, 405)
