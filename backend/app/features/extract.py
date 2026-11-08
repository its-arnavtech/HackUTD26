"""Local A9 features (DATA_SPEC 3.1); never follow links or send message data out.

Call after A3 redaction. Outputs contain domain metadata, fixed vocabulary,
normalized deadlines and a numeric amount; never URL paths, queries, userinfo,
contact numbers, or copied free-form message fragments. Rules are heuristics,
not verdicts. No evaluation-set rows are used to define them.
"""
from __future__ import annotations

import ipaddress
import json
import math
import re
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from urllib.parse import urlsplit

import idna
from tldextract import TLDExtract

from app.config import DATA_DIR
from app.contracts import Features, RedactedMessage, UrlInfo

# Explicitly disable HTTP and disk cache. Private suffixes keep tenant boundaries
# (e.g. tenant.github.io). Reserved synthetic suffixes are handled locally too.
_SUFFIXES = TLDExtract(cache_dir=None, suffix_list_urls=(), include_psl_private_domains=True,
                      extra_suffixes=("example", "test", "invalid"))
_SHORTENERS = frozenset({"bit.ly", "t.co", "tinyurl.com", "goo.gl", "ow.ly", "is.gd",
                         "rb.gy", "cutt.ly", "shorturl.at", "rebrand.ly", "buff.ly"})
# Capone is the domain spelling explicitly illustrated by DATA_SPEC 3.1.
_ALIASES = {"Capital One": ("capone",), "T-Mobile": ("tmobile",)}


@dataclass(frozen=True)
class _Brand:
    name: str
    domains: tuple[str, ...]
    terms: tuple[str, ...]
    mention: re.Pattern[str]


def _normalize_host(value: str) -> str:
    if not value or value.endswith("..") or "%" in value:
        raise ValueError("Invalid URL metadata")
    value = value.rstrip(".")
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return idna.encode(value, uts46=True, std3_rules=True).decode("ascii").lower()


@lru_cache(maxsize=2)
def _brands(include_extra: bool = False) -> tuple[_Brand, ...]:
    """Project registry; restart the process after registry changes.

    `include_extra` adds `brands_extra.json` (L15) for brand detection on new messages. The
    campaign matcher and URL fingerprints use the core registry only, so A12's calibration holds.
    """
    data = json.loads((DATA_DIR / "brands.json").read_text(encoding="utf-8"))
    rows = list(data["brands"])
    extra_path = DATA_DIR / "brands_extra.json"
    if include_extra and extra_path.exists():
        rows += json.loads(extra_path.read_text(encoding="utf-8"))["brands"]
    result = []
    for row in rows:
        name = row["name"]
        domains = tuple(_normalize_host(value) for value in row.get("official_domains", []))
        aliases = (*_ALIASES.get(name, ()), *row.get("aliases", []))
        names = (name, *aliases)
        variants = [r"[\s_-]*".join(re.escape(word) for word in re.findall(r"[^\W_]+", variant))
                    for variant in names]
        mention = re.compile(r"(?<!\w)(?:" + "|".join(variants) + r")(?!\w)", re.I)
        terms = {re.sub(r"[\s_]", "", variant.casefold()) for variant in names}
        terms.update(_SUFFIXES(domain).domain for domain in domains)
        terms.update(term.replace("-", "") for term in tuple(terms))
        result.append(_Brand(name, domains, tuple(sorted((t for t in terms if len(t) >= 3), key=lambda t: (-len(t), t))), mention))
    return tuple(result)


def _at_label_start(term: str, host: str) -> bool:
    """`term` begins at the start of the host or right after "." or "-" (L15: no "chase" in "purchase")."""
    return re.search(r"(?:^|[.\-])" + re.escape(term), host) is not None


