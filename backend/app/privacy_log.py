"""Privacy audit log (L6): what each model and tool received for a message.

Every pipeline run gets a `PrivacyLog`. L3's `JobRunner` binds it around the job,
so anything the job calls can record into it without passing it around:

- L5's tool registry records every tool call by itself: the validated arguments
  plus the parts of the agent input the tool reads (`ToolSpec.reads`).
- The pipeline and the agent record the rest with the module-level helpers,
  which do nothing outside a run and never raise:

      privacy_log.record_redaction(redacted)                     # L9, right after redact()
      privacy_log.record_local("classifier", {"text_redacted": ..., "features": ...})  # L9
      privacy_log.record_model("nemotron", agent_input)          # L8, before the first Nemotron call
      privacy_log.record_tool_result("nemotron", call.to_tool_message())  # L8, each tool result sent back
      privacy_log.record_model("gemini", lookup_input)           # L10

`view(store, message_id)` builds `GET /api/privacy/{id}`. Its `never_sent` list
only names what this module checked against every recorded payload: if a check
finds the item in something that was sent, the item is left out and the leak is
logged (without the value). The UI never claims more than was checked
(POC_MVP 4.4).

Everything lives in L3's in-memory store, for the session only (DATA_SPEC 5).
"""

from __future__ import annotations

import contextvars
import difflib
import json
import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel

from app import contracts as c

if TYPE_CHECKING:
    from app.state import StateStore

log = logging.getLogger(__name__)

Kind = Literal["model", "tool", "local"]

# Recipients that get one merged entry per run (each Nemotron step resends the conversation).
_MERGED_FIELD = "tool_results"


class PrivacyLog:
    """Records for one run of one message. Callable as L5's `on_call` hook."""

    def __init__(self, store: "StateStore", message_id: str, run: int) -> None:
        self.store, self.message_id, self.run = store, message_id, run

    # -- recording ------------------------------------------------------------

    def __call__(self, recipient: c.PrivacyRecipient) -> None:
        self._safe("record", lambda: self.store.add_privacy(self.message_id, self.run, _with_time(recipient)))

    def redaction(self, redacted: c.RedactedMessage) -> None:
        """The redaction step's output. Its report is shown; the text and links are only used for checks."""
        self._safe("redaction", lambda: self.store.set_redaction(self.message_id, self.run, redacted))

    def record(self, recipient: str, kind: Kind, payload: BaseModel | dict[str, Any], received_fields: list[str] | None = None) -> None:
        data = _payload(payload)
        self(c.PrivacyRecipient(recipient=recipient, kind=kind, received_fields=received_fields or list(data), payload=data))

    def tool_result(self, model: str, tool_message: dict[str, Any]) -> None:
        """A tool result sent back to `model`. Added to that model's entry for this run."""

        def go() -> None:
            entry_id, current = self.store.last_privacy(self.message_id, self.run, model)
            message = _payload(tool_message)
            if current is None:
                self(c.PrivacyRecipient(recipient=model, kind="model", received_fields=[_MERGED_FIELD], payload={_MERGED_FIELD: [message]}))
                return
            payload = dict(current.payload)
            payload[_MERGED_FIELD] = [*payload.get(_MERGED_FIELD, []), message]
            fields = current.received_fields if _MERGED_FIELD in current.received_fields else [*current.received_fields, _MERGED_FIELD]
            self.store.update_privacy(entry_id, current.model_copy(update={"payload": payload, "received_fields": fields}))

        self._safe("tool_result", go)

    def _safe(self, what: str, fn) -> None:
        try:
            fn()
        except Exception:  # the privacy log must never break a check
            log.exception("privacy log write failed", extra={"fields": {"what": what, "run": self.run}})


# ---------------------------------------------------------------------------
# The run's log, bound by JobRunner
# ---------------------------------------------------------------------------

_current: contextvars.ContextVar[PrivacyLog | None] = contextvars.ContextVar("privacy_log", default=None)


def current() -> PrivacyLog | None:
    return _current.get()


@contextmanager
def bind(privacy: PrivacyLog) -> Iterator[PrivacyLog]:
    token = _current.set(privacy)
    try:
        yield privacy
    finally:
        _current.reset(token)


def record_redaction(redacted: c.RedactedMessage) -> None:
    if (p := current()) is not None:
        p.redaction(redacted)


def record_model(name: str, payload: BaseModel | dict[str, Any], received_fields: list[str] | None = None) -> None:
    if (p := current()) is not None:
        p.record(name, "model", payload, received_fields)


def record_local(name: str, payload: BaseModel | dict[str, Any], received_fields: list[str] | None = None) -> None:
    if (p := current()) is not None:
        p.record(name, "local", payload, received_fields)


def record_tool_result(model: str, tool_message: dict[str, Any]) -> None:
    if (p := current()) is not None:
        p.tool_result(model, tool_message)


# ---------------------------------------------------------------------------
# GET /api/privacy/{id}
# ---------------------------------------------------------------------------

EMPTY_REPORT = c.RedactionReport(counts=c.RedactionCounts())

