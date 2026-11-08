"""Nessie tools. Filled in by A11.

Return summaries with references (`txn_3`), never payee names, account numbers
or merchant names (DATA_SPEC.md 3.2). Only these tools touch account data.
"""

from __future__ import annotations

from app.contracts import (
    AgentInput,
    NessieBillStatusArgs,
    NessieBillStatusResult,
    NessieRecentActivityArgs,
    NessieRecentActivityResult,
    WasThisYouItem,
)


def nessie_recent_activity(args: NessieRecentActivityArgs, agent_input: AgentInput) -> NessieRecentActivityResult:
    """Counts plus flagged items: new payee, transfer above the 30-day median, first-time merchant. (A11)"""
    raise NotImplementedError("A11: nessie_recent_activity")


def nessie_bill_status(args: NessieBillStatusArgs, agent_input: AgentInput) -> NessieBillStatusResult:
    """Last status, last payment date and amount due now for a payee. (A11)"""
    raise NotImplementedError("A11: nessie_bill_status")


def resolve_ref(ref: str) -> WasThisYouItem:
    """App-side details for a reference, shown only to the customer. (A11)"""
    raise NotImplementedError("A11: resolve reference")
