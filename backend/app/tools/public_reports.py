"""`public_scam_reports` tool. Filled in by L10.

Gemini with Google Search grounding from a fixed template: four questions,
source ranking, stale flag, no phone numbers passed on (DATA_SPEC.md section 4).
Gemini receives only the section 4.1 payload.
"""

from __future__ import annotations

import ipaddress
import json
import re

from app.config import DATA_DIR
from app.contracts import AgentInput, GeminiInput, PublicScamReportsArgs, PublicScamReportsResult

LURES = {
    "bank_impersonation": "account locked, verify by link",
    "billing_scam": "bill overdue, pay by link",
    "delivery_scam": "parcel delayed, update delivery details",
    "account_security": "account security warning, share a verification code",
    "toll_government": "unpaid toll or government fee, pay by link",
    "prize_refund": "unexpected prize or refund, claim by link",
    "job_offer": "unexpected job offer, upfront payment requested",
    "conversation_lure": "unexpected personal conversation, request for money",
    "legit": "unexpected text alert",
}


def lure_phrase_for(scam_category: str) -> str:
    """Generic lure phrase from our own list, picked by category. Never copied from the message. (L10)"""
    if scam_category not in LURES:
        raise ValueError("Unknown scam category")
    return LURES[scam_category]


def build_gemini_input(args: PublicScamReportsArgs) -> GeminiInput:
    """The only data Gemini gets. (L10)"""
    from app.tools.brands import load_brands  # core + brands_extra.json (L15)

    brands = {brand.name for brand in load_brands()}
    if args.claimed_brand not in brands | {"Unknown brand"}:
        raise ValueError("Unknown claimed brand")
    domain = args.link_domain
    if domain:
        domain = domain.lower().rstrip(".")
        if len(domain) > 253 or not re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", domain):
            raise ValueError("Expected a bare registered domain")
        try:
            ipaddress.ip_address(domain)
        except ValueError:
            pass
        else:
            raise ValueError("Expected a domain, not an IP address")
    return GeminiInput(claimed_brand=args.claimed_brand, scam_category=args.scam_category,
                       link_domain=domain, lure_phrase=lure_phrase_for(args.scam_category))


def public_scam_reports(args: PublicScamReportsArgs, agent_input: AgentInput) -> PublicScamReportsResult:
    """Cited public reports, brand guidance and recovery source. (L10)"""
    from app.integrations.gemini import grounded_search
    # Model-supplied tool arguments cannot smuggle arbitrary strings into the
    # lookup. Use the pipeline's permitted brand/category/parsed domain instead.
    permitted = PublicScamReportsArgs(
        claimed_brand=agent_input.sender.claimed_brand or "Unknown brand",
        scam_category=agent_input.classifier.category,
        link_domain=agent_input.urls[0].registered_domain if agent_input.urls else None,
    )
    return grounded_search(build_gemini_input(permitted))
