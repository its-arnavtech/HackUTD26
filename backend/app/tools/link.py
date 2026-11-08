"""`check_link` tool (A10, POC_MVP.md 7.6 row 1, DATA_SPEC.md 3.2).

Lexical checks (brand term in domain, edit distance to official domains, TLD,
shortener), RDAP domain age through the cache, and a local blocklist built from
scam-labeled domains in the train split only.

Works on the registered domain from `AgentInput.urls`. The link itself is never
visited, so `final_redirect_domain` stays null.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Optional

from rapidfuzz.distance import Levenshtein

from app.contracts import AgentInput, CheckLinkArgs, CheckLinkResult, ToolName, UrlInfo
from app.integrations.rdap import domain_age_days, lookup_registration
from app.tools.blocklist import load_blocklist
from app.tools.brands import Brand, find_brand, load_brands
from app.tools.domains import RISKY_TLDS, SHORTENERS, normalize_label, split_domain

NEW_DOMAIN_DAYS = 30
MAX_LOOKALIKE_EDITS = 2
MIN_LOOKALIKE_LENGTH = 5

RdapLookup = Callable[[str], Optional[dict[str, Any]]]


def _find_url(agent_input: AgentInput, url_id: str) -> UrlInfo:
    for url in agent_input.urls:
        if url.id == url_id:
            return url
    known = ", ".join(u.id for u in agent_input.urls) or "none"
    raise ValueError(f"unknown url_id {url_id!r} (message has: {known})")


def _official_owner(domain: str, brands: tuple[Brand, ...]) -> Optional[Brand]:
    for brand in brands:
        if any(domain == d or domain.endswith("." + d) for d in brand.official_domains):
            return brand
    return None


def _at_start(term: str, label: str) -> bool:
    import re

    return bool(term) and re.search(r"(?:^|-)" + re.escape(term), label) is not None


def _lookalike(label: str, url: UrlInfo, brands: tuple[Brand, ...]) -> tuple[Optional[Brand], Optional[str]]:
    """The brand a non-official domain imitates and the brand term found, if any."""
    raw = label.lower()
    normalized = normalize_label(label)
    for brand in brands:
        for term in brand.brand_terms:
            # Only at the start of the label or after "-" (L15: no "chase" in "purchase").
            if _at_start(term, raw) or _at_start(normalize_label(term), normalized):
                return brand, term
    for brand in brands:
        for official in brand.official_domains:
            official_label = normalize_label(split_domain(official)[0])
            if len(official_label) < MIN_LOOKALIKE_LENGTH:
                continue
            if Levenshtein.distance(normalized, official_label) <= MAX_LOOKALIKE_EDITS:
                return brand, None
    if url.brand_term_in_domain:
        brand = find_brand(url.brand_term_in_domain, brands)
        if brand:
            return brand, url.brand_term_in_domain
    return None, None


def check_link(
    args: CheckLinkArgs,
    agent_input: AgentInput,
    *,
    rdap_lookup: RdapLookup = lookup_registration,
    blocklist: frozenset[str] | None = None,
    brands: tuple[Brand, ...] | None = None,
) -> CheckLinkResult:
    """Describe the link `args.url_id` from the message's `urls`."""
    url = _find_url(agent_input, args.url_id)
    brands = brands if brands is not None else load_brands()
    blocklist = blocklist if blocklist is not None else load_blocklist()

    label, suffix = split_domain(url.registered_domain)
    domain = f"{label}.{suffix}" if suffix else label
    signals: list[str] = []

    owner = _official_owner(domain, brands)
    lookalike_of: Optional[str] = None
    if owner:
        signals.append(f"official {owner.name} domain")
    else:
        imitated, term = _lookalike(label, url, brands)
        if imitated:
            lookalike_of = imitated.official_domains[0] if imitated.official_domains else None
            if term:
                signals.append(f"{imitated.name} brand term in a domain {imitated.name} doesn't own")
            else:
                signals.append(f"spelled like {lookalike_of} but is a different domain")
        claimed = find_brand(agent_input.sender.claimed_brand, brands) if agent_input.sender.claimed_brand else None
        if claimed and claimed is not imitated:
            signals.append(f"not an official {claimed.name} domain")

    if url.is_shortener or domain in SHORTENERS:
        signals.append("link shortener hides the real destination")
    if suffix in RISKY_TLDS:
        signals.append(f"uncommon top-level domain .{suffix}")
    if label.startswith("xn--"):
        signals.append("uses look-alike characters (punycode)")
    if label.count("-") >= 2:
        signals.append("several hyphens in the domain name")

    on_blocklist = domain in blocklist
    if on_blocklist:
        signals.append("on our list of known scam domains")

    age: Optional[int] = None
    if owner is None:
        record = rdap_lookup(domain)
        age = domain_age_days(record, agent_input.received_at)
        if record is not None and not record.get("found", True):
            signals.append("no registration record found for this domain")
        elif age is not None and age < NEW_DOMAIN_DAYS:
            signals.append(f"domain registered {age} days before the message")

    return CheckLinkResult(
        domain=domain,
        domain_age_days=age,
        on_blocklist=on_blocklist,
        lookalike_of=lookalike_of,
        final_redirect_domain=None,
        signals=signals,
    )
