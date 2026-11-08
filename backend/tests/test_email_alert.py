"""Plain-text trusted-contact email (L16), against a local SMTP server. No network."""

from __future__ import annotations

import ipaddress
import os
import smtplib
import socket
import ssl
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from email import message_from_string, policy
from email.utils import parsedate_to_datetime

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from app.integrations.email_alert import (
    FOOTER,
    SUBJECT,
    EmailAlertError,
    format_central,
    send_alert_email,
)

FROM = "alerts@example.com"
TO = "maya.trusted@example.com"
PASSWORD = "gmail-app-password-secret"
ALERT = (
    "SentinelAI: Linda may be in a conversation with a scammer right now. Please call Linda now. "
    "We have not moved any money. This alert contains none of the message."
)
BANNED = ("urgent", "act now", "free", "winner", "verify", "click")


class SmtpBox:
    """Local SMTP server: STARTTLS, AUTH, then one plain-text message."""

    def __init__(self, *, reject_auth: bool = False) -> None:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
        now = datetime.now(timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(days=1))
            .add_extension(
                x509.SubjectAlternativeName([x509.IPAddress(ipaddress.IPv4Address("127.0.0.1"))]),
                critical=False,
            )
            .sign(key, hashes.SHA256())
        )
        self.cert_pem = cert.public_bytes(serialization.Encoding.PEM)
        key_pem = key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()
        )
        # tempfile, not /tmp: the team runs pytest on Windows.
        tmp = tempfile.gettempdir()
        self._cert_path = os.path.join(tmp, f"sentinel-alert-{id(self)}.crt")
        self._key_path = os.path.join(tmp, f"sentinel-alert-{id(self)}.key")
        with open(self._cert_path, "wb") as handle:
            handle.write(self.cert_pem)
        with open(self._key_path, "wb") as handle:
            handle.write(key_pem)
        self.server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.server_ctx.load_cert_chain(self._cert_path, self._key_path)
        self.reject_auth = reject_auth
        self.messages: list[str] = []
        self._stop = threading.Event()
        self._sock = socket.socket()
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(8)
        self.port = self._sock.getsockname()[1]
        self._thread = threading.Thread(target=self._accept, daemon=True)
        self._thread.start()

    def client_context(self) -> ssl.SSLContext:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.load_verify_locations(cadata=self.cert_pem.decode())
        return ctx

    def close(self) -> None:
        self._stop.set()
        try:
            self._sock.close()
        except OSError:
            pass
        self._thread.join(timeout=2)

    def _accept(self) -> None:
        self._sock.settimeout(0.2)
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except (socket.timeout, OSError):
                continue
            try:
                self._session(conn)
            except Exception:
                pass
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

    def _session(self, conn: socket.socket) -> None:
        state = {"sock": conn}
        pending = b""

        def send(line: str) -> None:
            state["sock"].sendall(line.encode())

        def read_line() -> str:
            nonlocal pending
            while b"\n" not in pending:
                state["sock"].settimeout(5)
                chunk = state["sock"].recv(4096)
                if not chunk:
                    return ""
                pending += chunk
            raw, pending = pending.split(b"\n", 1)
            return raw.decode("utf-8", "replace").rstrip("\r")

        send("220 localhost ESMTP\r\n")
        while True:
            command = read_line()
            if not command:
                break
            upper = command.upper()
            if upper.startswith("EHLO") or upper.startswith("HELO"):
                send("250-127.0.0.1\r\n250-STARTTLS\r\n250 AUTH PLAIN LOGIN\r\n")
            elif upper.startswith("STARTTLS"):
                send("220 Ready\r\n")
                state["sock"] = self.server_ctx.wrap_socket(state["sock"], server_side=True)
                pending = b""
            elif upper.startswith("AUTH"):
                if upper == "AUTH LOGIN":
                    send("334 VXNlcm5hbWU6\r\n")
                    read_line()
                    send("334 UGFzc3dvcmQ6\r\n")
                    read_line()
                send("535 denied\r\n" if self.reject_auth else "235 OK\r\n")
            elif upper.startswith(("MAIL", "RCPT", "NOOP", "RSET")):
                send("250 OK\r\n")
            elif upper == "DATA":
                send("354 End data with <CR><LF>.<CR><LF>\r\n")
                lines: list[str] = []
                while True:
                    row = read_line()
                    if row == ".":
                        break
                    lines.append(row[1:] if row.startswith("..") else row)
                self.messages.append("\r\n".join(lines))
                send("250 OK\r\n")
            elif upper.startswith("QUIT"):
                send("221 Bye\r\n")
                break
            else:
                send("250 OK\r\n")


