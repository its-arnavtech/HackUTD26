"""System prompt and message builders for Nemotron. Filled in by L8.

Tells Nemotron which tools are relevant to which claims (POC_MVP.md 7.2) while
leaving the decision to it. Built only from DATA_SPEC.md section 3 payloads, and
never from test-split messages.
"""

from __future__ import annotations

from typing import Any

from app.contracts import AgentInput

SYSTEM_PROMPT = ""  # L8


def build_messages(agent_input: AgentInput) -> list[dict[str, Any]]:
    """OpenAI-style chat messages for the first agent turn. (L8)"""
    raise NotImplementedError("L8: prompt builder")
