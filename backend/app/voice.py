"""TwiML for trial-account trusted-contact calls (L16): `GET|POST /api/voice/twiml/{token}`.

Twilio trial accounts reject inline Twiml, so the call carries only a Url and
Twilio fetches the words here. The route is public but signed: every request
must carry a valid `X-Twilio-Signature` for `PUBLIC_BASE_URL + path` (plus the
form params on POST), checked with `TWILIO_AUTH_TOKEN`. Bad signature → 403.
Unknown, used or expired token → 404. The token and phone numbers are never logged.
"""

from __future__ import annotations

import logging
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from app.alerts import consume_twiml_token
from app.auth.deps import authorize
from app.config import get_settings
from app.errors import ForbiddenError, NotFoundError
from app.integrations.twilio import verify_signature, voice_twiml

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", dependencies=[Depends(authorize)])


def _url_variants(url: str) -> list[str]:
    """The URL as configured, plus the same URL with/without the default port.

    Twilio signs HTTPS URLs with an explicit `:443` in some cases; its own
    RequestValidator accepts either form, so we do too (same host and path only).
    """
    parts = urlsplit(url)
    default = {"https": 443, "http": 80}.get(parts.scheme)
    host = parts.hostname or ""
    with_port = urlunsplit((parts.scheme, f"{host}:{parts.port or default}", parts.path, parts.query, ""))
    without_port = urlunsplit((parts.scheme, host, parts.path, parts.query, ""))
    return [url, with_port, without_port]


def _log_signature_diagnosis(
    auth_token: str, url: str, arrived: str, params: dict[str, str], signature: str | None
) -> None:
    """Booleans only: which URL/param variant would have matched. No token, URL or signature values."""
    parts = urlsplit(url)
    swap = "http" if parts.scheme == "https" else "https"
    variants = {
        "configured": url,
        "with_443": _url_variants(url)[1],
        "without_port": _url_variants(url)[2],
        "other_scheme": urlunsplit((swap, parts.netloc, parts.path, parts.query, "")),
        "trailing_slash": url + "/",
        "as_arrived": arrived,
    }
    found = {name: verify_signature(auth_token, u, params, signature) for name, u in variants.items()}
    found.update({f"{name}_no_params": verify_signature(auth_token, u, {}, signature) for name, u in variants.items()})
    log.info(
        "voice twiml signature diagnosis",
        extra={"fields": {
            "has_signature": bool(signature),
            "has_auth_token": bool(auth_token),
            "post_param_count": len(params),
            "matches": found,
        }},
    )


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
    signature = request.headers.get("x-twilio-signature")
    verified = bool(base) and any(verify_signature(auth_token, u, params, signature) for u in _url_variants(url))
    if not verified:
        _log_signature_diagnosis(auth_token, url, str(request.url), params, signature)
    if not verified and getattr(settings, "TWILIO_VERIFY_SIGNATURE", True):
        log.info("voice twiml refused", extra={"fields": {"reason": "bad_signature"}})
        raise ForbiddenError("Invalid webhook signature")
    if not verified:
        log.warning("voice twiml served without a valid signature (TWILIO_VERIFY_SIGNATURE=false)")
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
