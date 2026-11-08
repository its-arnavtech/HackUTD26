"""Local, deterministic P5 redaction; no network, model, logging or storage.

Names use greetings, titles, identity labels and capitalized full-name patterns.
Callers can supply known customer names locally with person_names. These regex
heuristics are not general named-entity recognition: arbitrary unmarked single
names and uncommon address formats are not guaranteed. Keep this limitation in
privacy/evaluation reporting; never claim universal PII detection.

The only original content returned separately is raw_urls, as required by the
in-memory A9 contract. Never serialize that field into model/tool payloads.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache

from app.config import DATA_DIR, get_settings
from app.contracts import RedactedMessage, RedactionCounts, RedactionReport, SenderType

_TAG = re.compile(r"<(?:PERSON|EMAIL|ADDRESS|ACCOUNT_DIGITS|PHONE_HASH_[a-f0-9]+|URL_\d+|UNKNOWN_SENDER)>")
_DOMAIN = r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?:[a-z]{2,63}|xn--[a-z0-9-]+)"
_URL = re.compile(r"https?://[^\s<>\"']+|www\.[^\s<>\"']+|(?<![\w@.-])" + _DOMAIN + r"(?::\d{1,5})?(?:[/?#][^\s<>\"']*)?", re.I)
_EMAIL = re.compile(r"(?<![\w.+-])[\w.!#$%&'*+/=?^`{|}~-]+@[\w-]+(?:\.[\w-]+)+", re.U)
_EXT = r"(?:\s*(?:ext(?:ension)?\.?|x|\#)\s*\d{1,6})?"
_PHONE = re.compile(r"(?<!\d)(?:(?:\+?1[ .-]?)?(?:\(\d{3}\)|\d{3})[ .-]?\d{3}[ .-]?\d{4}|\+\d(?:[\d ().-]{5,23}\d)|\d{3}[-.]\d{4})(?!\d)" + _EXT, re.I)
_STREET = r"(?:street|st|avenue|ave|road|rd|lane|ln|drive|dr|boulevard|blvd|court|ct|way|place|pl|terrace|ter|parkway|pkwy|circle|cir)"
_ADDRESS = re.compile(
    r"\b(?:\d{1,6}\s+(?:[\w.'’-]+\s+){1,6}" + _STREET + r"\b\.?|P\.?\s*O\.?\s+Box\s+\d{1,6})"
    r"(?:\s*,?\s*(?:apt\.?|apartment|unit|suite|ste\.?|\#)\s*[\w-]+)?"
    r"(?:,\s*[A-Za-z][A-Za-z .'-]{0,40},?\s+[A-Z]{2}\s+\d{5}(?:-\d{4})?)?", re.I)
_ACCOUNT_VALUE = r"(?:[xX*•]{2,}\s*)?(?:\d{4}(?:[ -]\d{4}){1,3}|\d{4,19})"
_ACCOUNT = re.compile(
    r"(?i:\b(?:account|acct|card|routing|iban|ssn)\b\s*(?:(?:number|no\.?|ending(?:\s+in)?|last\s+(?:four|4)(?:\s+digits)?)\s*)?[:\#=-]?\s*|\bending\s+in\s+|\blast\s+(?:four|4)\s+digits\s*[:=]?\s*)"
    r"(?P<digits>" + _ACCOUNT_VALUE + r")(?!\d)")
_CARD = re.compile(r"(?<!\d)(?:(?:\d{4}[ -]){3}\d{4}|\d{4}[ -]\d{6}[ -]\d{5})(?!\d)")
_DIGITS = re.compile(r"\d{4,}")
_AMOUNT = re.compile(r"(?:[$£€]\s*\d[\d,]*(?:\.\d{1,2})?|\b\d[\d,]*(?:\.\d{1,2})?\s*(?:USD|GBP|EUR)\b)", re.I)
_DEADLINE = re.compile(r"\b\d+\s*(?:seconds?|minutes?|mins?|hours?|hrs?|days?|weeks?)\b|\b\d{4}-\d{2}-\d{2}(?:T[\d:.+-]+Z?)?|\b\d{1,2}/\d{1,2}/\d{4}\b|\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2},?\s+\d{4}\b", re.I)
_SHORT_CODE = re.compile(r"(?i:\b(?:text|sms|reply|send|short\s*code)\s+(?:[A-Za-z]+\s+)?(?:to\s+)?)(?P<code>\d{5,6})(?!\d)")
_CAP_WORD = r"[A-ZÀ-ÖØ-Þ][^\W\d_]*(?:['’-][^\W\d_]+)*\.?"
_NAME_WORD = r"[^\W\d_]+(?:['’-][^\W\d_]+)*\.?"
_PERSON_CONTEXT = [
    re.compile(r"(?i:\b(?:hi|hello|dear|hey|attention|mr\.?|mrs\.?|ms\.?|dr\.?|mx\.?)\s+)(?P<person>" + _NAME_WORD + r"(?:\s+" + _NAME_WORD + r"){0,3})"),
    re.compile(r"(?i:\b(?:customer(?:\s+name)?|full\s+name|name|recipient|cardholder|account\s+holder|beneficiary)\s*[:=]\s*)(?P<person>" + _NAME_WORD + r"(?:\s+" + _NAME_WORD + r"){0,3})"),
    re.compile(r"(?i:\b(?:my\s+name\s+is|i\s+am|i'm|this\s+is|for|to|from)\s+)(?P<person>" + _CAP_WORD + r"(?:\s+" + _CAP_WORD + r"){0,3})"),
]
_FULL_NAME = re.compile(r"\b(?=(?P<person>" + _CAP_WORD + r"(?:\s+" + _CAP_WORD + r"){1,3}))")
_CONTEXT_STOP = frozenset("your you a an the there customer user member account card payment paid is are was has have will please this that verify now today tomorrow thanks thank and or at on in by with from to for of alert notice support service team security capital one mobile bank checking balance locked suspended overdue due click link code text reply stop hello hi dear mr mrs ms dr mx".split())
_GLOBAL_STOP = _CONTEXT_STOP | frozenset("free new unknown bill offer capital one apple google amazon united states main street avenue road".split())


@dataclass(frozen=True)
class _Span:
    start: int
    end: int
    kind: str
    priority: int


def _overlap(start: int, end: int, spans: Sequence[tuple[int, int]]) -> bool:
    return any(start < right and end > left for left, right in spans)


@lru_cache(maxsize=2)
def _brand_data(include_extra: bool = True) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Only project-maintained brand metadata; never derive it from test rows."""
    data = json.loads((DATA_DIR / "brands.json").read_text(encoding="utf-8"))
    rows = list(data["brands"])
    extra = DATA_DIR / "brands_extra.json"  # L15: so "Wells Fargo" is kept as a brand, not hidden as a name
    if include_extra and extra.exists():
        rows += json.loads(extra.read_text(encoding="utf-8"))["brands"]
    names, short_codes, sender_ids = [], [], []
    for brand in rows:
        names.append(brand["name"])
        short_codes.extend(brand.get("official_short_codes", []))
        sender_ids.extend(brand.get("official_sender_ids", []))
    return tuple(names), tuple(str(code) for code in short_codes), tuple(sender_ids)


