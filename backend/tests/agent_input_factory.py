"""Builds DATA_SPEC 3.1 `AgentInput` objects for tool tests."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from app.contracts import AgentInput, SenderType

RECEIVED_AT = "2026-11-08T09:14:00-06:00"


def make_input(
    *,
    domains: tuple[str, ...] = ("capone-verify-alert.com",),
    sender_type: SenderType = SenderType.long_code,
    sender_value: str = "<PHONE_HASH_7f3a>",
    claimed_brand: Optional[str] = "Capital One",
    shortener: bool = False,
    received_at: str = RECEIVED_AT,
) -> AgentInput:
    return AgentInput.model_validate(
        {
            "message_id": "msg_test",
            "mode": "check",
            "received_at": datetime.fromisoformat(received_at),
            "sender": {"type": sender_type, "value": sender_value, "claimed_brand": claimed_brand},
            "text_redacted": "Alert for <PERSON>. Verify now: " + " ".join(f"<URL_{i}>" for i in range(1, len(domains) + 1)),
            "urls": [
                {"id": f"URL_{i}", "registered_domain": d, "is_shortener": shortener, "is_official_brand_domain": False}
                for i, d in enumerate(domains, start=1)
            ],
            "features": {},
            "classifier": {"category": "bank_impersonation", "score": 0.9},
            "customer_context": {"linked_bank": True, "linked_institutions": ["Capital One"]},
        }
    )