NAME = "Your name"
SENDER_NUMBER = "The sender's phone number"
FULL_LINK = "The full link"
ORIGINAL_TEXT = "Your original message"
ACCOUNT_NUMBERS = "Account numbers"
PHONE_NUMBERS = "Phone numbers in the message"
HISTORY = "Your full transaction history"

_URL = re.compile(r"(?:https?://|www\.)\S+", re.I)
_SCHEME = re.compile(r"https?://|www\.", re.I)
_TOKEN_EDGE = re.compile(r"^[^\w]+|[^\w]+$")
_PLACEHOLDER = re.compile(r"<[A-Z][A-Za-z0-9_]*>")  # <PERSON>, <URL_1>, <PHONE_HASH_2ae6...>
_NUMBERISH = re.compile(r"[\d\s().+-]+")


def view(store: "StateStore", message_id: str) -> c.PrivacyView:
    """What was redacted, every recorded recipient (all runs, oldest first) and the checked never-sent list."""
    message = store.get_message(message_id)
    redaction = store.redaction(message_id)
    recipients = store.privacy(message_id)
    return c.PrivacyView(
        message_id=message_id,
        redaction=redaction.report if redaction else EMPTY_REPORT,
        recipients=recipients,
        never_sent=never_sent(message.text, message.sender, redaction, recipients),
    )


def never_sent(raw_text: str, sender: str, redaction: c.RedactedMessage | None, recipients: list[c.PrivacyRecipient]) -> list[str]:
    """Things no recorded payload contains. Each item is checked; a failed check drops it and logs a leak."""
    strings = [s for r in recipients for s in _strings(r.payload)]
    blob = "\n".join(strings)
    hidden = _hidden_tokens(raw_text, redaction.text_redacted) if redaction else []

    checks: list[tuple[str, bool]] = []
    # Names, account digits and anything else redaction replaced (needs the redaction step's output).
    if redaction is not None:
        numbers = [re.sub(r"\D", "", t) for t in hidden if _NUMBERISH.fullmatch(t)]
        words = [t for t in hidden if not _NUMBERISH.fullmatch(t)]
        phones = [d[-10:] for d in numbers if len(d) >= 10]
        accounts = [d for d in numbers if 4 <= len(d) < 10]
        checks.append((NAME, not any(_has_word(blob, w) for w in words)))
        checks.append((ACCOUNT_NUMBERS, not any(_has_digits(blob, d) for d in accounts)))
        if redaction.report.counts.PHONE:
            checks.append((PHONE_NUMBERS, not any(_has_digits(blob, d) for d in phones)))
        if redaction.text_redacted.strip() != raw_text.strip():
            checks.append((ORIGINAL_TEXT, raw_text.strip() not in blob))
    sender_digits = re.sub(r"\D", "", sender)
    if len(sender_digits) >= 10:  # a personal-style long code, not a business short code
        checks.append((SENDER_NUMBER, not _has_digits(blob, sender_digits[-10:])))
    links = [*(redaction.raw_urls if redaction else []), *_URL.findall(raw_text)]
    if links:
        checks.append((FULL_LINK, not _SCHEME.search(blob) and not any(u.rstrip(".,)") in blob for u in links)))
    # Structural: Nessie tools return counts and references, never records (POC_MVP 7.6).
    checks.append((HISTORY, True))

    out = []
    for item, ok in checks:
        if ok:
            out.append(item)
        else:
            log.error("privacy check failed: item reached a recipient", extra={"fields": {"item": item}})
    return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _with_time(r: c.PrivacyRecipient) -> c.PrivacyRecipient:
    return r if r.at is not None else r.model_copy(update={"at": datetime.now(timezone.utc)})


def _payload(payload: BaseModel | dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload, BaseModel):
        return payload.model_dump(mode="json", exclude_none=True)
    return json.loads(json.dumps(payload, default=str))


def _strings(value: Any) -> Iterator[str]:
    """Every string and number value in a payload (keys are field names, not data)."""
    if isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)
    elif isinstance(value, str):
        yield value
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        yield str(value)


def _hidden_tokens(raw: str, redacted: str) -> list[str]:
    """Words of the raw text that redaction replaced with a placeholder (names, digits, emails...)."""
    a, b = raw.split(), redacted.split()
    out: list[str] = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op not in ("replace", "delete"):
            continue
        if op == "replace" and not any(_PLACEHOLDER.search(t) for t in b[j1:j2]):
            continue  # not a redaction (e.g. whitespace or punctuation shifts)
        for token in a[i1:i2]:
            if _URL.match(token):
                continue  # links are checked separately; their domain is kept on purpose
            token = _TOKEN_EDGE.sub("", token)
            if len(token) >= 3 and token not in redacted:
                out.append(token)
    return out


def _has_word(blob: str, word: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(word)}(?!\w)", blob, re.I) is not None


def _has_digits(blob: str, digits: str) -> bool:
    """`digits` in `blob`, allowing common separators between them (214-555-0101, 214.555.0101)."""
    pattern = r"[\s().-]{0,2}".join(re.escape(d) for d in digits)
    return re.search(rf"(?<!\d){pattern}(?!\d)", blob) is not None
