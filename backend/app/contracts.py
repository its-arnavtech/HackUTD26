"""Shared data contracts for SentinelAI.

Every model here mirrors a JSON object in docs/DATA_SPEC.md (section numbers in
the docstrings). `frontend/src/types.ts` mirrors this file exactly.

This file is shared between Arnav and Lavanya. Change it only in a separate PR
titled `[contracts] ...` (AGENTS.md section 4).
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Alias so a field named `date` doesn't shadow the type (PublicReport).
_Date = date


class Contract(BaseModel):
    """Base model: unknown fields are rejected so drift from DATA_SPEC fails loudly."""

    model_config = ConfigDict(extra="forbid", use_enum_values=False)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Verdict(str, Enum):
    """DATA_SPEC 3.3. Shown as "Very likely a scam", "We're not sure", "Likely safe"."""

    likely_scam = "likely_scam"
    unsure = "unsure"
    likely_safe = "likely_safe"


class ConfidenceWords(str, Enum):
    """DATA_SPEC 3.3."""

    very_likely = "very likely"
    likely = "likely"
    not_sure = "not sure"


class Action(str, Enum):
    """DATA_SPEC 3.3. Every action waits for a customer tap."""

    block_sender = "block_sender"
    report_spam = "report_spam"
    call_number_on_card = "call_number_on_card"
    open_official_app = "open_official_app"
    freeze_card = "freeze_card"
    change_password = "change_password"
    alert_trusted_contact = "alert_trusted_contact"
    ignore = "ignore"


class SenderType(str, Enum):
    """DATA_SPEC 3.1."""

    short_code = "short_code"
    long_code = "long_code"
    alphanumeric = "alphanumeric"
    email = "email"
    unknown = "unknown"


class TrailKind(str, Enum):
    """DATA_SPEC 3.4."""

    plan = "plan"
    tool = "tool"
    replan = "replan"
    verdict = "verdict"


class SourceType(str, Enum):
    """DATA_SPEC 4.3."""

    official = "official"
    government = "government"
    news = "news"
    security_vendor = "security_vendor"
    community = "community"


class DemoMode(str, Enum):
    """POC_MVP 7.8."""

    live = "live"
    record = "record"
    replay = "replay"


class AgentMode(str, Enum):
    """DATA_SPEC 3.1."""

    check = "check"
    recovery = "recovery"


class JobStatus(str, Enum):
    """POC_MVP 7.1: status of a message's pipeline run."""

    queued = "queued"
    running = "running"
    done = "done"


class ToolName(str, Enum):
    """DATA_SPEC 3.2: the agent tools (`check_request` added in L15f)."""

    check_link = "check_link"
    check_sender = "check_sender"
    match_campaign = "match_campaign"
    nessie_recent_activity = "nessie_recent_activity"
    nessie_bill_status = "nessie_bill_status"
    public_scam_reports = "public_scam_reports"
    check_request = "check_request"  # L15f: what the message asks you to do (codes, passwords)


class MessageSource(str, Enum):
    """Where a message came from (DATA_SPEC 2; POC_MVP 4.3: authored messages are labeled)."""

    generated = "generated"  # our DeepSeek set (A21)
    handwritten = "handwritten"  # team-written test messages (A21)
    public = "public"  # public real SMS set via Hugging Face (A5)
    scenario = "scenario"
    authored = "authored"
    sms = "sms"  # texted or forwarded to the SentinelAI number (L14)


# ---------------------------------------------------------------------------
# Messages and redaction (DATA_SPEC 2, 5)
# ---------------------------------------------------------------------------


class MessageIn(Contract):
    """Body of `POST /api/messages` (POC_MVP 7.1)."""

    text: str
    sender: str
    received_at: datetime


class Message(Contract):
    """A message from our generated set, the public SMS set, a scenario, or authored.
    A1's loader reads `data/generated/` into this. `category` uses the ids in
    `data/taxonomy.json`. `prompt_set` records which generator prompt set made it
    (train and test use different sets)."""

    message_id: str
    text: str
    sender: str
    received_at: Optional[datetime] = None
    is_scam: Optional[bool] = None
    category: Optional[str] = None
    source: MessageSource = MessageSource.generated
    prompt_set: Optional[str] = None


class RedactionCounts(Contract):
    """DATA_SPEC 5."""

    PERSON: int = 0
    PHONE: int = 0
    ACCOUNT_DIGITS: int = 0
    ADDRESS: int = 0
    EMAIL: int = 0


