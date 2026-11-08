"""Pipeline: message -> redact -> features -> classify -> agent -> result.

Filled in by L9 (API endpoints and pipeline orchestration). Redaction always runs
first: nothing else sees the raw text (AGENTS.md section 7).

L3's `JobRunner` runs `pipeline_job` on a worker thread; `on_trail` is the
run's `TrailWriter`, so every entry the agent appends shows up in the next poll.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from app.contracts import AgentMode, AgentResult, MessageIn, TrailEntry

if TYPE_CHECKING:
    from app.state import StoredMessage, TrailWriter


def run_pipeline(
    message_id: str,
    message: MessageIn,
    on_trail: Callable[[TrailEntry], None],
    mode: AgentMode = AgentMode.check,
) -> AgentResult:
    """Run one message end to end, appending trail entries as the agent works. (L9)"""
    raise NotImplementedError("L9: pipeline orchestration")


def pipeline_job(message_id: str, message: "StoredMessage", on_trail: "TrailWriter") -> AgentResult:
    """`JobRunner` job: run the pipeline for the message's current mode (check, or recovery after /clicked)."""
    return run_pipeline(message_id, message.as_message_in(), on_trail, mode=message.mode)
