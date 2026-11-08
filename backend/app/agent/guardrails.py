"""Guardrails enforced in code (L8).

POC_MVP.md section 7.4 and DATA_SPEC.md section 3.5:

- Verdict, confidence and action values must come from the fixed enums.
  `validate_result` rejects anything else, so the loop can retry once.
- "Very likely" needs findings from at least two different tools.
- If the classifier and the tools disagree, the verdict is `unsure`.
- At most 3 actions, all from the fixed list (each still waits for a tap).
- Phone numbers and links are stripped from model-written text, so the UI never
  shows a contact that came from model output (AGENTS.md section 7).

`apply_guardrails` returns the corrected result plus a short note for each
change, so the trail can say what code overrode. `enforce` returns only the
result.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from typing import Any

from pydantic import ValidationError

from app.contracts import (
    Action,
    AgentResult,
    ClassifierOutput,
    ConfidenceWords,
    Evidence,
    ToolName,
    Verdict,
)

log = logging.getLogger(__name__)

MAX_ACTIONS = 3
# A classifier at or above this score "says scam" for the disagreement rule.
CLASSIFIER_SCAM_SCORE = 0.7
LEGIT_CATEGORY = "legit"  # data/taxonomy.json

# Same wording as state.FAILED_REASON (POC_MVP 4.4: say what happened, never reassure).
UNSURE_REASON = "We couldn't finish checking this message. Until we can, don't tap its links or reply to it."
DISAGREE_REASON = "Our checks gave mixed signals about this message, so we can't say either way. Don't tap its links or reply to it."
_EMPTY_REASON = {
    Verdict.likely_scam: "This message shows signs of a scam. Don't tap its links or reply to it.",
    Verdict.unsure: "We can't say either way about this message. Don't tap its links or reply to it.",
    Verdict.likely_safe: "We checked this message and found no signs of a scam.",
}

# ---------------------------------------------------------------------------
# Contact stripping
# ---------------------------------------------------------------------------

_TLDS = (
    "com|net|org|info|biz|co|io|us|uk|ca|gov|edu|me|ly|app|site|online|xyz|top|live|shop|"
    "store|link|click|help|support|services|account|security|vip|club|cc|tk|ml|ga|cf|gq|ru|cn"
)
_URL = re.compile(
    r"(?:https?://|hxxps?://|www\.)\S+"  # full links
    rf"|\b(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+(?:{_TLDS})\b(?:/\S*)?",  # bare domains
    re.IGNORECASE,
)
_PHONE = re.compile(
    r"(?<![\w$])"
    r"(?:"
    r"\+?\d{1,3}[\s.-]?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}"  # +1 (555) 010-4477, 1-555-010-4477
    r"|\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}"  # (555) 010-4477, 555.010.4477, 5550104477
    r"|\d{3}[\s.-]\d{4}"  # 010-4477
    r"|\+\d{8,15}"  # +15550104477
    r"|\d{11,15}"  # 15550104477
    r")"
    r"(?![\w])"
)
# Short codes (5 or 6 digits) only count as a contact right after a contact verb.
_SHORT_CODE = re.compile(r"\b((?:text|txt|call|dial|reply|sms|message|contact)\b\D{0,12}?)\d{5,6}\b", re.IGNORECASE)


def strip_contacts(text: str) -> str:
    """Remove any phone number or link from model-written text.

    Keeps ordinary numbers ("3 days old", "$900", "2 hours", "txn_3") and our
    own redaction tags (`<URL_1>`, `<PHONE_HASH_7f3a>`), which aren't contacts.
    """
    if not text:
        return ""
    out = _URL.sub("", text)
    out = _PHONE.sub("", out)
    out = _SHORT_CODE.sub(lambda m: m.group(1), out)
    # Tidy what the removals leave behind.
    out = re.sub(r"\(\s*\)|\[\s*\]", "", out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"\s+([,.;:!?])", r"\1", out)
    out = re.sub(r"([,;:])(?=[,.;:!?])", "", out)
    out = re.sub(r"\b(at|to|on|call|text|visit|via)\s*([.,;:!?]|$)", r"\2", out, flags=re.IGNORECASE)
    out = re.sub(r"\b(to|at|on)\s+\1\b", r"\1", out, flags=re.IGNORECASE)
    out = re.sub(r"\s+([,.;:!?])", r"\1", out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    return out.strip(" ,;:")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_RESULT_KEYS = set(AgentResult.model_fields)
_EVIDENCE_KEYS = set(Evidence.model_fields)


def _clean(raw: dict[str, Any]) -> dict[str, Any]:
    """Drop keys the contract doesn't know and trim/lowercase enum strings.

    Unknown keys are not enum violations, so dropping them saves a wasted retry.
    Enum values are only normalised for case and spacing: "Very likely" becomes
    "very likely", but "definitely_scam" still fails.
    """
    extra = set(raw) - _RESULT_KEYS
    if extra:
        log.info("dropped unknown result keys", extra={"fields": {"keys": sorted(extra)}})
    data = {k: v for k, v in raw.items() if k in _RESULT_KEYS}

    def norm(v: Any) -> Any:
        return v.strip().lower() if isinstance(v, str) else v

    for key in ("verdict", "confidence_words"):
        if key in data:
            data[key] = norm(data[key])
    for key in ("plan", "actions"):
        if isinstance(data.get(key), list):
            data[key] = [norm(v) for v in data[key]]
    if isinstance(data.get("evidence"), list):
        data["evidence"] = [
            {k: (norm(v) if k == "tool" else v) for k, v in e.items() if k in _EVIDENCE_KEYS} if isinstance(e, dict) else e
            for e in data["evidence"]
        ]
    if isinstance(data.get("actions"), list):  # the cap is a guardrail, not a reason to reject the answer
        data["actions"] = list(dict.fromkeys(data["actions"]))
    return data


def validate_result(raw: Any) -> AgentResult:
    """Parse Nemotron's final JSON against `AgentResult`.

    Raises `ValueError` with a short, input-free description of what's wrong,
    which the loop sends back to Nemotron for its one retry.
    """
    if not isinstance(raw, dict):
        raise ValueError("The final answer must be one JSON object.")
    data = _clean(raw)
    actions = data.get("actions")
    over_cap = isinstance(actions, list) and len(actions) > MAX_ACTIONS
    if over_cap:
        data["actions"] = actions[:MAX_ACTIONS]
    try:
        result = AgentResult.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or 'result'}: {e['msg']}" for e in exc.errors(include_input=False, include_url=False)
        )
        raise ValueError(f"Invalid final result: {problems}") from None
    if over_cap:
        log.info("trimmed actions to the cap", extra={"fields": {"given": len(actions)}})
    return result


# ---------------------------------------------------------------------------
# Enforcement
# ---------------------------------------------------------------------------


def _classifier_says_scam(classifier: ClassifierOutput) -> bool:
    return classifier.category != LEGIT_CATEGORY and classifier.score >= CLASSIFIER_SCAM_SCORE


def _classifier_says_legit(classifier: ClassifierOutput) -> bool:
    # Symmetric with `_classifier_says_scam` (L15): a weak "legit" (below 0.7) no longer overrides
    # verified tool evidence. Seen live: a PayPal look-alike link scam scored legit 0.65 and was
    # forced to "not sure" although the link check proved the impersonation.
    return classifier.category == LEGIT_CATEGORY and classifier.score >= CLASSIFIER_SCAM_SCORE


def apply_guardrails(
    result: AgentResult,
    classifier: ClassifierOutput,
    tools_run: Iterable[ToolName | str] | None = None,
    tools_attempted: Iterable[ToolName | str] | None = None,
) -> tuple[AgentResult, list[str]]:
    """Apply the 7.4 rules. Returns the corrected result and a note per change.

    `tools_run` is the tools that answered in this loop; `tools_attempted` adds
    the ones that were called but failed (defaults to `tools_run`). Evidence
    is kept only from tools that answered. Evidence citing a tool that was
    never called is an invented check: it's dropped, noted, and the reason is
    replaced. Evidence citing a tool that failed is just dropped.
    """
    notes: list[str] = []
    verdict = result.verdict
    confidence = result.confidence_words
    reason = result.reason
    evidence = list(result.evidence)
    plan = list(result.plan)

    # Evidence must come from tools that ran. If the model cited a check it never
    # ran, its reason may rest on that invented finding, so use an honest default.
    if tools_run is not None:
        ran = [ToolName(t) for t in tools_run]
        attempted = set(ran) | {ToolName(t) for t in (tools_attempted or [])}
        if any(e.tool not in attempted for e in evidence):
            notes.append("The answer mentioned a check that didn't run, so that part was left out.")
            reason = _EMPTY_REASON[verdict]
        evidence = [e for e in evidence if e.tool in ran]
        plan += [t for t in dict.fromkeys(ran) if t not in plan]

    # No contacts in anything the customer reads. (Logged, not shown: it isn't a
    # change to the answer the customer needs to know about.)
    clean_reason = strip_contacts(reason)
    clean_evidence = [e.model_copy(update={"finding": strip_contacts(e.finding)}) for e in evidence]
    if clean_reason != reason.strip() or any(a.finding != b.finding for a, b in zip(evidence, clean_evidence)):
        log.info("stripped a contact from model text")
    reason, evidence = clean_reason, [e for e in clean_evidence if e.finding]

    # Classifier and tools disagree: say so instead of picking a side.
    disagree = (verdict == Verdict.likely_scam and _classifier_says_legit(classifier)) or (
        verdict == Verdict.likely_safe and _classifier_says_scam(classifier)
    )
    if disagree:
        notes.append("Our message classifier and the checks disagreed, so the answer is \"not sure\".")
        verdict, confidence, reason = Verdict.unsure, ConfidenceWords.not_sure, DISAGREE_REASON

    # Verdict and confidence must agree with each other.
    if verdict == Verdict.unsure and confidence != ConfidenceWords.not_sure:
        confidence = ConfidenceWords.not_sure
    elif verdict != Verdict.unsure and confidence == ConfidenceWords.not_sure:
        confidence = ConfidenceWords.likely

    # "Very likely" needs two different tools behind it.
    if confidence == ConfidenceWords.very_likely and len({e.tool for e in evidence}) < 2:
        notes.append("Only one check backed this up, so we say \"likely\", not \"very likely\".")
        confidence = ConfidenceWords.likely

    actions: list[Action] = list(dict.fromkeys(result.actions))[:MAX_ACTIONS]
    if verdict == Verdict.likely_scam and len(actions) > 1 and Action.ignore in actions:
        actions.remove(Action.ignore)
        notes.append("Left out an ignore suggestion that conflicted with the protective steps.")

    if not reason:
        reason = _EMPTY_REASON[verdict]

    fixed = result.model_copy(
        update={
            "plan": plan,
            "verdict": verdict,
            "confidence_words": confidence,
            "reason": reason,
            "evidence": evidence,
            "actions": actions,
        }
    )
    # Round-trip so the copy is re-validated against the contract.
    return AgentResult.model_validate(fixed.model_dump()), notes


def enforce(
    result: AgentResult,
    classifier: ClassifierOutput,
    tools_run: Iterable[ToolName | str] | None = None,
    tools_attempted: Iterable[ToolName | str] | None = None,
) -> AgentResult:
    """Apply the evidence, disagreement, action and contact rules."""
    return apply_guardrails(result, classifier, tools_run, tools_attempted)[0]


def unsure_fallback(evidence_so_far: Iterable[Any], plan: Iterable[ToolName | str] | None = None) -> AgentResult:
    """Result after a second invalid output or a failed call: `unsure`, with whatever evidence we did collect."""
    evidence: list[Evidence] = []
    for item in evidence_so_far or []:
        try:
            ev = item if isinstance(item, Evidence) else Evidence.model_validate(
                {"tool": item["tool"], "finding": item["finding"]}
            )
        except Exception:
            continue
        finding = strip_contacts(ev.finding)
        if finding:
            evidence.append(ev.model_copy(update={"finding": finding}))
    steps: list[ToolName] = []
    for t in plan or []:
        try:
            steps.append(ToolName(t))
        except ValueError:
            continue
    return AgentResult(
        plan=list(dict.fromkeys(steps or [e.tool for e in evidence])),
        verdict=Verdict.unsure,
        confidence_words=ConfidenceWords.not_sure,
        reason=UNSURE_REASON,
        evidence=evidence,
    )
