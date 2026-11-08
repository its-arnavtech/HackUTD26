"""WhatsApp Cloud API (L14): webhook security, the conversation with buttons, and failures."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from datetime import datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from app import contracts as c
from app.integrations.whatsapp import WhatsAppClient
from app.whatsapp import WhatsAppService, inbound_messages
from tests.conftest import make_settings

SECRET = "test-app-secret"
VERIFY = "test-verify-token"
BASE = "https://sentinel-demo.lhr.life"
PHONE = "12144047631"  # WhatsApp sends numbers without "+"
STRANGER = "15125550999"

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


class FakeGraph:
    def __init__(self, status: int = 200):
        self.sent: list[dict] = []
        self.status = status
        self.auth: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.sent.append(json.loads(request.content))
        self.auth.append(request.headers.get("authorization", ""))
        if self.status >= 300:
            return httpx.Response(self.status, json={"error": {"code": 131030, "message": "Recipient not in allowed list"}})
        return httpx.Response(200, json={"messages": [{"id": "wamid.1"}]})

    def wait(self, n: int, timeout: float = 5.0) -> list[dict]:
        end = time.monotonic() + timeout
        while len(self.sent) < n and time.monotonic() < end:
            time.sleep(0.02)
        return self.sent

    @staticmethod
    def text_of(payload: dict) -> str:
        return payload["text"]["body"] if payload["type"] == "text" else payload["interactive"]["body"]["text"]

    @staticmethod
    def buttons_of(payload: dict) -> list[str]:
        if payload["type"] != "interactive":
            return []
        return [b["reply"]["id"] for b in payload["interactive"]["action"]["buttons"]]


@pytest.fixture
def wa_app(monkeypatch):
    from app import main
    from app.main import _reset_state, create_app
    from app.tools import nessie_tools

    monkeypatch.setattr(nessie_tools, "resolve_ref", lambda ref: detail(ref))
    clients = []

    def make(job=None, status: int = 200, demo_mode: c.DemoMode = c.DemoMode.live, timeout_s: float = 5.0):
        def default_job(mid, message, trail):
            return RECOVERY if message.mode == c.AgentMode.recovery else CHECK

        monkeypatch.setattr(main, "pipeline_job", job or default_job)
        _reset_state()
        graph = FakeGraph(status)
        wa = WhatsAppService(
            client=WhatsAppClient("EAAtoken", "1234567890", "v23.0", demo_mode, transport=httpx.MockTransport(graph.handler)),
            app_secret=SECRET, verify_token=VERIFY, public_base_url=BASE, phone_salt="test-salt",
            allowed=frozenset({"+" + PHONE}), timeout_s=timeout_s,
        )
        settings = make_settings(
            AUTH_ENABLED=False, DEMO_MODE="replay", PHONE_HASH_SALT="test-salt", PUBLIC_BASE_URL=BASE,
            WHATSAPP_ACCESS_TOKEN="EAAtoken", WHATSAPP_PHONE_NUMBER_ID="1234567890",
            WHATSAPP_APP_SECRET=SECRET, WHATSAPP_VERIFY_TOKEN=VERIFY,
        )
        client = TestClient(create_app(settings, whatsapp_service=wa))
        clients.append(client)
        return client, graph, wa

    yield make
    for client in clients:
        client.close()
    _reset_state()


def payload_text(body: str, sender: str = PHONE) -> dict:
    return {"object": "whatsapp_business_account", "entry": [{"changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp",
        "messages": [{"from": sender, "id": "wamid.in", "timestamp": "1", "type": "text", "text": {"body": body}}],
    }}]}]}


def payload_button(button_id: str, sender: str = PHONE) -> dict:
    return {"entry": [{"changes": [{"value": {"messages": [{
        "from": sender, "type": "interactive", "interactive": {"type": "button_reply", "button_reply": {"id": button_id, "title": "x"}},
    }]}}]}]}


def post(client, payload: dict, signature: str | None = None):
    raw = json.dumps(payload).encode()
    sig = signature if signature is not None else "sha256=" + hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return client.post("/api/whatsapp/webhook", content=raw, headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig})


def wa_messages(client) -> list:
    return [i for i in client.app.state.store.inbox() if i.source == c.MessageSource.sms]


# ---------------------------------------------------------------------------
# Webhook security
# ---------------------------------------------------------------------------


def test_subscription_check_echoes_challenge_only_for_our_token(wa_app):
    client, _, _ = wa_app()
    ok = client.get("/api/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": VERIFY, "hub.challenge": "12345"})
    assert ok.status_code == 200 and ok.text == "12345"
    bad = client.get("/api/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "guess", "hub.challenge": "12345"})
    assert bad.status_code == 403 and "12345" not in bad.text


@pytest.mark.parametrize("signature", ["", "sha256=deadbeef", "sha1=abc"])
def test_unsigned_or_forged_posts_are_refused(wa_app, signature):
    client, graph, _ = wa_app()
    assert post(client, payload_text(SCAM_TEXT), signature=signature).status_code == 403
    assert wa_messages(client) == [] and graph.sent == []


def test_signature_over_a_different_body_is_refused(wa_app):
    client, graph, _ = wa_app()
    other = json.dumps(payload_text("hello")).encode()
    sig = "sha256=" + hmac.new(SECRET.encode(), other, hashlib.sha256).hexdigest()
    assert post(client, payload_text(SCAM_TEXT), signature=sig).status_code == 403


def test_numbers_not_on_the_allow_list_get_nothing(wa_app):
    client, graph, _ = wa_app()
    assert post(client, payload_text(SCAM_TEXT, sender=STRANGER)).status_code == 200
    assert wa_messages(client) == [] and graph.sent == []


def test_status_updates_and_junk_are_acknowledged_and_ignored(wa_app):
    client, graph, _ = wa_app()
    status_only = {"entry": [{"changes": [{"value": {"statuses": [{"status": "delivered"}]}}]}]}
    assert post(client, status_only).status_code == 200
    raw = b"not json"
    sig = "sha256=" + hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    assert client.post("/api/whatsapp/webhook", content=raw, headers={"X-Hub-Signature-256": sig}).status_code == 200
    assert graph.sent == []


# ---------------------------------------------------------------------------
# The conversation
# ---------------------------------------------------------------------------


def test_message_gets_ack_then_verdict_with_buttons_and_no_scam_link(wa_app):
    client, graph, _ = wa_app()
    assert post(client, payload_text(SCAM_TEXT)).status_code == 200
    sent = graph.wait(2)
    assert "Checking this now" in FakeGraph.text_of(sent[0])
    verdict = FakeGraph.text_of(sent[1])
    mid = wa_messages(client)[0].message_id
    assert verdict.startswith("SentinelAI: Very likely a scam.") and f"{BASE}/r/{mid}" in verdict
    assert "capone-verify-alert" not in verdict and "555-0199" not in verdict
    assert FakeGraph.buttons_of(sent[1]) == ["CLICKED", "BLOCK"]
    assert sent[1]["to"] == PHONE and graph.auth[1] == "Bearer EAAtoken"


def test_buttons_drive_recovery_was_this_you_and_checklist(wa_app):
    client, graph, _ = wa_app()
    post(client, payload_text(SCAM_TEXT))
    graph.wait(2)
    post(client, payload_button("CLICKED"))
    sent = graph.wait(4)
    assert "Checking your recent account activity" in FakeGraph.text_of(sent[2])
    assert "$900.00 purchase at Unknown Payee" in FakeGraph.text_of(sent[3])
    assert FakeGraph.buttons_of(sent[3]) == ["NO", "YES"]
    post(client, payload_button("NO"))
    sent = graph.wait(5)
    assert "number on the back of your card" in FakeGraph.text_of(sent[4])
    assert client.app.state.store._db.execute("SELECT was_me FROM confirmations").fetchone()[0] == 0


def test_typed_commands_work_like_buttons(wa_app):
    client, graph, _ = wa_app()
    post(client, payload_text(SCAM_TEXT))
    graph.wait(2)
    post(client, payload_text("block"))
    assert "simulated for the demo" in FakeGraph.text_of(graph.wait(3)[2])


def test_inbound_parser_handles_text_buttons_and_ignores_the_rest():
    assert inbound_messages(payload_text("hi")) == [(PHONE, "hi")]
    assert inbound_messages(payload_button("YES")) == [(PHONE, "YES")]
    assert inbound_messages({"entry": [{"changes": [{"value": {"messages": [{"from": PHONE, "type": "image"}]}}]}]}) == []
    assert inbound_messages({}) == []


# ---------------------------------------------------------------------------
# Failures
# ---------------------------------------------------------------------------


def test_slow_check_sends_the_honest_failure(wa_app):
    def slow(mid, message, trail):
        time.sleep(1.0)
        return CHECK

    client, graph, _ = wa_app(job=slow, timeout_s=0.2)
    post(client, payload_text(SCAM_TEXT))
    assert "couldn't finish" in FakeGraph.text_of(graph.wait(2)[1])


def test_meta_refusing_is_logged_without_number_text_or_token(wa_app, caplog):
    client, graph, _ = wa_app(status=400)
    with caplog.at_level(logging.INFO):
        assert post(client, payload_text(SCAM_TEXT)).status_code == 200
        graph.wait(2)
        time.sleep(0.1)
    logs = "\n".join(r.getMessage() for r in caplog.records)
    assert "WhatsApp refused" in logs
    for secret in (PHONE, "EAAtoken", "capone-verify"):
        assert secret not in logs


def test_raw_number_never_stored(wa_app):
    client, graph, _ = wa_app()
    post(client, payload_text(SCAM_TEXT))
    graph.wait(2)
    db = client.app.state.store._db
    dump = "\n".join(str(tuple(r)) for t in ("messages", "trail", "privacy", "redaction") for r in db.execute(f"SELECT * FROM {t}"))
    assert PHONE not in dump


def test_replay_mode_sends_nothing(wa_app):
    client, graph, _ = wa_app(demo_mode=c.DemoMode.replay)
    post(client, payload_text(SCAM_TEXT))
    time.sleep(0.3)
    assert graph.sent == []


def test_webhook_absent_without_whatsapp_settings(client):
    assert client.get("/api/whatsapp/webhook").status_code in (403, 404, 405)