def detect_claimed_brand(text_redacted: str, *, core_only: bool = False) -> str | None:
    """First registry-name/alias mention in the redacted body, not in a URL.

    New messages are checked against core + extra brands (L15); the campaign matcher passes
    `core_only=True` so its fingerprints match what it was calibrated on.
    """
    mentions = [(match.start(), index, brand.name) for index, brand in enumerate(_brands(not core_only))
                if (match := brand.mention.search(text_redacted)) is not None]
    return min(mentions)[2] if mentions else None


def _url_host(raw_url: str) -> str:
    try:
        if re.search(r"[\x00-\x20\x7f]", raw_url):
            raise ValueError
        has_scheme = re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", raw_url)
        candidate = raw_url if has_scheme or raw_url.startswith("//") else "//" + raw_url
        parsed = urlsplit(candidate)
        if parsed.scheme.lower() not in {"", "http", "https"} or not parsed.hostname:
            raise ValueError
        if not has_scheme and parsed.username is not None:
            raise ValueError  # A bare email/mailto value is not an HTTP URL.
        _ = parsed.port  # Validate a supplied port, but never return it.
        return _normalize_host(parsed.hostname)
    except (ValueError, UnicodeError, idna.IDNAError):
        # Never include an untrusted URL or parse exception's input in the error.
        raise ValueError("Invalid URL metadata") from None


def _registered_domain(host: str) -> str:
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        parsed = _SUFFIXES(host)
        # An unlisted suffix is not evidence of registration or safety. Use only
        # the final two labels as a conservative local description.
        return parsed.top_domain_under_public_suffix or ".".join(host.split(".")[-2:])


def extract_urls(redacted: RedactedMessage) -> list[UrlInfo]:
    """Describe A3's URL occurrences in order, returning no raw URL components.

    Official-domain status is relative to the first claimed brand if present;
    otherwise any registered brand may match. It is a lexical flag, not a safety
    verdict, registration check, redirect resolution or reputation lookup.
    """
    tags = re.findall(r"<URL_(\d+)>", redacted.text_redacted)
    if tags != [str(i) for i in range(1, len(redacted.raw_urls) + 1)]:
        raise ValueError("URL placeholders do not match the private URL list")
    brands = _brands()
    claimed = detect_claimed_brand(redacted.text_redacted, core_only=True)
    relevant = [brand for brand in brands if claimed is None or brand.name == claimed]
    output = []
    for index, raw_url in enumerate(redacted.raw_urls, start=1):
        host = _url_host(raw_url)
        domain = _registered_domain(host)
        terms = sorted({term for brand in brands for term in brand.terms}, key=lambda term: (-len(term), term))
        brand_term = next((term for term in terms if _at_label_start(term, host)), None)
        if brand_term is None:
            # Hyphen-free fallback ("capital-one" written "capitalone") only for long, distinctive terms.
            compact_host = re.sub(r"[.-]", "", host)
            brand_term = next((term for term in terms if len(term) >= 7 and term.replace("-", "") in compact_host), None)
        official = any(host == allowed or host.endswith("." + allowed)
                       for brand in relevant for allowed in brand.domains)
        output.append(UrlInfo(id=f"URL_{index}", registered_domain=domain,
                              is_shortener=domain in _SHORTENERS,
                              brand_term_in_domain=brand_term,
                              is_official_brand_domain=official))
    return output


