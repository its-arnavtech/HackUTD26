"""Twilio SMS: verify inbound webhooks and send replies (L14).

**Why this doesn't go through `cache.cached_call`:** sending a text is an action,
not a lookup. Recording it would put phone numbers into committed fixtures, and
replaying it would make no sense. So:

- `DEMO_MODE=live` or `record`: really send.
- `DEMO_MODE=replay`: log "not sent (replay)" and send nothing.

**Webhook signature:** Twilio signs each webhook with HMAC-SHA1 of the full URL
plus the sorted POST parameters, keyed with the account's auth token
(`X-Twilio-Signature`). Anything without a valid signature is refused, so only
Twilio can start a check or get a reply sent.

Nothing here logs a phone number or a message body.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
from collections.abc import Mapping
from xml.sax.saxutils import escape

import httpx

from app.contracts import DemoMode

log = logging.getLogger(__name__)

API_BASE = "https://api.twilio.com/2010-04-01"
TIMEOUT_S = 10.0
MAX_SMS_CHARS = 1600


class TwilioError(RuntimeError):
    """Sending failed. The message is safe to log (no number, no body)."""


def expected_signature(auth_token: str, url: str, params: Mapping[str, str]) -> str:
    payload = url + "".join(f"{key}{params[key]}" for key in sorted(params))
    digest = hmac.new(auth_token.encode("utf-8"), payload.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("ascii")


def verify_signature(auth_token: str, url: str, params: Mapping[str, str], signature: str | None) -> bool:
    if not signature or not auth_token:
        return False
    return hmac.compare_digest(expected_signature(auth_token, url, params), signature)


class TwilioClient:
    def __init__(
        self,
        account_sid: str,
        auth_token: str,
        from_number: str,
        demo_mode: DemoMode,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.from_number = from_number
        self.demo_mode = demo_mode
        self._transport = transport

    def send_sms(self, to: str, body: str) -> str | None:
        """Send `body` to `to`. Returns Twilio's message SID, or None in replay mode."""
        body = body[:MAX_SMS_CHARS]
        if self.demo_mode == DemoMode.replay:
            log.info("sms not sent (replay mode)", extra={"fields": {"chars": len(body)}})
            return None
        url = f"{API_BASE}/Accounts/{self.account_sid}/Messages.json"
        try:
            with httpx.Client(timeout=TIMEOUT_S, transport=self._transport) as client:
                response = client.post(
                    url,
                    data={"To": to, "From": self.from_number, "Body": body},
                    auth=(self.account_sid, self.auth_token),
                )
        except httpx.HTTPError as exc:
            raise TwilioError(f"Twilio unreachable ({type(exc).__name__})") from None
        if response.status_code >= 300:
            code = ""
            try:
                code = str(response.json().get("code", ""))
            except ValueError:
                pass
            raise TwilioError(f"Twilio refused the message (HTTP {response.status_code}, code {code or 'n/a'})")
        sid = response.json().get("sid")
        log.info("sms sent", extra={"fields": {"chars": len(body)}})
        return sid

    def create_call(
        self,
        to: str,
        from_: str,
        twiml: str,
        timeout: int = 25,
        machine_detection: str = "DetectMessageEnd",
    ) -> str | None:
        """Place a call that speaks `twiml`. Returns the call SID, or None in replay mode.

        Nothing here is logged except the TwiML length: not the number, the
        caller id, or the words.
        """
        if self.demo_mode == DemoMode.replay:
            log.info("call not placed (replay mode)", extra={"fields": {"chars": len(twiml)}})
            return None
        url = f"{API_BASE}/Accounts/{self.account_sid}/Calls.json"
        try:
            with httpx.Client(timeout=TIMEOUT_S, transport=self._transport) as client:
                response = client.post(
                    url,
                    data={
                        "To": to,
                        "From": from_,
                        "Twiml": twiml,
                        "Timeout": str(timeout),
                        "MachineDetection": machine_detection,
                    },
                    auth=(self.account_sid, self.auth_token),
                )
        except httpx.HTTPError as exc:
            raise TwilioError(f"Twilio unreachable ({type(exc).__name__})") from None
        if response.status_code >= 300:
            code = ""
            try:
                code = str(response.json().get("code", ""))
            except ValueError:
                pass
            raise TwilioError(f"Twilio refused the call (HTTP {response.status_code}, code {code or 'n/a'})")
        try:
            sid = response.json().get("sid")
        except ValueError:
            raise TwilioError("Twilio returned a call id that was not JSON") from None
        if not sid:
            raise TwilioError("Twilio returned no call id")
        log.info("call placed", extra={"fields": {"chars": len(twiml)}})
        return str(sid)

    def get_call(self, sid: str) -> dict[str, str | None]:
        """`{"status", "answered_by"}` for a call. `answered_by` is None when Twilio omits it."""
        if self.demo_mode == DemoMode.replay:
            log.info("call status not fetched (replay mode)")
            return {"status": "no-answer", "answered_by": None}
        url = f"{API_BASE}/Accounts/{self.account_sid}/Calls/{sid}.json"
        try:
            with httpx.Client(timeout=TIMEOUT_S, transport=self._transport) as client:
                response = client.get(url, auth=(self.account_sid, self.auth_token))
        except httpx.HTTPError as exc:
            raise TwilioError(f"Twilio unreachable ({type(exc).__name__})") from None
        if response.status_code >= 300:
            code = ""
            try:
                code = str(response.json().get("code", ""))
            except ValueError:
                pass
            raise TwilioError(f"Twilio refused the call lookup (HTTP {response.status_code}, code {code or 'n/a'})")
        try:
            body = response.json()
        except ValueError:
            raise TwilioError("Twilio returned a call status that was not JSON") from None
        answered = body.get("answered_by")
        status = str(body.get("status") or "")
        known = {"queued", "ringing", "in-progress", "completed", "busy", "failed", "no-answer", "canceled"}
        log.info("call status read", extra={"fields": {"status": status if status in known else "other"}})
        return {"status": status, "answered_by": str(answered) if answered else None}


def voice_twiml(alert_text: str) -> str:
    """Inline TwiML: say the alert, pause one second, say it again.

    The words are escaped. The alert itself must already be content-free.
    """
    said = escape(alert_text)
    return f'<Response><Say>{said}</Say><Pause length="1"/><Say>{said}</Say></Response>'
