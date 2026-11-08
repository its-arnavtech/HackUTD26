"""`public_scam_reports` tool. Filled in by L10.

Gemini with Google Search grounding from a fixed template: four questions,
source ranking, stale flag, no phone numbers passed on (DATA_SPEC.md section 4).
Gemini receives only the section 4.1 payload.
"""

from __future__ import annotations

from app.contracts import AgentInput, GeminiInput, PublicScamReportsArgs, PublicScamReportsResult


def lure_phrase_for(scam_category: str) -> str:
    """Generic lure phrase from our own list, picked by category. Never copied from the message. (L10)"""
    raise NotImplementedError("L10: lure phrases")


def build_gemini_input(args: PublicScamReportsArgs) -> GeminiInput:
    """The only data Gemini gets. (L10)"""
    raise NotImplementedError("L10: Gemini input")


def public_scam_reports(args: PublicScamReportsArgs, agent_input: AgentInput) -> PublicScamReportsResult:
    """Cited public reports, brand guidance and recovery source. (L10)"""
    raise NotImplementedError("L10: public_scam_reports")