# Fixed vocabulary for Features. Context checks conservatively suppress nearby
# negated instructions. These are lexical hints; L7/A13 measure their usefulness.
_NEGATION = re.compile(r"\b(?:never|not|don't|do\s+not|won't|no\s+need\s+to)\b", re.I)
_CLAUSE_BREAK = re.compile(r"[!?;\n]|(?<!\d)\.(?!\d)|\b(?:but|however|instead)\b", re.I)
_VERIFY = re.compile(r"\b(?:verify|confirm|unlock|secure\s+your\s+account|update\s+(?:your\s+)?(?:account|payment|details))\b", re.I)
_LOGIN = re.compile(r"\b(?:log\s+in|sign\s+in|login\s+now)\b", re.I)
_PAY = re.compile(r"\b(?:pay|make\s+(?:a\s+)?payment|settle\s+(?:your\s+|the\s+)?(?:bill|balance|fee)|send\s+(?:us\s+)?money)\b", re.I)
_REPLY = re.compile(r"\b(?:reply|text\s+(?:back|yes|no|stop)|send\s+(?:us\s+)?(?:your\s+)?(?:code|otp))\b", re.I)
_CLICK = re.compile(r"\b(?:click|tap|visit|follow\s+(?:this|the)\s+link|claim|redeem|open\s+(?:this|the)\s+link)\b", re.I)
_CALL = re.compile(r"\b(?:call|phone)\b", re.I)
_OFFICIAL_APP = re.compile(r"\b(?:open|use|check)\s+(?:your\s+|the\s+)?(?:official\s+)?(?:bank(?:ing)?\s+)?app\b", re.I)
_DOWNLOAD = re.compile(r"\b(?:download|install)\s+(?:(?:this|the|our|an)\s+)?(?:app|application|software)\b", re.I)
_ASK_VERB = re.compile(r"\b(?:enter|provide|send|share|reply|confirm|verify|submit|give|tell|update|type|need|request|ask(?:ing)?(?:\s+for)?)\b", re.I)
_ASK_NOUNS = (
    ("password", re.compile(r"\bpassword\b", re.I)),
    ("one_time_code", re.compile(r"\b(?:(?:one[- ]time|verification|security|access|login|2fa)\s+(?:code|password)|otp|passcode|code)\b", re.I)),
    ("card_details", re.compile(r"\b(?:card\s+(?:number|details|digits)|cvv|cvc)\b", re.I)),
    ("account_details", re.compile(r"\b(?:account\s+(?:number|details|digits)|routing\s+number|iban)\b", re.I)),
    ("personal_information", re.compile(r"\b(?:ssn|social\s+security|date\s+of\s+birth|full\s+name|address)\b", re.I)),
)
_THREATS = (
    ("account_lock", re.compile(r"\b(?:account|card)\b[^.!?;\n]{0,45}\b(?:lock(?:ed)?|block(?:ed)?|suspend(?:ed)?|(?:freeze|frozen))\b|\b(?:lock(?:ed)?|block(?:ed)?|suspend(?:ed)?)\s+(?:your\s+)?(?:account|card)\b", re.I)),
    ("service_suspension", re.compile(r"\b(?:service|line|phone|mobile)\b[^.!?;\n]{0,45}\b(?:suspend(?:ed)?|disconnect(?:ed)?|shut\s*off|cut\s*off)\b|\b(?:suspension|disconnection)\b", re.I)),
    ("account_deletion", re.compile(r"\baccount\b[^.!?;\n]{0,35}\bdelet(?:e|ed|ion)\b", re.I)),
    ("payment_penalty", re.compile(r"\b(?:late\s+fee|penalty|fine)\b", re.I)),
    ("legal_action", re.compile(r"\b(?:arrest|warrant|lawsuit|prosecution|legal\s+action)\b", re.I)),
)
_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
            "eight": 8, "nine": 9, "ten": 10, "twelve": 12, "twenty-four": 24}
_NUMBER = r"(?:\d{1,5}|one|two|three|four|five|six|seven|eight|nine|ten|twelve|twenty-four)"
_DURATION = re.compile(r"\b(?:within|in|next)\s+(?P<number>" + _NUMBER + r")\s*(?P<unit>seconds?|minutes?|mins?|hours?|hrs?|days?|weeks?)\b", re.I)
_REMAINING = re.compile(r"\b(?P<number>" + _NUMBER + r")\s*(?P<unit>seconds?|minutes?|mins?|hours?|hrs?|days?|weeks?)\s+(?:left|remaining)\b", re.I)
_FIXED_DEADLINE = re.compile(r"\b(?:today|tonight|midnight|immediately|now|asap)\b", re.I)
_BY_DEADLINE = re.compile(r"\bby\s+(?P<deadline>midnight|noon|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday|\d{4}-\d{2}-\d{2})\b", re.I)
_AMOUNT_NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?"
_MONEY = re.compile(r"(?:[$£€]\s*(?P<prefix>" + _AMOUNT_NUMBER + r")(?![\d,]|\.\d)|\b(?P<suffix>" + _AMOUNT_NUMBER + r")\s*(?:USD|GBP|EUR)\b)", re.I)


