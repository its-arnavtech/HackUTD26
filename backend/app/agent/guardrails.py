"""Guardrails enforced in code. Filled in by L8.

POC_MVP.md section 7.4 and DATA_SPEC.md section 3.5: fixed enums, "very likely"
needs two findings from different tools, classifier/tool disagreement means
`unsure`, at most 3 actions, phone numbers and URLs stripped from text.
"""

from __future__ import annotations

from typing import Any

from app.contracts import AgentResult, ClassifierOutput


def validate_result(raw: dict[str, Any]) -> AgentResult:
    """Parse Nemotron's final JSON against the contract; raise on invalid values. (L8)"""
    raise NotImplementedError("L8: validate result")


def enforce(result: AgentResult, classifier: ClassifierOutput) -> AgentResult:
    """Apply the evidence, disagreement and action rules. (L8)"""
    raise NotImplementedError("L8: enforce guardrails")


def strip_contacts(text: str) -> str:
    """Remove any phone number or URL from model-written text. (L8)"""
    raise NotImplementedError("L8: strip contacts")


def unsure_fallback(evidence_so_far: list[Any]) -> AgentResult:
    """Result returned after a second invalid output. (L8)"""
    raise NotImplementedError("L8: unsure fallback")