class RedactionReport(Contract):
    """DATA_SPEC 5: returned with each message, feeds the privacy panel."""

    counts: RedactionCounts
    kept: list[str] = Field(default_factory=list)


class RedactedMessage(Contract):
    """Output of `privacy/redact.py` (A3).

    `raw_urls[i]` is the link replaced by `<URL_{i+1}>`. It stays in memory for
    `features/extract.py` (A9) to describe as `UrlInfo`, and is never sent to any
    model, tool payload or outside service.
    """

    text_redacted: str
    report: RedactionReport
    raw_urls: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Nemotron input (DATA_SPEC 3.1)
# ---------------------------------------------------------------------------


class SenderInfo(Contract):
    type: SenderType
    value: str
    claimed_brand: Optional[str] = None


class UrlInfo(Contract):
    id: str
    registered_domain: str
    is_shortener: bool
    brand_term_in_domain: Optional[str] = None
    is_official_brand_domain: bool


class Features(Contract):
    urgency_deadline: Optional[str] = None
    threat: Optional[str] = None
    requested_action: Optional[str] = None
    asks_for: list[str] = Field(default_factory=list)
    money_amount_claimed: Optional[float] = None


class ClassifierOutput(Contract):
    category: str
    score: float = Field(ge=0, le=1)
    top3: list[tuple[str, float]] = Field(default_factory=list, max_length=3)
    baseline_score: Optional[float] = Field(default=None, ge=0, le=1)


class CustomerContext(Contract):
    linked_bank: bool
    linked_institutions: list[str] = Field(default_factory=list)


class AgentInput(Contract):
    """DATA_SPEC 3.1: the only message-derived payload Nemotron receives."""

    message_id: str
    mode: AgentMode
    received_at: datetime
    since: Optional[datetime] = None
    sender: SenderInfo
    text_redacted: str
    urls: list[UrlInfo] = Field(default_factory=list)
    features: Features
    classifier: ClassifierOutput
    customer_context: CustomerContext

    @model_validator(mode="after")
    def _since_only_in_recovery(self) -> "AgentInput":
        if self.mode == AgentMode.recovery and self.since is None:
            raise ValueError("recovery mode needs `since`")
        if self.mode == AgentMode.check and self.since is not None:
            raise ValueError("`since` is only used in recovery mode")
        return self


# ---------------------------------------------------------------------------
# Tool args and results (DATA_SPEC 3.2)
# ---------------------------------------------------------------------------


class CheckLinkArgs(Contract):
    url_id: str


class CheckLinkResult(Contract):
    domain: str
    domain_age_days: Optional[int] = None
    on_blocklist: bool
    lookalike_of: Optional[str] = None
    final_redirect_domain: Optional[str] = None
    signals: list[str] = Field(default_factory=list)


class CheckSenderArgs(Contract):
    claimed_brand: str


class CheckSenderResult(Contract):
    sender_type: SenderType
    matches_official_channel: bool
    official_channels_known: bool
    note: str


class MatchCampaignArgs(Contract):
    message_id: str


class MatchCampaignResult(Contract):
    campaign_id: Optional[str] = None
    similar_last_24h: int = 0
    first_seen: Optional[datetime] = None
    similarity: float = Field(default=0.0, ge=0, le=1)
    template: Optional[str] = None


class NessieRecentActivityArgs(Contract):
    """Either `days` or `since`, not both."""

    days: Optional[int] = Field(default=None, ge=1)
    since: Optional[datetime] = None

    @model_validator(mode="after")
    def _exactly_one(self) -> "NessieRecentActivityArgs":
        if (self.days is None) == (self.since is None):
            raise ValueError("give exactly one of `days` or `since`")
        return self


class FlaggedItem(Contract):
    """A reference such as `txn_3`. Never payee names, account numbers or merchant names."""

    ref: str
    type: Literal["transfer", "purchase", "bill", "deposit", "withdrawal"]
    amount: float
    new_payee: bool = False
    minutes_after_message: Optional[int] = None
    reason: str


class NessieRecentActivityResult(Contract):
    accounts_checked: int
    items_checked: int
    flagged: list[FlaggedItem] = Field(default_factory=list)


class NessieBillStatusArgs(Contract):
    payee: str


class NessieBillStatusResult(Contract):
    found: bool
    last_status: Optional[str] = None
    last_payment_date: Optional[date] = None
    amount_due_now: Optional[float] = None
    recurring: Optional[bool] = None


# ---------------------------------------------------------------------------
# Gemini (DATA_SPEC 4)
# ---------------------------------------------------------------------------


