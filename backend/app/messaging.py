"""Talk to SentinelAI from your phone: the conversation, shared by SMS and WhatsApp (L14).

Someone sends a suspicious message; we acknowledge at once, run the normal
pipeline on it (redact → classify → Nemotron agent → guardrails), and send the
verdict when the run finishes. Follow-ups continue the conversation:

    CLICKED   I already tapped the link → recovery re-plan, then "Was this you?"
    YES / NO  answer to "Was this you?" → thanks, or the recovery checklist
    BLOCK     block the sender (simulated; the reply is the customer's consent)
    HELP      the command list

WhatsApp shows these as tap buttons; SMS lists them as words to reply with.
Each channel (`app/sms.py`, `app/whatsapp.py`) only parses its webhook and
delivers replies; everything else lives here.

A first line `From: <sender>` sets the sender the scam claimed (a short code or
brand name), since forwarding loses it.

Privacy and safety:
- Only the channel's servers can call our webhooks (signatures checked) and only
  allow-listed numbers get a reply.
- The customer's number stays in memory, only to send replies. The store, logs
  and audit see only its HMAC (`PHONE_HASH_SALT`); no model or tool ever sees it.
  The forwarded text is redacted like every other message.
- Replies never include a phone number or link from the scam or from model
  output (`strip_contacts`); the only link is our own result page.
- If a check fails or runs too long, the reply says so and tells the customer
  not to tap anything (fail closed).
"""

from __future__ import annotations

import logging
import re
import threading
from concurrent.futures import Future, TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import NamedTuple

from fastapi import Request

from app import contracts as c
from app.agent.guardrails import strip_contacts
from app.auth.deps import DEMO_CUSTOMER_ID, RateLimiter
from app.privacy.redact import hash_phone

log = logging.getLogger(__name__)

MAX_BODY = 1600
CHECK_TIMEOUT_S = 90.0
FORWARDED_SENDER = "unknown"


class Reply(NamedTuple):
    """What to send back. `buttons` are (command, label); SMS turns them into "Reply A or B."."""

    text: str
    buttons: tuple[tuple[str, str], ...] = ()


ACK = Reply("SentinelAI: Checking this now. We'll reply in a moment. Don't tap any links in it meanwhile.")
HELP = Reply(
    "SentinelAI: Forward or paste a message you're unsure about and we'll check it. "
    "After a check you can tell us if you already tapped its link."
)
NO_MESSAGE = Reply("SentinelAI: Send us the message you're worried about first.")
FAILED = Reply("SentinelAI: We couldn't finish checking this message. Until we can, don't tap its links or reply to it.")
BLOCKED = Reply("SentinelAI: Done. We'd block that sender for you (simulated for the demo; nothing was sent).")
YES_REPLY = Reply("SentinelAI: Thanks for confirming. We didn't flag anything else in the activity we checked.")
CHECKING_ACTIVITY = Reply("SentinelAI: Okay. Checking your recent account activity now.")

VERDICT_BUTTONS = (("CLICKED", "I tapped the link"), ("BLOCK", "Block sender"))
YES_NO_BUTTONS = (("NO", "No, not me"), ("YES", "Yes, that was me"))

VERDICT_LABEL = {
    c.Verdict.likely_scam: "Very likely a scam",
    c.Verdict.unsure: "We're not sure about this one",
    c.Verdict.likely_safe: "Likely safe",
}
NEXT_STEP = {
    c.Verdict.likely_scam: "Don't tap the link or reply to it.",
    c.Verdict.unsure: "Don't tap the link until you've checked with the company directly, using its official app or the number on your card.",
    c.Verdict.likely_safe: "",
}
# Same wording as the app's recovery checklist (frontend present.ts).
CHECKLIST = {
    c.Action.freeze_card: "Review your card controls in the official Capital One app (freeze it if needed).",
    c.Action.change_password: "Change your bank password in the official app.",
    c.Action.call_number_on_card: "Call the number on the back of your card and tell them what happened.",
    c.Action.alert_trusted_contact: "Tell someone you trust and ask them to sit with you.",
}
DEFAULT_CHECKLIST = [c.Action.freeze_card, c.Action.change_password, c.Action.call_number_on_card]
_FROM_LINE = re.compile(r"^\s*from\s*[:\-]?\s*([A-Za-z0-9][\w .&'-]{0,31})\s*$", re.IGNORECASE)

