"""WhatsApp Cloud API (Meta): verify webhooks and send replies (L14).

Free for this demo: Meta's test number can message up to 5 verified recipients,
and once the customer messages us first, we may reply with free-form text and
tap buttons for 24 hours (the "customer service window").

**Webhook security.** Meta signs every webhook POST with `X-Hub-Signature-256`
(`sha256=` + HMAC-SHA256 of the raw body, keyed with the app secret). Anything
without a valid signature is refused. The one-time GET subscription check must
echo `hub.challenge` only when `hub.verify_token` matches our own token.

**Why this doesn't go through `cache.cached_call`:** sending a message is an
action, not a lookup, and recording it would put phone numbers into committed
fixtures. `DEMO_MODE=replay` sends nothing.

Nothing here logs a phone number, a message body or a token.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any

import httpx

from app.contracts import DemoMode

log = logging.getLogger(__name__)

GRAPH = "https://graph.facebook.com"
TIMEOUT_S = 10.0
MAX_TEXT = 4096
MAX_BUTTON_BODY = 1024
MAX_BUTTON_TITLE = 20


class WhatsAppError(RuntimeError):
    """Sending failed. The message is safe to log (no number, body or token)."""


def verify_signature(app_secret: str, raw_body: bytes, header: str | None) -> bool:
    if not app_secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


class WhatsAppClient:
    def __init__(
        self,
        access_token: str,
        phone_number_id: str,
        graph_version: str,
        demo_mode: DemoMode,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.access_token = access_token
        self.phone_number_id = phone_number_id
        self.graph_version = graph_version
        self.demo_mode = demo_mode
        self._transport = transport

    def _post(self, payload: dict[str, Any]) -> str | None:
        if self.demo_mode == DemoMode.replay:
            log.info("whatsapp not sent (replay mode)")
            return None
        url = f"{GRAPH}/{self.graph_version}/{self.phone_number_id}/messages"
        try:
            with httpx.Client(timeout=TIMEOUT_S, transport=self._transport) as client:
                response = client.post(url, json=payload, headers={"Authorization": f"Bearer {self.access_token}"})
        except httpx.HTTPError as exc:
            raise WhatsAppError(f"WhatsApp unreachable ({type(exc).__name__})") from None
        if response.status_code >= 300:
            code = ""
            try:
                code = str(response.json().get("error", {}).get("code", ""))
            except ValueError:
                pass
            raise WhatsAppError(f"WhatsApp refused the message (HTTP {response.status_code}, code {code or 'n/a'})")
        log.info("whatsapp sent", extra={"fields": {"type": payload.get("type")}})
        messages = response.json().get("messages") or [{}]
        return messages[0].get("id")

    def send(self, to: str, text: str, buttons: tuple[tuple[str, str], ...] = ()) -> str | None:
        """Plain text, or text with up to 3 reply buttons (id, label)."""
        to = "".join(ch for ch in to if ch.isdigit())
        if not buttons:
            return self._post({"messaging_product": "whatsapp", "to": to, "type": "text",
                               "text": {"body": text[:MAX_TEXT], "preview_url": False}})
        return self._post({
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": text[:MAX_BUTTON_BODY]},
                "action": {"buttons": [
                    {"type": "reply", "reply": {"id": command, "title": label[:MAX_BUTTON_TITLE]}}
                    for command, label in buttons[:3]
                ]},
            },
        })