def _literal_spans(text: str, values: Sequence[str]) -> list[tuple[int, int]]:
    return [match.span() for value in values if value
            for match in re.finditer(r"(?<!\w)" + re.escape(value) + r"(?!\w)", text, re.I)]


def _salt() -> str:
    secret = get_settings().PHONE_HASH_SALT
    if secret is None or not secret.get_secret_value().strip():
        raise ValueError("PHONE_HASH_SALT must be configured before phone redaction")
    return secret.get_secret_value()


def hash_phone(number: str, salt: str) -> str:
    """HMAC-SHA256, truncated to 64 bits; normalize US/international formatting.

    Extensions identify the same base phone. Empty salts and invalid numbers
    fail closed; there is no fixed default salt or unsalted fallback.
    """
    if not isinstance(salt, str) or not salt.strip():
        raise ValueError("A non-empty phone hash salt is required")
    base = re.sub(r"\s*(?:ext(?:ension)?\.?|x|\#)\s*\d{1,6}$", "", number.strip(), flags=re.I)
    if not re.fullmatch(r"\+?[\d\s().-]+", base):
        raise ValueError("Invalid phone number")
    digits = "".join(str(unicodedata.digit(char)) for char in base if char.isdecimal())
    if digits.startswith("00"):
        digits = digits[2:]
    if not 7 <= len(digits) <= 15:
        raise ValueError("Phone number must contain 7 to 15 digits")
    if len(digits) == 10:
        digits = "1" + digits
    digest = hmac.new(salt.encode("utf-8"), ("+" + digits).encode("ascii"), hashlib.sha256).hexdigest()[:16]
    return f"<PHONE_HASH_{digest}>"