class GeminiInput(Contract):
    """DATA_SPEC 4.1: the only data Gemini gets. `lure_phrase` comes from our own list."""

    claimed_brand: str
    scam_category: str
    link_domain: Optional[str] = None
    lure_phrase: str


class PublicReport(Contract):
    source_type: SourceType
    publisher: str
    url: str
    date: Optional[_Date] = None
    claim: str
    stale: bool = False


class BrandGuidance(Contract):
    never_asks_by_text: list[str] = Field(default_factory=list)
    source_url: str


class GeminiOutput(Contract):
    """DATA_SPEC 4.3. Also the result of the `public_scam_reports` tool."""

    reports_found: int
    reports: list[PublicReport] = Field(default_factory=list)
    brand_guidance: Optional[BrandGuidance] = None
    domain_reported: bool = False
    recovery_steps_source: Optional[str] = None
    newest_report_age_days: Optional[int] = None


class PublicScamReportsArgs(Contract):
    claimed_brand: str
    scam_category: str
    link_domain: Optional[str] = None


PublicScamReportsResult = GeminiOutput


# ---------------------------------------------------------------------------
# Agent output and trail (DATA_SPEC 3.3, 3.4)
# ---------------------------------------------------------------------------


class Evidence(Contract):
    tool: ToolName
    finding: str


class AgentResult(Contract):
    """DATA_SPEC 3.3: the final JSON Nemotron must return (checked by guardrails)."""

    plan: list[ToolName]
    verdict: Verdict
    confidence_words: ConfidenceWords
    reason: str
    evidence: list[Evidence] = Field(default_factory=list)
    actions: list[Action] = Field(default_factory=list, max_length=3)
    was_this_you: list[str] = Field(default_factory=list)
    replan: bool = False


class TrailEntry(Contract):
    """DATA_SPEC 3.4: one step in "How we checked"."""

    step: int = Field(ge=1)
    kind: TrailKind
    tool: Optional[ToolName] = None
    why: Optional[str] = None
    finding: Optional[str] = None
    ms: Optional[int] = Field(default=None, ge=0)
    at: datetime


# ---------------------------------------------------------------------------
# API views (POC_MVP 7.1)
# ---------------------------------------------------------------------------


class InboxItem(Contract):
    """`GET /api/inbox` item. `text` is the customer's own message, shown only to them."""

    message_id: str
    sender: str
    text: str
    received_at: datetime
    status: JobStatus
    verdict: Optional[Verdict] = None
    confidence_words: Optional[ConfidenceWords] = None
    source: MessageSource = MessageSource.scenario


class WasThisYouItem(Contract):
    """App-side detail for a flagged reference, shown only to the customer (DATA_SPEC 3.2)."""

    ref: str
    type: Literal["transfer", "purchase", "bill", "deposit", "withdrawal"]
    amount: float
    payee: str
    at: datetime


class ResultPoll(Contract):
    """`GET /api/messages/{id}/result`."""

    message_id: str
    status: JobStatus
    mode: AgentMode = AgentMode.check
    trail: list[TrailEntry] = Field(default_factory=list)
    result: Optional[AgentResult] = None
    was_this_you_items: list[WasThisYouItem] = Field(default_factory=list)


class PostMessageResponse(Contract):
    message_id: str


class ClickedResponse(Contract):
    message_id: str
    status: JobStatus
    mode: AgentMode = AgentMode.recovery


class ConfirmRequest(Contract):
    was_me: bool


class ConfirmResponse(Contract):
    ref: str
    was_me: bool
    recorded: bool


class ActionRequest(Contract):
    message_id: str
    action: Action


class ActionResponse(Contract):
    message_id: str
    action: Action
    status: Literal["simulated"] = "simulated"
    note: str


class DemoResetResponse(Contract):
    ok: bool
    inbox_count: int


# ---------------------------------------------------------------------------
# Privacy view (POC_MVP 8, DATA_SPEC 1)
# ---------------------------------------------------------------------------


class PrivacyRecipient(Contract):
    """What one model or tool received for this message."""

    recipient: str
    kind: Literal["model", "tool", "local"]
    received_fields: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    at: Optional[datetime] = None


class PrivacyView(Contract):
    """`GET /api/privacy/{id}`: what was redacted and exactly what each tool and model received."""

    message_id: str
    redaction: RedactionReport
    recipients: list[PrivacyRecipient] = Field(default_factory=list)
    never_sent: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Campaigns (POC_MVP 7.1, 7.6)
