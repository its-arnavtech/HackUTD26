"""`check_link` tool. Filled in by A10.

Lexical checks (brand term in domain, edit distance to official domains, TLD,
shortener), RDAP domain age through the cache, and a local blocklist built from
scam-labeled domains in the train split only (POC_MVP.md 7.6).
"""

from __future__ import annotations

from app.contracts import AgentInput, CheckLinkArgs, CheckLinkResult


def check_link(args: CheckLinkArgs, agent_input: AgentInput) -> CheckLinkResult:
    """Describe the link `args.url_id` from the message's `urls`. (A10)"""
    raise NotImplementedError("A10: check_link")