def _person_span(text: str, start: int, end: int, *, contextual: bool) -> tuple[int, int] | None:
    words = list(re.finditer(_NAME_WORD, text[start:end]))
    stop = _CONTEXT_STOP if contextual else _GLOBAL_STOP
    while words and words[0].group().casefold().rstrip(".") in stop:
        words.pop(0)
    kept = []
    for word in words:
        if word.group().casefold().rstrip(".") in stop:
            break
        kept.append(word)
    if not kept or (not contextual and len(kept) < 2):
        return None
    right = start + kept[-1].end()
    if kept[-1].group().endswith(".") and len(kept[-1].group()) > 2:
        right -= 1
    return start + kept[0].start(), right


def redact(text: str, *, person_names: Sequence[str] = (), core_brands_only: bool = False) -> RedactedMessage:
    """Redact locally and count replaced occurrences, resolving overlapping spans.

    person_names optionally supplies customer names already known locally. It
    is never inferred from held-out data and is not sent outside this function.
    Phone/URL placeholders in untrusted input are rejected, rather than trusted
    as proof of prior redaction. Run once on raw message text. URL numbering
    follows occurrence order; raw_urls excludes trailing prose punctuation.
    """
    if re.search(r"<(?:PHONE_HASH_[^>]*|URL_\d+)>", text):
        raise ValueError("Pre-redacted URL/phone tags are not valid raw message input")
    brands, public_codes, _ = _brand_data(not core_brands_only)
    tags = [match.span() for match in _TAG.finditer(text)]
    brand_spans = _literal_spans(text, brands)
    amount_spans = [match.span() for match in _AMOUNT.finditer(text)]
    deadline_spans = [match.span() for match in _DEADLINE.finditer(text)]
    code_spans = [match.span("code") for match in _SHORT_CODE.finditer(text)] + _literal_spans(text, public_codes)
    protected = tags + brand_spans + amount_spans + deadline_spans + code_spans
    candidates: list[_Span] = []

    def add(start: int, end: int, kind: str, priority: int, *, strong: bool = False) -> None:
        if start < end and not _overlap(start, end, tags if strong else protected):
            candidates.append(_Span(start, end, kind, priority))

    email_spans = [match.span() for match in _EMAIL.finditer(text)]
    for match in _URL.finditer(text):
        start, end = match.span()
        # A dotted email username is not a bare domain. An email *inside* a
        # URL query is instead covered by the outer URL span and never leaks.
        prefix_before_at = text[start:end].split("@", 1)[0]
        has_url_path = any(char in prefix_before_at for char in "/?#")
        if not has_url_path and any(left <= start < right for left, right in email_spans):
            continue
        # Retain sentence punctuation and unmatched closing delimiters.
        while end > start:
            last = text[end - 1]
            chunk = text[start:end]
            if last in ".,;:!?" or (last in ")]}" and chunk.count(last) > chunk.count({")": "(", "]": "[", "}": "{"}[last])):
                end -= 1
            else:
                break
        add(start, end, "URL", 120, strong=True)
    for pattern, kind, priority in ((_EMAIL, "EMAIL", 110), (_ADDRESS, "ADDRESS", 90)):
        for match in pattern.finditer(text):
            add(*match.span(), kind, priority, strong=True)
    for match in _ACCOUNT.finditer(text):
        add(*match.span("digits"), "ACCOUNT_DIGITS", 85, strong=True)
    for match in _CARD.finditer(text):
        add(*match.span(), "ACCOUNT_DIGITS", 80)
    for match in _PHONE.finditer(text):
        # Discard malformed candidates before they can reach hashing/rendering.
        try:
            hash_phone(match.group(), "candidate-validation-only")
        except ValueError:
            continue
        add(*match.span(), "PHONE", 70)
    for match in _DIGITS.finditer(text):
        add(*match.span(), "ACCOUNT_DIGITS", 20)
    for span in _literal_spans(text, person_names):
        add(*span, "PERSON", 65)
    for pattern in _PERSON_CONTEXT:
        for match in pattern.finditer(text):
            span = _person_span(text, *match.span("person"), contextual=True)
            if span:
                add(*span, "PERSON", 60)
    for match in _FULL_NAME.finditer(text):
        span = _person_span(text, *match.span("person"), contextual=False)
        if span:
            add(*span, "PERSON", 50)

    chosen: list[_Span] = []
    for span in sorted(candidates, key=lambda item: (-item.priority, -(item.end-item.start), item.start)):
        if not _overlap(span.start, span.end, [(other.start, other.end) for other in chosen]):
            chosen.append(span)
    counts = RedactionCounts()
    raw_urls, output = [], []
    cursor = 0
    for span in sorted(chosen, key=lambda item: item.start):
        output.append(text[cursor:span.start])
        if span.kind == "URL":
            raw_urls.append(text[span.start:span.end])
            replacement = f"<URL_{len(raw_urls)}>"
        else:
            setattr(counts, span.kind, getattr(counts, span.kind) + 1)
            replacement = hash_phone(text[span.start:span.end], _salt()) if span.kind == "PHONE" else f"<{span.kind}>"
        output.append(replacement)
        cursor = span.end
    output.append(text[cursor:])
    kept = [label for label, present in (("brand", bool(brand_spans)), ("domain", bool(raw_urls)),
                                        ("amount", bool(amount_spans)), ("deadline", bool(deadline_spans)),
                                        ("short_code", bool(code_spans))) if present]
    return RedactedMessage(text_redacted="".join(output), report=RedactionReport(counts=counts, kept=kept), raw_urls=raw_urls)


def redact_sender(raw_sender: str) -> tuple[SenderType, str]:
    """Keep public short codes/known brand IDs; suppress unknown sender text."""
    value = raw_sender.strip()
    if re.fullmatch(r"\d{5,6}", value):
        return SenderType.short_code, value
    if _EMAIL.fullmatch(value):
        return SenderType.email, "<EMAIL>"
    try:
        hash_phone(value, "candidate-validation-only")
    except ValueError:
        pass
    else:
        return SenderType.long_code, hash_phone(value, _salt())
    brands, _, identifiers = _brand_data()
    def normalize(item: str) -> str:
        return re.sub(r"[\W_]", "", item).casefold()
    known = {normalize(item) for item in (*brands, *identifiers)}
    if normalize(value) and normalize(value) in known:
        return SenderType.alphanumeric, value
    sender_type = SenderType.alphanumeric if re.fullmatch(r"[A-Za-z][\w-]{1,31}", value) else SenderType.unknown
    return sender_type, "<UNKNOWN_SENDER>"
