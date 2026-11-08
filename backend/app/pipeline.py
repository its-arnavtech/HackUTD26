"""Pipeline: message -> redact -> features -> classify -> agent -> result (L9).

POC_MVP.md section 5. Redaction always runs first: the classifier, Nemotron and
every tool see only the redacted `AgentInput` (AGENTS.md section 7).

    pipeline = Pipeline()                      # real parts; tests pass fakes
    agent_input, redacted = pipeline.build_input(message_id, message, mode)
    result = pipeline.run(message_id, message, on_trail, mode)
    runner.submit(message_id, pipeline.job)    # L3's JobRunner job

`on_trail` is the run's `TrailWriter`, so every entry the agent writes shows up
in the next poll: the trail fills in live.

**Classifier.** L7's `predict()` when its model file exists. Until it's trained
(`python -m scripts.train_classifier`), A1's baseline with real probabilities.
The baseline takes about 36 s to train, so `Pipeline.warm()` runs at startup.

**Privacy (L6).** The pipeline records what it sends through L6's
`app.privacy_log` hooks: the redaction, and what the classifier received. The
tool registry records tool calls itself and the agent records what Nemotron
received. The hooks do nothing outside a job (L3's runner binds the log).

**Campaigns (A12).** After a check, the message is recorded in the campaign
store once (`record_message`, fingerprints only, no text), so later messages
can match it.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

from app.agent.loop import run_agent
from app.contracts import (
    AgentInput,
    AgentMode,
    AgentResult,
    ClassifierOutput,
    CustomerContext,
    Features,
    MessageIn,
    RedactedMessage,
    SenderInfo,
    TrailEntry,
)
from app.features.extract import detect_claimed_brand, extract_features, extract_urls
from app.privacy.redact import redact, redact_sender

if TYPE_CHECKING:
    from app.state import StoredMessage

from app import privacy_log as _privacy_log  # L6

log = logging.getLogger(__name__)

# The demo customer (POC_MVP 1): Linda, Capital One linked. A16's consent screen doesn't change it yet.
DEMO_CUSTOMER = CustomerContext(linked_bank=True, linked_institutions=["Capital One"])
# Known customer names are redacted locally (A3's `person_names`), so "Linda" never leaves redaction.
DEMO_PERSON_NAMES: tuple[str, ...] = ("Linda",)

AgentFn = Callable[..., AgentResult]
ClassifyFn = Callable[[str, Features], ClassifierOutput]
RecordFn = Callable[[AgentInput], Any]
OnTrail = Callable[[TrailEntry], None]


# ---------------------------------------------------------------------------
# Classifier: L7 when trained, else A1's baseline with real probabilities
# ---------------------------------------------------------------------------

_baseline_lock = threading.Lock()
_baseline_model: Any = None


def _baseline() -> Any:
    """A1's baseline, trained once per process on the train split (about 36 s)."""
    global _baseline_model
    with _baseline_lock:
        if _baseline_model is None:
            from app.classifier.baseline import load_split, train_baseline

            started = time.perf_counter()
            _baseline_model = train_baseline(load_split().train)
            log.info("baseline classifier trained", extra={"fields": {"ms": _ms(started)}})
        return _baseline_model


def _baseline_output(text_redacted: str) -> ClassifierOutput:
    model = _baseline()
    # `_features` is A1's internal; L7's predict() uses it the same way for its baseline score.
    probs = model.clf.predict_proba(model._features([text_redacted]))[0]
    ranked = sorted(zip(model.clf.classes_, probs), key=lambda kv: -kv[1])[:3]
    top3 = [(str(label), float(p)) for label, p in ranked]
    category, score = top3[0]
    return ClassifierOutput(category=category, score=score, top3=top3, baseline_score=score)


def classify(text_redacted: str, features: Features) -> ClassifierOutput:
    """L7's classifier, or the baseline while L7's model file isn't trained."""
    from app.classifier.predict import predict

    try:
        return predict(text_redacted, features)
    except (NotImplementedError, FileNotFoundError) as exc:
        log.info("L7 classifier unavailable, using the baseline", extra={"fields": {"reason": type(exc).__name__}})
        return _baseline_output(text_redacted)


def warm_classifier() -> None:
    """Load L7's model, or train the baseline, before the first check needs it."""
    started = time.perf_counter()
    try:
        from app.classifier.predict import get_model

        get_model()
        source = "l7"
    except (ImportError, NotImplementedError, FileNotFoundError):
        _baseline()
        source = "baseline"
    log.info("classifier warm", extra={"fields": {"source": source, "ms": _ms(started)}})


def _default_record() -> RecordFn:
    from app.tools.campaign import record_message

    return record_message


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