COMMANDS = {
    "HELP": "HELP", "INFO": "HELP", "?": "HELP",
    "CLICKED": "CLICKED", "I CLICKED": "CLICKED", "TAPPED": "CLICKED",
    "YES": "YES", "Y": "YES", "NO": "NO", "N": "NO",
    "BLOCK": "BLOCK", "BLOCK SENDER": "BLOCK",
}


def as_sms(reply: Reply) -> str:
    """One SMS: the text, then "Reply CLICKED or BLOCK." for the buttons."""
    if not reply.buttons:
        return reply.text
    return f"{reply.text} Reply {' or '.join(command for command, _ in reply.buttons)}."


def verdict_label(result: c.AgentResult) -> str:
    if result.verdict == c.Verdict.likely_scam and result.confidence_words == c.ConfidenceWords.likely:
        return "Likely a scam"
    return VERDICT_LABEL[result.verdict]


def verdict_reply(result: c.AgentResult, result_url: str) -> Reply:
    parts = [f"SentinelAI: {verdict_label(result)}.", strip_contacts(result.reason).strip()]
    if NEXT_STEP[result.verdict]:
        parts.append(NEXT_STEP[result.verdict])
    parts.append(f"How we checked: {result_url}")
    buttons = VERDICT_BUTTONS if result.verdict != c.Verdict.likely_safe else ()
    return Reply(" ".join(p for p in parts if p), buttons)


def checklist_reply(result: c.AgentResult | None, prefix: str = "SentinelAI: Here's what to do now.") -> Reply:
    steps = [a for a in (result.actions if result else []) if a in CHECKLIST] or DEFAULT_CHECKLIST
    lines = " ".join(f"{i}. {CHECKLIST[a]}" for i, a in enumerate(steps, 1))
    return Reply(f"{prefix} {lines} We never move money for you.")


