"""Redaction module. Filled in by A3 (gate P5).

Runs before the classifier, Nemotron or any outside service sees a message.
Replaces names, personal phone numbers, account digits, addresses and emails
(DATA_SPEC.md section 5) and every full URL with `<URL_n>`.
"""

from __future__ import annotations

from app.contracts import RedactedMessage, SenderType


def redact(text: str) -> RedactedMessage:
    """Return the redacted text, the redaction report and the raw URLs kept in memory. (A3)"""
    raise NotImplementedError("A3: redaction")


def hash_phone(number: str, salt: str) -> str:
    """Salted hash for a personal phone number, rendered as `<PHONE_HASH_xxxx>`. (A3)"""
    raise NotImplementedError("A3: phone hashing")


def redact_sender(raw_sender: str) -> tuple[SenderType, str]:
    """Classify the sender and hash it if personal. Business short codes stay visible. (A3)"""
    raise NotImplementedError("A3: sender redaction")