# ---------------------------------------------------------------------------


class Campaign(Contract):
    """`GET /api/campaigns` item. Built from anonymized fingerprints only."""

    campaign_id: str
    claimed_brand: Optional[str] = None
    category: str
    domain_pattern: Optional[str] = None
    count_total: int
    count_last_24h: int
    first_seen: datetime
    last_seen: datetime
    template: str
    redacted_example: str
    linked_message_ids: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Metrics (POC_MVP 7.5, DATA_SPEC 7)
# ---------------------------------------------------------------------------


class Scores(Contract):
    precision: float = Field(ge=0, le=1)
    recall: float = Field(ge=0, le=1)
    f1: float = Field(ge=0, le=1)


class CategoryMetrics(Contract):
    category: str
    support: int
    ours: Scores
    baseline: Scores


class OursVsBaseline(Contract):
    ours: float
    baseline: float


class RedactionCost(Contract):
    """Our model's macro F1 on unredacted vs. redacted text."""

    macro_f1_unredacted: float
    macro_f1_redacted: float


class AgentSample(Contract):
    n: int
    share_correct: float = Field(ge=0, le=1)
    share_unsure: float = Field(ge=0, le=1)


class PublicSetMetrics(Contract):
    """Spam recall and FPR on the real public SMS set (DATA_SPEC 7)."""

    dataset: str
    n: int
    spam_recall: OursVsBaseline
    false_positive_rate: OursVsBaseline


class Metrics(Contract):
    """`eval/metrics.json`, served by `GET /api/metrics` for the accuracy page."""

    generated_at: datetime
    split: Literal["test"] = "test"
    n_test: int
    categories: list[CategoryMetrics]
    macro_f1: OursVsBaseline
    false_positive_rate: OursVsBaseline
    public_set: Optional[PublicSetMetrics] = None
    redaction_cost: Optional[RedactionCost] = None
    agent_sample: Optional[AgentSample] = None


class BaselineCategoryMetrics(Contract):
    category: str
    support: int
    precision: float = Field(ge=0, le=1)
    recall: float = Field(ge=0, le=1)
    f1: float = Field(ge=0, le=1)


class BaselineMetrics(Contract):
    """`eval/baseline_metrics.json` written by A1 (gate P1)."""

    generated_at: datetime
    split: Literal["test"] = "test"
    n_test: int
    categories: list[BaselineCategoryMetrics]
    macro_f1: float = Field(ge=0, le=1)
    false_positive_rate: float = Field(ge=0, le=1)


# ---------------------------------------------------------------------------
# Authentication and audit (DATA_SPEC section 8, L13). Only used when AUTH_ENABLED=true.
# Tokens never appear in any of these bodies: they travel in HttpOnly cookies.
# ---------------------------------------------------------------------------


class Role(str, Enum):
    customer = "customer"
    admin = "admin"


class PasswordLoginRequest(Contract):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class TotpRequest(Contract):
    code: str = Field(min_length=6, max_length=8)


class PasskeyCredential(Contract):
    """The browser's `PublicKeyCredential` as JSON (from `@simplewebauthn/browser`)."""

    model_config = ConfigDict(extra="allow")

    id: str = Field(max_length=1024)
    rawId: str = Field(max_length=1024)
    type: Literal["public-key"]
    response: dict[str, Any]


class LoginStep(Contract):
    """Answer to a sign-in step. `mfa_required` means: send the TOTP code next."""

    signed_in: bool
    mfa_required: bool = False


class Me(Contract):
    user_id: str
    username: str
    display_name: str
    role: Role
    passkeys: int = Field(ge=0)


class AuditEventView(Contract):
    """One content-free audit row: no message text, no raw IP, no tokens."""

    id: int
    ts: datetime
    event: str
    actor: str
    target: str
    outcome: Literal["success", "failure", "denied"]
    ip_hash: str
    details: dict[str, Any] = Field(default_factory=dict)


class AuditView(Contract):
    chain_intact: bool
    first_broken_id: Optional[int] = None
    events: list[AuditEventView]


# ---------------------------------------------------------------------------
# check_request (L15f): what the message asks you to do. Local, reads text_redacted only.
# ---------------------------------------------------------------------------


class CheckRequestArgs(Contract):
    """No arguments: it always checks the current message."""


class CheckRequestResult(Contract):
    asks_for_code: bool
    asks_for_password: bool
    asks_to_reply: bool
    phrases: list[str] = Field(default_factory=list, max_length=3)
