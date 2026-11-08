"""TwiML for trial-account trusted-contact calls (L16): `GET|POST /api/voice/twiml/{token}`.

Twilio trial accounts reject inline Twiml, so the call carries only a Url and
Twilio fetches the words here. The route is public but signed: every request
must carry a valid `X-Twilio-Signature` for `PUBLIC_BASE_URL + path` (plus the
form params on POST), checked with `TWILIO_AUTH_TOKEN`. Bad signature → 403.
Unknown, used or expired token → 404. The token and phone numbers are never logged.
"""

from __future__ import annotations

import logging
from urllib.parse import parse_qsl

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from app.alerts import consume_twiml_token
from app.auth.deps import authorize
from app.config import get_settings
from app.errors import ForbiddenError, NotFoundError
from app.integrations.twilio import verify_signature, voice_twiml

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", dependencies=[Depends(authorize)])


async def _twiml(request: Request, token: str) -> Response:
    settings = request.app.state.settings if hasattr(request.app.state, "settings") else get_settings()
    auth_token = settings.TWILIO_AUTH_TOKEN.get_secret_value() if settings.TWILIO_AUTH_TOKEN else ""
    base = (settings.PUBLIC_BASE_URL or "").strip().rstrip("/")
    url = base + request.url.path
    if request.url.query:
        url += "?" + request.url.query
    params: dict[str, str] = {}
    if request.method == "POST":
        raw = (await request.body()).decode("utf-8", errors="replace")
        params = dict(parse_qsl(raw, keep_blank_values=True))
    if not base or not verify_signature(auth_token, url, params, request.headers.get("x-twilio-signature")):
        log.info("voice twiml refused", extra={"fields": {"reason": "bad_signature"}})
        raise ForbiddenError("Invalid webhook signature")
    text = consume_twiml_token(token)
    if text is None:
        log.info("voice twiml refused", extra={"fields": {"reason": "unknown_or_expired"}})
        raise NotFoundError("Unknown or expired call")
    log.info("voice twiml served")
    body = '<?xml version="1.0" encoding="UTF-8"?>' + voice_twiml(text)
    return Response(body, media_type="text/xml")


@router.get("/voice/twiml/{token}")
async def voice_twiml_get(token: str, request: Request) -> Response:
    return await _twiml(request, token)


@router.post("/voice/twiml/{token}")
async def voice_twiml_post(token: str, request: Request) -> Response:
    return await _twiml(request, token)
