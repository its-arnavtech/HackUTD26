"""Plain-text email to the trusted contact (L16).

Sent with the standard library (`smtplib` + STARTTLS) from
`ALERT_EMAIL_FROM` to `TRUSTED_CONTACT_EMAIL`. There is no HTML, no link,
no image and no attachment. Failure raises `EmailAlertError` whose message
never includes an address, a password, or the alert text.
"""

from __future__ import annotations

import smtplib
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from zoneinfo import ZoneInfo

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SUBJECT = "Linda may need your help right now"
FOOTER = (
    "You're receiving this because Linda added you as her trusted contact in SentinelAI. "
    "Reply STOP and we won't email you again."
)
_CENTRAL = ZoneInfo("America/Chicago")
_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


class EmailAlertError(RuntimeError):
    """The email was not sent. The message is safe to log."""


def format_central(when: datetime) -> str:
    """Clock time in America/Chicago, English weekday and month, no locale."""
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    local = when.astimezone(_CENTRAL)
    hour = local.hour % 12 or 12
    ampm = "AM" if local.hour < 12 else "PM"
    return (
        f"{_WEEKDAYS[local.weekday()]}, {_MONTHS[local.month - 1]} {local.day}, {local.year} "
        f"at {hour}:{local.minute:02d} {ampm} CT"
    )


def build_alert_body(alert_text: str, called_at: datetime) -> str:
    """The alert, the Central time, the missed-call line, and the footer."""
    when = format_central(called_at)
    return (
        f"{alert_text}\n\n"
        f"{when}\n\n"
        f"We tried to call you at {when} and couldn't reach you.\n\n"
        f"{FOOTER}\n"
    )


def send_alert_email(
    alert_text: str,
    called_at: datetime,
    *,
    mail_from: str,
    app_password: str,
    mail_to: str,
    host: str = SMTP_HOST,
    port: int = SMTP_PORT,
    timeout: float = 20,
    ssl_context: ssl.SSLContext | None = None,
) -> None:
    """Send one plain-text alert. Raises `EmailAlertError` on any failure."""
    if not mail_from.strip() or not app_password or not mail_to.strip():
        raise EmailAlertError("email is not configured")
    message = EmailMessage()
    message["From"] = f"SentinelAI Alerts <{mail_from}>"
    message["To"] = mail_to
    message["Reply-To"] = mail_from
    message["Subject"] = SUBJECT
    message["Date"] = formatdate(localtime=False)
    message["Message-ID"] = make_msgid()
    message.set_content(build_alert_body(alert_text, called_at))
    try:
        with smtplib.SMTP(host, port, timeout=timeout) as client:
            client.ehlo()
            client.starttls(context=ssl_context or ssl.create_default_context())
            client.ehlo()
            client.login(mail_from, app_password)
            client.send_message(message)
    except (smtplib.SMTPException, OSError, ssl.SSLError) as exc:
        raise EmailAlertError(f"email could not be sent ({type(exc).__name__})") from None