def was_this_you_reply(item: c.WasThisYouItem, message_at: datetime) -> Reply:
    minutes = int((item.at - message_at).total_seconds() // 60)
    when = f" {minutes} minutes after that message" if minutes >= 0 else ""
    return Reply(f"SentinelAI: We found a ${item.amount:,.2f} {item.type} at {item.payee}{when}. Was this you?", YES_NO_BUTTONS)


def split_sender(body: str) -> tuple[str, str]:
    """`From: 227898` on the first line names the claimed sender (forwarding loses it)."""
    first, _, rest = body.partition("\n")
    match = _FROM_LINE.match(first)
    if match and rest.strip():
        return match.group(1).strip(), rest.strip()
    return FORWARDED_SENDER, body.strip()


def e164(number: str) -> str:
    """WhatsApp sends `12144047631`; SMS sends `+12144047631`. Compare in one form."""
    digits = re.sub(r"\D", "", number)
    return f"+{digits}" if digits else ""


@dataclass
class Conversation:
    number: str  # raw, memory only, to send replies
    message_id: str | None = None
    pending_ref: str | None = None


@dataclass
class MessagingService:
    """Shared conversation state and flow. Subclasses implement `deliver`."""

    public_base_url: str
    phone_salt: str
    allowed: frozenset[str]
    channel: str = "sms"
    timeout_s: float = CHECK_TIMEOUT_S
    conversations: dict[str, Conversation] = field(default_factory=dict)
    limiter: RateLimiter = field(default_factory=lambda: RateLimiter(10))
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def deliver(self, conversation: Conversation, reply: Reply) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    def send(self, conversation: Conversation, reply: Reply) -> None:
        try:
            self.deliver(conversation, reply)
        except Exception as exc:  # noqa: BLE001 - a failed reply must never crash the worker
            log.error("%s reply failed: %s", self.channel, exc)

    def phone_hash(self, number: str) -> str:
        return hash_phone(number, self.phone_salt)

    def result_url(self, message_id: str) -> str:
        return f"{self.public_base_url.rstrip('/')}/r/{message_id}"

    def watch(self, future: Future, on_done) -> None:
        """Wait for a run in a background thread, then call `on_done(finished: bool)`."""

        def _wait() -> None:
            try:
                future.result(timeout=self.timeout_s)
                finished = True
            except FutureTimeout:
                finished = False
            except Exception:  # noqa: BLE001 - the runner already logged it
                finished = False
            try:
                on_done(finished)
            except Exception:  # noqa: BLE001
                log.exception("%s follow-up failed", self.channel)

        threading.Thread(target=_wait, name=f"sentinel-{self.channel}-watch", daemon=True).start()

    # -- the conversation ------------------------------------------------------

    def handle(self, request: Request, number: str, body: str) -> Reply | None:
        """Process one inbound message. Returns the immediate reply, or None for no reply."""
        try:
            actor = f"{self.channel}:{self.phone_hash(number)}"
        except ValueError:
            return None
        if e164(number) not in {e164(n) for n in self.allowed}:
            _audit(request, f"{self.channel}.not_allowed", actor, outcome="denied")
            log.info("%s from a number that isn't allow-listed (ignored)", self.channel)
            return None
        if not self.limiter.check(actor):
            _audit(request, f"{self.channel}.rate_limited", actor, outcome="denied")
            return None

        body = body[:MAX_BODY]
        command = COMMANDS.get(body.strip().upper().rstrip(".!"))
        with self._lock:
            conversation = self.conversations.setdefault(actor, Conversation(number=number))
            conversation.number = number

        if command == "HELP":
            return HELP
        if command == "CLICKED":
            return self._clicked(request, conversation, actor)
        if command in ("YES", "NO"):
            return self._answer(request, conversation, actor, command == "YES")
        if command == "BLOCK":
            if not conversation.message_id:
                return NO_MESSAGE
            _audit(request, f"{self.channel}.action", actor, action="block_sender")
            log.info("action requested by %s (simulated)", self.channel, extra={"fields": {"action": "block_sender"}})
            return BLOCKED
        if not body.strip():
            return HELP
        return self._check(request, conversation, actor, body)

    def _check(self, request: Request, conversation: Conversation, actor: str, body: str) -> Reply:
        store = request.app.state.store
        sender, text = split_sender(body)
        message = c.MessageIn(text=text, sender=sender, received_at=datetime.now(timezone.utc))
        message_id = store.add_message(message, source=c.MessageSource.sms, owner_id=DEMO_CUSTOMER_ID)
        conversation.message_id, conversation.pending_ref = message_id, None
        future = request.app.state.runner.submit(message_id, _job(request))
        _audit(request, f"{self.channel}.check", actor, message_id=message_id)

        def done(finished: bool) -> None:
            poll = store.poll(message_id)
            if not finished or poll.result is None:
                self.send(conversation, FAILED)
                return
            self.send(conversation, verdict_reply(poll.result, self.result_url(message_id)))

        self.watch(future, done)
        return ACK

    def _clicked(self, request: Request, conversation: Conversation, actor: str) -> Reply:
        message_id = conversation.message_id
        if not message_id:
            return NO_MESSAGE
        store = request.app.state.store
        future = request.app.state.runner.submit(message_id, _job(request), mode=c.AgentMode.recovery)
        _audit(request, f"{self.channel}.clicked", actor, message_id=message_id)
        received_at = store.get_message(message_id).received_at

        def done(finished: bool) -> None:
            poll = store.poll(message_id)
            if not finished or poll.result is None:
                self.send(conversation, FAILED)
                return
            if poll.was_this_you_items:
                item = poll.was_this_you_items[0]
                conversation.pending_ref = item.ref
                self.send(conversation, was_this_you_reply(item, received_at))
            else:
                self.send(conversation, checklist_reply(
                    poll.result, "SentinelAI: We didn't find new activity since that message in what we checked. Still, here's what to do."))

        self.watch(future, done)
        return CHECKING_ACTIVITY

    def _answer(self, request: Request, conversation: Conversation, actor: str, was_me: bool) -> Reply:
        if not conversation.message_id or not conversation.pending_ref:
            return HELP
        store = request.app.state.store
        store.confirm_transaction(conversation.pending_ref, was_me, owner_id=DEMO_CUSTOMER_ID)
        _audit(request, f"{self.channel}.confirm", actor, was_me=was_me)
        conversation.pending_ref = None
        return YES_REPLY if was_me else checklist_reply(store.poll(conversation.message_id).result)


def _job(request: Request):
    return request.app.state.job_override or request.app.state.pipeline.job


def _audit(request: Request, event: str, actor: str, outcome: str = "success", **details) -> None:
    ctx = request.app.state.auth
    if ctx is not None:
        ctx.store.audit.record(event, actor=actor, outcome=outcome, details=details)
