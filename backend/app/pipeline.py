"""Pipeline: message -> redact -> features -> classify -> agent -> result.

Filled in by L9 (API endpoints and pipeline orchestration). Redaction always runs
first: nothing else sees the raw text (AGENTS.md section 7).
"""

from __future__ import annotations

from collections.abc import Callable

from app.contracts import AgentMode, AgentResult, MessageIn, TrailEntry


def run_pipeline(
    message_id: str,
    message: MessageIn,
    on_trail: Callable[[TrailEntry], None],
    mode: AgentMode = AgentMode.check,
) -> AgentResult:
    """Run one message end to end, appending trail entries as the agent works. (L9)"""
    raise NotImplementedError("L9: pipeline orchestration")
