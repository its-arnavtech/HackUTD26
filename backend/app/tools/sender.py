"""`check_sender` tool. Filled in by A10.

Compares the sender type and claimed brand against `data/brands.json`.
"""

from __future__ import annotations

from app.contracts import AgentInput, CheckSenderArgs, CheckSenderResult


def check_sender(args: CheckSenderArgs, agent_input: AgentInput) -> CheckSenderResult:
    """Does the sender match an official channel of the claimed brand? (A10)"""
    raise NotImplementedError("A10: check_sender")
