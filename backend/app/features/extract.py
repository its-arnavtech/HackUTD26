"""Feature extraction. Filled in by A9.

Returns the `urls` and `features` objects from DATA_SPEC.md section 3.1. Works on
redacted text only, plus the raw URLs that redaction kept in memory.
"""

from __future__ import annotations

from typing import Optional

from app.contracts import Features, RedactedMessage, UrlInfo


def extract_urls(redacted: RedactedMessage) -> list[UrlInfo]:
    """Describe each `<URL_n>`: registered domain, shortener, brand term, official domain. (A9)"""
    raise NotImplementedError("A9: URL features")


def extract_features(text_redacted: str) -> Features:
    """Urgency deadline, threat, requested action, what it asks for, money claimed. (A9)"""
    raise NotImplementedError("A9: message features")


def detect_claimed_brand(text_redacted: str) -> Optional[str]:
    """The brand the message claims to come from, matched against data/brands.json. (A9)"""
    raise NotImplementedError("A9: claimed brand")