def test_alert_email_is_plain_text_with_the_footer_and_no_links():
    called_at = datetime(2026, 11, 8, 15, 24, tzinfo=timezone.utc)
    box = SmtpBox()
    try:
        send_alert_email(
            ALERT, called_at,
            mail_from=FROM, app_password=PASSWORD, mail_to=TO,
            host="127.0.0.1", port=box.port, timeout=5, ssl_context=box.client_context(),
        )
    finally:
        box.close()
    assert len(box.messages) == 1
    message = message_from_string(box.messages[0], policy=policy.default)
    assert message.get_content_type() == "text/plain"
    assert not message.is_multipart()
    assert message["Subject"] == SUBJECT
    assert "!" not in message["Subject"]
    assert not any(word.isupper() and word.isalpha() for word in message["Subject"].split())
    assert message["From"] == f"SentinelAI Alerts <{FROM}>"
    assert message["Reply-To"] == FROM
    assert message["To"] == TO
    assert message["Message-ID"].startswith("<") and message["Message-ID"].endswith(">")
    parsedate_to_datetime(message["Date"])
    body = message.get_content()
    when = format_central(called_at)
    assert when == "Sunday, November 8, 2026 at 9:24 AM CT"
    assert body.startswith(ALERT)
    assert when in body
    assert f"We tried to call you at {when} and couldn't reach you." in body
    assert FOOTER in body
    lowered = f"{message['Subject']}\n{body}".lower()
    for banned in BANNED:
        assert banned not in lowered
    assert "http://" not in lowered and "https://" not in lowered and "www." not in lowered
    assert "<html" not in lowered and "<img" not in lowered
    assert "content-disposition" not in box.messages[0].lower()


def test_auth_failure_and_missing_config_raise_without_secrets():
    box = SmtpBox(reject_auth=True)
    try:
        with pytest.raises(EmailAlertError) as refused:
            send_alert_email(
                ALERT, datetime.now(timezone.utc),
                mail_from=FROM, app_password=PASSWORD, mail_to=TO,
                host="127.0.0.1", port=box.port, timeout=5, ssl_context=box.client_context(),
            )
    finally:
        box.close()
    text = str(refused.value)
    assert PASSWORD not in text and FROM not in text and TO not in text and ALERT not in text
    assert box.messages == []

    with pytest.raises(EmailAlertError, match="not configured") as blank:
        send_alert_email(ALERT, datetime.now(timezone.utc), mail_from="", app_password=PASSWORD, mail_to=TO)
    assert PASSWORD not in str(blank.value)


def test_default_server_is_gmail_starttls(monkeypatch):
    seen: dict[str, object] = {}

    class Boom(smtplib.SMTP):
        def __init__(self, host: str = "", port: int = 0, timeout: float = 0) -> None:
            seen["host"] = host
            seen["port"] = port
            raise OSError("blocked")

    monkeypatch.setattr(smtplib, "SMTP", Boom)
    with pytest.raises(EmailAlertError) as exc:
        send_alert_email(ALERT, datetime.now(timezone.utc), mail_from=FROM, app_password=PASSWORD, mail_to=TO)
    assert seen == {"host": "smtp.gmail.com", "port": 587}
    assert PASSWORD not in str(exc.value) and FROM not in str(exc.value) and TO not in str(exc.value)
