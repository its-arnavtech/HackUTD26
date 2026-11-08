"""SentinelAI by text message, through Twilio: `POST /api/sms/inbound` (L14, DATA_SPEC section 9).

Twilio calls this webhook for each text to the SentinelAI number. The
conversation itself (check, CLICKED, YES/NO, BLOCK) is shared with WhatsApp and
lives in `app/messaging.py`; this module only checks Twilio's signature, answers
with TwiML and sends follow-ups through Twilio's API.

Note: a Twilio *trial* account can't do this (no own number; templates only).
It needs an upgraded account with a number. WhatsApp (`app/whatsapp.py`) is the
free route.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from urllib.parse import parse_qsl

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from app.auth.deps import authorize
from app.errors import ForbiddenError
from app.integrations.twilio import TwilioClient, verify_signature
from app.messaging import (  # noqa: F401 - re-exported for tests and callers
    ACK,
    BLOCKED,
    FAILED,
    HELP,
    NO_MESSAGE,
    Conversation,
    MessagingService,
    Reply,
    _audit,
    as_sms,
)


@dataclass
class SmsService(MessagingService):
    client: TwilioClient | None = None
    channel: str = "sms"

    def deliver(self, conversation: Conversation, reply: Reply) -> None:
        assert self.client is not None
        self.client.send_sms(conversation.number, as_sms(reply))


def twiml(reply: Reply | None) -> Response:
    inner = f"<Message>{html.escape(as_sms(reply))}</Message>" if reply else ""
    return Response(f'<?xml version="1.0" encoding="UTF-8"?><Response>{inner}</Response>', media_type="application/xml")


router = APIRouter(prefix="/api", dependencies=[Depends(authorize)])


@router.post("/sms/inbound")
async def sms_inbound(request: Request) -> Response:
    sms: SmsService = request.app.state.sms
    raw = (await request.body()).decode("utf-8", errors="replace")
    params = dict(parse_qsl(raw, keep_blank_values=True))
    url = sms.public_base_url.rstrip("/") + request.url.path
    if request.url.query:
        url += "?" + request.url.query
    assert sms.client is not None
    if not verify_signature(sms.client.auth_token, url, params, request.headers.get("x-twilio-signature")):
        _audit(request, "sms.bad_signature", "anonymous", outcome="denied")
        raise ForbiddenError("Invalid webhook signature")
    return twiml(sms.handle(request, params.get("From", ""), params.get("Body", "")))
