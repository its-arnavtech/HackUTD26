"""Trusted-contact voice alert (L16).

`start_alert` returns at once with `state="calling"` and finishes the call in
a background thread. One alert per message is started every 60 seconds; a tap
inside that window returns the alert already in progress or just finished.

The words are `trusted_contact.alert_text` (the sentence inside `alert_note`):
the same string is spoken, left on voicemail, emailed, and stored as
`alert_text`. No message text, amount, link, or phone number is included.

`VOICE_ALERTS_ENABLED` off, or `DEMO_MODE=replay`, never calls Twilio or Gmail.
The status then becomes `no_answer` with `email_sent` and `simulated` after
about three seconds.

Phone numbers, email addresses and secrets are not logged, stored, or audited.
Destinations in the privacy log are HMAC-SHA256 truncations.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import threading
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app import privacy_log, trusted_contact
from app.contracts import AgentMode, DemoMode
from app.integrations.email_alert import EmailAlertError, send_alert_email
from app.integrations.twilio import TwilioClient, TwilioError, voice_twiml

log = logging.getLogger(__name__)

POLL_INTERVAL_S = 2.0
POLL_TIMEOUT_S = 90.0
COOLDOWN_S = 60.0
SIMULATE_DELAY_S = 3.0

CallOutcome = Literal["answered", "voicemail", "no_answer", "failed"]
_MACHINE = "machine"
_EMAIL_DETAIL = "The email could not be sent."


class AlertStatus(BaseModel):
    """Latest trusted-contact alert for one message. Not a shared contract."""

    model_config = ConfigDict(extra="forbid")

    message_id: str
    state: Literal["calling", "done"]
    call_outcome: CallOutcome | None = None
    email_sent: bool = False
    simulated: bool = False
    called_at: datetime | None = None
    email_sent_at: datetime | None = None
    alert_text: str
    detail: str | None = None


class _Slot:
    def __init__(self, status: AlertStatus, started: float, attempt: str) -> None:
        self.status = status
        self.started = started
        self.attempt = attempt
        self.thread: threading.Thread | None = None


_lock = threading.Lock()
_alerts: dict[str, _Slot] = {}


def clear() -> None:
    """Drop in-memory alerts. In-flight threads then leave the map alone."""
    with _lock:
        _alerts.clear()


def get_alert(message_id: str) -> AlertStatus | None:
    with _lock:
        slot = _alerts.get(message_id)
        return slot.status.model_copy() if slot else None


def wait_alert(message_id: str, timeout: float = 5.0) -> AlertStatus | None:
    """Block until the background attempt for `message_id` finishes, for tests."""
    with _lock:
        thread = _alerts[message_id].thread if message_id in _alerts else None
    if thread is not None:
        thread.join(timeout)
    return get_alert(message_id)


def start_alert(
    message_id: str,
    customer_id: str,
    *,
    settings: Any = None,
    store: Any = None,
    audit: Any = None,
    twilio: Any = None,
    send_email: Callable[[str, datetime], None] | None = None,
    poll_interval: float | None = None,
    poll_timeout: float | None = None,
    simulate_delay: float | None = None,
    cooldown: float | None = None,
    clock: Callable[[], float] | None = None,
) -> AlertStatus:
    """Begin an alert, or return the one already started in the last minute."""
    if settings is None:
        from app.config import get_settings

        settings = get_settings()
    now = (clock or time.monotonic)()
    window = COOLDOWN_S if cooldown is None else cooldown
    with _lock:
        current = _alerts.get(message_id)
        if current is not None and now - current.started < window:
            return current.status.model_copy()
        text = _alert_text(store, message_id)
        simulated = _should_simulate(settings)
        status = AlertStatus(message_id=message_id, state="calling", simulated=simulated, alert_text=text)
        slot = _Slot(status, now, uuid.uuid4().hex)
        _alerts[message_id] = slot
        snapshot = status.model_copy()

    def run() -> None:
        try:
            _run(
                message_id,
                customer_id,
                slot.attempt,
                text,
                simulated,
                settings,
                store,
                audit,
                twilio,
                send_email,
                POLL_INTERVAL_S if poll_interval is None else poll_interval,
                POLL_TIMEOUT_S if poll_timeout is None else poll_timeout,
                SIMULATE_DELAY_S if simulate_delay is None else simulate_delay,
            )
        except Exception as exc:
            log.error("alert failed", extra={"fields": {"error": type(exc).__name__}})
            _update(message_id, slot.attempt, state="done", call_outcome="failed", detail=_EMAIL_DETAIL)

    thread = threading.Thread(target=run, name="sentinel-alert", daemon=True)
    slot.thread = thread
    thread.start()
    return snapshot


def classify_call(status: str, answered_by: str | None) -> CallOutcome | None:
    """Map a Twilio poll to an outcome. None means keep polling."""
    state = (status or "").strip().lower()
    who = (answered_by or "").strip().lower()
    if who.startswith(_MACHINE):
        return "voicemail"
    if state == "completed" and who == "human":
        return "answered"
    if state in {"busy", "no-answer", "canceled"}:
        return "no_answer"
    if state == "failed":
        return "failed"
    if state == "completed":
        return "no_answer"
    return None


def _should_simulate(settings: Any) -> bool:
    return (not settings.VOICE_ALERTS_ENABLED) or settings.DEMO_MODE == DemoMode.replay


def _alert_text(store: Any, message_id: str) -> str:
    from app.pipeline import DEMO_PERSON_NAMES

    recovery = False
    if store is not None and store.has_message(message_id):
        recovery = store.get_message(message_id).mode == AgentMode.recovery
    return trusted_contact.alert_text(DEMO_PERSON_NAMES[0], recovery)


def _update(message_id: str, attempt: str, **changes: Any) -> None:
    with _lock:
        slot = _alerts.get(message_id)
        if slot is None or slot.attempt != attempt:
            return
        slot.status = slot.status.model_copy(update=changes)


def _run(
    message_id: str,
    customer_id: str,
    attempt: str,
    text: str,
    simulated: bool,
    settings: Any,
    store: Any,
    audit: Any,
    twilio: Any,
    send_email: Callable[[str, datetime], None] | None,
    poll_interval: float,
    poll_timeout: float,
    simulate_delay: float,
) -> None:
    if simulated:
        time.sleep(simulate_delay)
        stamp = datetime.now(timezone.utc)
        _update(
            message_id,
            attempt,
            state="done",
            call_outcome="no_answer",
            email_sent=True,
            simulated=True,
            called_at=stamp,
            email_sent_at=stamp,
        )
        _audit(audit, customer_id, message_id, "no_answer", email_sent=True, simulated=True)
        log.info("alert simulated", extra={"fields": {"outcome": "no_answer"}})
        return

    called_at = datetime.now(timezone.utc)
    _update(message_id, attempt, called_at=called_at)
    outcome = _place_and_poll(message_id, text, settings, store, twilio, poll_interval, poll_timeout)
    email_sent = False
    detail = None
    if outcome != "answered":
        email_sent, detail = _email(message_id, text, called_at, settings, store, send_email)
    _update(
        message_id,
        attempt,
        state="done",
        call_outcome=outcome,
        email_sent=email_sent,
        simulated=False,
        detail=detail,
        email_sent_at=datetime.now(timezone.utc) if email_sent else None,
    )
    _audit(audit, customer_id, message_id, outcome, email_sent=email_sent, simulated=False)
    log.info("alert finished", extra={"fields": {"outcome": outcome, "email_sent": email_sent}})


def _place_and_poll(
    message_id: str,
    text: str,
    settings: Any,
    store: Any,
    twilio: Any,
    poll_interval: float,
    poll_timeout: float,
) -> CallOutcome:
    phone = (settings.TRUSTED_CONTACT_PHONE or "").strip()
    caller = (settings.TWILIO_FROM_NUMBER or "").strip()
    if not phone or not caller or not settings.TWILIO_ACCOUNT_SID or settings.TWILIO_AUTH_TOKEN is None:
        log.info("alert call skipped", extra={"fields": {"reason": "not_configured"}})
        return "failed"
    client = twilio if twilio is not None else _twilio_client(settings)
    twiml = voice_twiml(text)
    sent = {
        "channel": "voice",
        "alert_text": text,
        "to_hmac": _destination_hmac(phone, settings),
        "machine_detection": "DetectMessageEnd",
    }
    try:
        sid = client.create_call(phone, caller, twiml, timeout=25, machine_detection="DetectMessageEnd")
    except TwilioError as exc:
        _privacy(store, message_id, "twilio", sent)
        log.info("alert call failed", extra={"fields": {"error": type(exc).__name__}})
        return "failed"
    if not sid:
        return "failed"
    _privacy(store, message_id, "twilio", sent)
    deadline = time.monotonic() + poll_timeout
    last_status, last_who = "", None
    while True:
        try:
            info = client.get_call(sid)
        except TwilioError as exc:
            log.info("alert call status failed", extra={"fields": {"error": type(exc).__name__}})
            return "failed"
        last_status = str(info.get("status") or "")
        last_who = info.get("answered_by")
        outcome = classify_call(last_status, last_who)
        if outcome is not None:
            return outcome
        if time.monotonic() >= deadline:
            who = (last_who or "").strip().lower()
            if who == "human":
                return "answered"
            if who.startswith(_MACHINE):
                return "voicemail"
            return "no_answer"
        time.sleep(poll_interval)


def _email(
    message_id: str,
    text: str,
    called_at: datetime,
    settings: Any,
    store: Any,
    send_email: Callable[[str, datetime], None] | None,
) -> tuple[bool, str | None]:
    sender = send_email or _default_sender(settings)
    try:
        sender(text, called_at)
    except EmailAlertError as exc:
        log.info("alert email failed", extra={"fields": {"error": type(exc).__name__}})
        return False, _EMAIL_DETAIL
    _privacy(
        store,
        message_id,
        "gmail",
        {
            "channel": "email",
            "alert_text": text,
            "to_hmac": _destination_hmac(settings.TRUSTED_CONTACT_EMAIL or "", settings),
            "subject": "Linda may need your help right now",
        },
    )
    return True, None


def _default_sender(settings: Any) -> Callable[[str, datetime], None]:
    def send(alert_text: str, called_at: datetime) -> None:
        password = settings.ALERT_EMAIL_APP_PASSWORD.get_secret_value() if settings.ALERT_EMAIL_APP_PASSWORD else ""
        send_alert_email(
            alert_text,
            called_at,
            mail_from=settings.ALERT_EMAIL_FROM,
            app_password=password,
            mail_to=settings.TRUSTED_CONTACT_EMAIL,
        )

    return send


def _twilio_client(settings: Any) -> TwilioClient:
    token = settings.TWILIO_AUTH_TOKEN.get_secret_value() if settings.TWILIO_AUTH_TOKEN else ""
    return TwilioClient(settings.TWILIO_ACCOUNT_SID, token, settings.TWILIO_FROM_NUMBER, settings.DEMO_MODE)


def _destination_hmac(value: str, settings: Any) -> str:
    salt = settings.PHONE_HASH_SALT.get_secret_value() if settings.PHONE_HASH_SALT is not None else "sentinel-alert"
    return hmac.new(salt.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()[:16]


def _privacy(store: Any, message_id: str, recipient: str, payload: dict[str, Any]) -> None:
    if store is None or not store.has_message(message_id):
        return
    try:
        run = int(store.get_message(message_id).run or 0)
        privacy_log.PrivacyLog(store, message_id, run).record(recipient, "tool", payload, list(payload))
    except Exception as exc:
        log.error("alert privacy record failed", extra={"fields": {"error": type(exc).__name__}})


def _audit(audit: Any, customer_id: str, message_id: str, outcome: str, *, email_sent: bool, simulated: bool) -> None:
    if audit is None:
        return
    reached = outcome == "answered" or email_sent or simulated
    try:
        audit.record(
            "alert.trusted_contact",
            actor=customer_id,
            target=message_id,
            outcome="success" if reached else "failure",
            details={"call": outcome, "email": email_sent, "simulated": simulated},
        )
    except Exception as exc:
        log.error("alert audit record failed", extra={"fields": {"error": type(exc).__name__}})