@dataclass
class Pipeline:
    """The message pipeline. Every part can be swapped (tests, L11)."""

    agent: AgentFn = run_agent
    classify: ClassifyFn = classify
    record_campaign: Optional[RecordFn] = field(default_factory=_default_record)
    customer: CustomerContext = field(default_factory=lambda: DEMO_CUSTOMER.model_copy(deep=True))
    person_names: tuple[str, ...] = DEMO_PERSON_NAMES

    def build_input(self, message_id: str, message: MessageIn, mode: AgentMode = AgentMode.check) -> tuple[AgentInput, RedactedMessage]:
        """Raw message -> DATA_SPEC 3.1 `AgentInput`. Redaction runs before anything else sees the text."""
        redacted = redact(message.text, person_names=self.person_names)
        _privacy("record_redaction", redacted)
        sender_type, sender_value = redact_sender(message.sender)

        text = redacted.text_redacted
        urls = extract_urls(redacted)
        features = extract_features(text)
        brand = detect_claimed_brand(text)
        _privacy("record_local", "classifier", {"text_redacted": text, "features": features.model_dump(mode="json")})
        classifier = self.classify(text, features)
        try:  # L15: scam-wave early warning keeps a fingerprint, never the text
            from app import waves

            waves.detector.observe(text, brand=brand, domain=urls[0].registered_domain if urls else None,
                                   category=classifier.category)
        except Exception:  # a wave counter must never break a check
            log.warning("wave observe skipped")

        mode = AgentMode(mode)
        agent_input = AgentInput(
            message_id=message_id,
            mode=mode,
            received_at=message.received_at,
            since=message.received_at if mode == AgentMode.recovery else None,
            sender=SenderInfo(type=sender_type, value=sender_value, claimed_brand=brand),
            text_redacted=text,
            urls=urls,
            features=features,
            classifier=classifier,
            customer_context=self.customer,
        )
        return agent_input, redacted

    def run(self, message_id: str, message: MessageIn, on_trail: OnTrail, mode: AgentMode = AgentMode.check) -> AgentResult:
        """Run one message end to end, appending trail entries as the agent works."""
        started = time.perf_counter()
        agent_input, _ = self.build_input(message_id, message, mode)
        prepared_ms = _ms(started)

        if self.agent is run_agent:  # L14: record each real Nemotron call for the System view
            from app import transcript
            from app.config import get_settings

            chat = transcript.recording_chat(message_id, agent_input.mode.value, get_settings().NEMOTRON_MODEL)
            result = run_agent(agent_input, on_trail, chat=chat)
        else:
            result = self.agent(agent_input, on_trail)

        if agent_input.mode == AgentMode.check and self.record_campaign is not None:
            try:  # campaign counts must never break a check
                self.record_campaign(agent_input)
            except Exception as exc:  # e.g. the campaign DB isn't seeded yet: `python -m scripts.seed_campaigns`
                log.warning("campaign record skipped", extra={"fields": {"error_type": type(exc).__name__, "error": str(exc)[:200]}})
        log.info(
            "pipeline done",
            extra={
                "fields": {
                    "mode": agent_input.mode.value,
                    "category": agent_input.classifier.category,
                    "verdict": result.verdict.value,
                    "prepare_ms": prepared_ms,
                    "ms": _ms(started),
                }
            },
        )
        return result

    def job(self, message_id: str, message: "StoredMessage", on_trail: OnTrail) -> AgentResult:
        """`JobRunner` job: run the message in its current mode (check, or recovery after /clicked)."""
        return self.run(message_id, message.as_message_in(), on_trail, mode=message.mode)

    def warm(self) -> None:
        """Get the classifier ready before the first check (only the real one needs it)."""
        if self.classify is classify:
            try:
                warm_classifier()
            except Exception:  # a failed warm-up just means the first check trains it
                log.exception("classifier warm-up failed")


def _privacy(hook: str, *args: Any) -> None:
    """Call an L6 `privacy_log` hook. Never breaks a check."""
    try:
        getattr(_privacy_log, hook)(*args)
    except Exception:
        log.exception("privacy hook failed", extra={"fields": {"hook": hook}})


def _ms(started: float) -> int:
    return max(0, round((time.perf_counter() - started) * 1000))


# ---------------------------------------------------------------------------
# Module-level entry points (kept for existing callers)
# ---------------------------------------------------------------------------

_default: Pipeline | None = None
_default_lock = threading.Lock()


def default_pipeline() -> Pipeline:
    global _default
    with _default_lock:
        if _default is None:
            _default = Pipeline()
        return _default


def run_pipeline(message_id: str, message: MessageIn, on_trail: OnTrail, mode: AgentMode = AgentMode.check) -> AgentResult:
    """Run one message end to end with the default pipeline."""
    return default_pipeline().run(message_id, message, on_trail, mode)


def pipeline_job(message_id: str, message: "StoredMessage", on_trail: OnTrail) -> AgentResult:
    """`JobRunner` job using the default pipeline."""
    return default_pipeline().job(message_id, message, on_trail)
