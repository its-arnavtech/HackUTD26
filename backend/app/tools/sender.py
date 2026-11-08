"""`check_sender` tool (A10, POC_MVP.md 7.6 row 2, DATA_SPEC.md 3.2).

Compares the sender type and claimed brand against `data/brands.json`. Notes never
include a phone number: they reach Nemotron, and the UI never shows numbers from
model output.
"""

from __future__ import annotations

import re

from app.contracts import AgentInput, CheckSenderArgs, CheckSenderResult, SenderType, ToolName
from app.tools.brands import Brand, find_brand, load_brands

# Redaction placeholders such as `<PHONE_HASH_7f3a>` can't be compared with a number.
_PLACEHOLDER = re.compile(r"^<[^<>]+>$")


def _digits(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    return digits[1:] if len(digits) == 11 and digits.startswith("1") else digits


def _matches(sender_type: SenderType, value: str, brand: Brand) -> bool | None:
    """True or False if the sender can be compared with the brand's list, None if it can't."""
    if sender_type == SenderType.short_code:
        return _digits(value) in {_digits(c) for c in brand.official_short_codes}
    if sender_type == SenderType.long_code:
        if _PLACEHOLDER.match(value):
            return None
        return _digits(value) in {_digits(c) for c in brand.official_long_codes}
    if sender_type == SenderType.alphanumeric:
        return value.strip().lower() in {s.lower() for s in brand.official_sender_ids}
    if sender_type == SenderType.email:
        domain = value.rsplit("@", 1)[-1].strip().lower() if "@" in value else ""
        if not domain:
            return None
        return any(domain == d or domain.endswith("." + d) for d in brand.official_domains)
    return None


def _note(sender_type: SenderType, brand: Brand, matched: bool | None) -> str:
    kind = {
        SenderType.short_code: "short code",
        SenderType.long_code: "regular 10-digit phone number",
        SenderType.alphanumeric: "sender name",
        SenderType.email: "email address",
        SenderType.unknown: "unknown sender",
    }[sender_type]
    if matched:
        return f"The sender is one of {brand.name}'s official texting channels listed on its own website."
    if matched is None:
        if sender_type == SenderType.long_code:
            return (
                f"Sent from a personal-style phone number. {brand.name} lists short codes for its texts, "
                "and this sender isn't one of them."
                if brand.official_short_codes
                else f"Sent from a personal-style phone number, which couldn't be compared with {brand.name}'s channels."
            )
        return f"This {kind} couldn't be compared with {brand.name}'s official channels."
    return f"This {kind} isn't one of the official channels {brand.name} lists on its own website."


def check_sender(
    args: CheckSenderArgs,
    agent_input: AgentInput,
    *,
    brands: tuple[Brand, ...] | None = None,
) -> CheckSenderResult:
    """Does the sender match an official channel of the claimed brand?"""
    sender_type = agent_input.sender.type
    brand = find_brand(args.claimed_brand, brands if brands is not None else load_brands())

    if brand is None:
        return CheckSenderResult(
            sender_type=sender_type,
            matches_official_channel=False,
            official_channels_known=False,
            note=f"We have no official channels on file for {args.claimed_brand}, so the sender couldn't be checked.",
        )
    if not brand.has_official_channels and sender_type != SenderType.email:
        return CheckSenderResult(
            sender_type=sender_type,
            matches_official_channel=False,
            official_channels_known=False,
            note=f"{brand.name} doesn't list its texting numbers on its own website, so the sender couldn't be compared.",
        )

    matched = _matches(sender_type, agent_input.sender.value, brand)
    return CheckSenderResult(
        sender_type=sender_type,
        matches_official_channel=bool(matched),
        official_channels_known=True,
        note=_note(sender_type, brand, matched),
    )
