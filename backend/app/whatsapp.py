"""SentinelAI on WhatsApp: `GET|POST /api/whatsapp/webhook` (L14, DATA_SPEC section 9).

The free way to talk to SentinelAI from a real phone. Forward or paste a
suspicious message to the SentinelAI WhatsApp test number; it answers "Checking
this now…", then the verdict with tap buttons (**I tapped the link**, **Block
sender**), then "Was this you?" with **No, not me** / **Yes, that was me**.

The conversation is shared with SMS (`app/messaging.py`). This module only
handles Meta's webhook: the one-time subscription check (GET) and signed message
events (POST). Replies always go out through the Graph API (Meta's webhook has
no inline reply), from a background thread, so the webhook answers 200 at once.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse, Response

from app.auth.deps import authorize
from app.errors import ForbiddenError
from app.integrations.whatsapp import WhatsAppClient, verify_signature
from app.messaging import Conversation, MessagingService, Reply, _audit

log = logging.getLogger(__name__)


@dataclass
class WhatsAppService(MessagingService):
    client: WhatsAppClient | None = None
    app_secret: str = ""
    verify_token: str = ""
    channel: str = "whatsapp"

    def deliver(self, conversation: Conversation, reply: Reply) -> None:
        assert self.client is not None
        self.client.send(conversation.number, reply.text, reply.buttons)


def inbound_messages(payload: dict[str, Any]) -> list[tuple[str, str]]:
    """`(from, text)` for each customer message in a webhook payload.

    Text messages give their body; a tap on one of our buttons gives the
    button's id (CLICKED, BLOCK, YES, NO). Status updates (sent, delivered,
    read) and anything else are ignored.
    """
    found: list[tuple[str, str]] = []
    for entry in payload.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            value = change.get("value", {}) or {}
            for message in value.get("messages", []) or []:
                sender = str(message.get("from", ""))
                kind = message.get("type")
                if kind == "text":
                    found.append((sender, str(message.get("text", {}).get("body", ""))))
                elif kind == "interactive":
                    reply = message.get("interactive", {}).get("button_reply", {}) or {}
                    found.append((sender, str(reply.get("id", ""))))
                elif kind == "button":  # quick-reply on a template
                    found.append((sender, str(message.get("button", {}).get("payload", ""))))
    return found


router = APIRouter(prefix="/api", dependencies=[Depends(authorize)])


@router.get("/whatsapp/webhook")
def whatsapp_verify(request: Request) -> Response:
    """Meta's one-time subscription check: echo the challenge only for our verify token."""
    wa: WhatsAppService = request.app.state.whatsapp
    params = request.query_params
    if params.get("hub.mode") == "subscribe" and wa.verify_token and params.get("hub.verify_token") == wa.verify_token:
        return PlainTextResponse(params.get("hub.challenge", ""))
    _audit(request, "whatsapp.bad_verify_token", "anonymous", outcome="denied")
    raise ForbiddenError("Verification failed")


@router.post("/whatsapp/webhook")
async def whatsapp_inbound(request: Request) -> Response:
    wa: WhatsAppService = request.app.state.whatsapp
    raw = await request.body()
    if not verify_signature(wa.app_secret, raw, request.headers.get("x-hub-signature-256")):
        _audit(request, "whatsapp.bad_signature", "anonymous", outcome="denied")
        raise ForbiddenError("Invalid webhook signature")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return Response(status_code=200)  # acknowledged; nothing we can act on
    for sender, text in inbound_messages(payload):
        reply = wa.handle(request, sender, text)
        if reply is not None:
            conversation = wa.conversations.get(f"whatsapp:{wa.phone_hash(sender)}")
            if conversation is not None:
                wa.send(conversation, reply)  # inline, so "Checking…" always lands before the verdict
    return Response(status_code=200)