def _prefix(text: str, start: int, limit: int = 72) -> str:
    window = text[max(0, start-limit):start]
    boundaries = list(_CLAUSE_BREAK.finditer(window))
    return window[boundaries[-1].end():] if boundaries else window


def _positive(pattern: re.Pattern[str], text: str) -> list[re.Match[str]]:
    return [match for match in pattern.finditer(text)
            if not _NEGATION.search(_prefix(text, match.start()) + match.group())]


def _deadline(text: str, has_action_or_threat: bool) -> str | None:
    if not has_action_or_threat and not re.search(r"\b(?:expir\w*|due|deadline|left|remaining|urgent)\b", text, re.I):
        return None
    for pattern in (_DURATION, _REMAINING):
        for match in _positive(pattern, text):
            number = match["number"].casefold()
            count = int(number) if number.isdigit() else _NUMBERS[number]
            unit = match["unit"].casefold().rstrip("s")
            unit = {"hr": "hour", "min": "minute"}.get(unit, unit)
            return f"{count} {unit if count == 1 else unit + 's'}"
    by = _positive(_BY_DEADLINE, text)
    if by:
        return "by " + by[0]["deadline"].casefold()
    fixed = _positive(_FIXED_DEADLINE, text)
    return fixed[0].group().casefold() if fixed else None


def extract_features(text_redacted: str) -> Features:
    """Canonical lexical hints from redacted text only; no URL metadata is read.

    Threat/action and asks_for values are documented by the constants above.
    Account verification at a link infers a login request. money_amount_claimed
    is the first explicit currency-denominated magnitude, without conversion.
    """
    verify = bool(_positive(_VERIFY, text_redacted) or _positive(_LOGIN, text_redacted))
    pay = bool(_positive(_PAY, text_redacted))
    reply = bool(_positive(_REPLY, text_redacted))
    link = bool(re.search(r"<URL_[1-9]\d*>", text_redacted))
    asks = []
    if _positive(_LOGIN, text_redacted) or (verify and link and re.search(r"\baccount\b", text_redacted, re.I)):
        asks.append("login")
    for category, pattern in _ASK_NOUNS:
        for match in pattern.finditer(text_redacted):
            prefix = _prefix(text_redacted, match.start())
            if _ASK_VERB.search(prefix) and not _NEGATION.search(prefix + match.group()):
                asks.append(category)
                break
    if pay:
        asks.append("payment")
    threat = next((name for name, pattern in _THREATS if _positive(pattern, text_redacted)), None)
    if _positive(_OFFICIAL_APP, text_redacted):
        action = "open_official_app"
    elif reply and "one_time_code" in asks:
        action = "reply_with_code"
    elif _positive(_DOWNLOAD, text_redacted):
        action = "download_app"
    elif reply:
        action = "reply"
    elif pay:
        action = "click_link_and_pay" if link else "make_payment"
    elif verify or asks:
        action = "click_link_and_verify" if link else ("verify_account" if verify else "share_credentials")
    elif link and _positive(_CLICK, text_redacted):
        action = "click_link"
    elif _positive(_CALL, text_redacted) and ("<PHONE_HASH_" in text_redacted or re.search(r"\bnumber\b", text_redacted, re.I)):
        action = "call_number"
    else:
        action = None
    money = None
    if (match := _MONEY.search(text_redacted)) is not None:
        value = float(Decimal((match["prefix"] or match["suffix"]).replace(",", "")))
        if math.isfinite(value):
            money = value
    return Features(urgency_deadline=_deadline(text_redacted, bool(action or threat)), threat=threat,
                    requested_action=action, asks_for=asks, money_amount_claimed=money)
