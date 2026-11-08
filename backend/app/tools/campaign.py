"""Campaign store, seeding and `match_campaign`. Filled in by A12.

Fingerprint = registered-domain pattern + hash of a normalized wording template
+ claimed brand + category. SQLite stores fingerprints only. Seeded from the
train split; threshold set on the validation split.
"""

from __future__ import annotations

from app.contracts import AgentInput, Campaign, MatchCampaignArgs, MatchCampaignResult, Message


def fingerprint(agent_input: AgentInput) -> dict[str, str]:
    """Anonymized fingerprint of one message. (A12)"""
    raise NotImplementedError("A12: fingerprint")


def seed_campaigns(train_set: list[Message]) -> int:
    """Build the campaign store from the train split. Returns fingerprints stored. (A12)"""
    raise NotImplementedError("A12: seed campaigns")


def list_campaigns() -> list[Campaign]:
    """Campaigns for `GET /api/campaigns`. (A12)"""
    raise NotImplementedError("A12: list campaigns")


def match_campaign(args: MatchCampaignArgs, agent_input: AgentInput) -> MatchCampaignResult:
    """Nearest campaign, its 24-hour count and similarity. (A12)"""
    raise NotImplementedError("A12: match_campaign")
