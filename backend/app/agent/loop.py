"""Nemotron agent loop with plan, re-plan and guardrails. Filled in by L8 (recovery: L11).

POC_MVP.md section 7.2: plan logged before any tool runs, at most 6 tool calls,
invalid output retried once, then `unsure` with the evidence so far.
"""

from __future__ import annotations

from collections.abc import Callable

from app.contracts import AgentInput, AgentResult, TrailEntry

MAX_TOOL_CALLS = 6


def run_agent(agent_input: AgentInput, on_trail: Callable[[TrailEntry], None]) -> AgentResult:
    """Plan, call tools, re-plan, and return a guardrail-checked result. (L8)"""
    raise NotImplementedError("L8: agent loop")
