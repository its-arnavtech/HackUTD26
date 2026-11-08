"""Domain helpers shared by `check_link` and the blocklist builder."""

from __future__ import annotations

import re
from functools import lru_cache

import tldextract

# Bundled public suffix snapshot only: never fetch the list at runtime.
_extract = tldextract.TLDExtract(suffix_list_urls=())

URL_RE = re.compile(r"(?:https?://)?(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s]*)?", re.IGNORECASE)

SHORTENERS = frozenset(
    {"bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "is.gd", "buff.ly", "rebrand.ly", "cutt.ly", "shorturl.at", "rb.gy", "t.ly", "tiny.cc", "s.id"}
)

# TLDs that are cheap to register and common in smishing; a weak signal on its own.
RISKY_TLDS = frozenset(
    {"xyz", "top", "click", "info", "live", "online", "site", "shop", "icu", "buzz", "vip", "cyou", "rest", "support", "help", "link", "work", "life", "sbs", "cfd"}
)

_HOMOGLYPHS = (("rn", "m"), ("vv", "w"), ("0", "o"), ("1", "l"), ("3", "e"), ("5", "s"), ("7", "t"), ("4", "a"))


@lru_cache(maxsize=1024)
def split_domain(host_or_url: str) -> tuple[str, str]:
    """`(label, suffix)` of the registered domain, e.g. `("capone-verify-alert", "com")`."""
    parts = _extract(host_or_url.lower())
    return parts.domain, parts.suffix


def registered_domain(host_or_url: str) -> str:
    label, suffix = split_domain(host_or_url)
    return f"{label}.{suffix}" if label and suffix else label


def normalize_label(label: str) -> str:
    """Lowercase, hyphens removed, common look-alike characters mapped back (`capita1-0ne` -> `capitalone`)."""
    out = label.lower().replace("-", "")
    for fake, real in _HOMOGLYPHS:
        out = out.replace(fake, real)
    return out


def domains_in_text(text: str) -> list[str]:
    """Registered domains of every link-like string in `text`, in order, without duplicates."""
    seen: dict[str, None] = {}
    for match in URL_RE.finditer(text):
        domain = registered_domain(match.group(0))
        if "." in domain:
            seen.setdefault(domain, None)
    return list(seen)
