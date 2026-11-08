"""Run a demo scenario end to end from the command line (G1).

    python -m scripts.run_scenario 1            # trail and verdict
    python -m scripts.run_scenario 2            # scenario 2 runs in recovery mode
    python -m scripts.run_scenario 1 --json     # stages, agent input, trail and result as JSON

Run from `backend/`. Every stage uses the real module when it's implemented and
falls back to a stand-in, marked STAND-IN below, while it still raises
`NotImplementedError`. The output says which stages were real. Redaction always
runs first, and the stand-in agent only sees the redacted `AgentInput`.

The agent loop is the single `AGENT = ...` line below. When L8 merges, set it to
`run_agent` (already imported).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

import tldextract
from pydantic import BaseModel

from app.agent.loop import MAX_TOOL_CALLS, run_agent  # noqa: F401  (run_agent: see AGENT below)
from app.classifier.baseline import baseline_predict
from app.classifier.predict import predict
from app.config import DATA_DIR, get_settings
from app.contracts import (
    Action,
    AgentInput,
    AgentMode,
    AgentResult,
    CheckLinkArgs,
    CheckSenderArgs,
    ClassifierOutput,
    ConfidenceWords,
    CustomerContext,
    Evidence,
    Features,
    Message,
    NessieBillStatusArgs,
    NessieRecentActivityArgs,
    RedactedMessage,
    RedactionCounts,
    RedactionReport,
    SenderInfo,
    SenderType,
    ToolName,
    TrailEntry,
    TrailKind,
    UrlInfo,
    Verdict,
)
from app.features.extract import detect_claimed_brand, extract_features, extract_urls
from app.privacy.redact import redact, redact_sender
from app.tools.link import check_link
from app.tools.nessie_tools import nessie_bill_status, nessie_recent_activity
from app.tools.sender import check_sender

SCENARIOS_DIR = DATA_DIR / "scenarios"
DEMO_CUSTOMER = CustomerContext(linked_bank=True, linked_institutions=["Capital One"])
RECOVERY_SCENARIOS = {2}


# ---------------------------------------------------------------------------
# Stage bookkeeping
# ---------------------------------------------------------------------------


@dataclass
class Stage:
    name: str
    source: str  # "real", "baseline" or "stand-in"
    note: str = ""


@dataclass
class Run:
    scenario: dict[str, Any]
    mode: AgentMode
    stages: list[Stage] = field(default_factory=list)
    trail: list[TrailEntry] = field(default_factory=list)
    agent_input: Optional[AgentInput] = None
    result: Optional[AgentResult] = None


def _first_available(run: Run, name: str, attempts: list[tuple[str, Callable[[], Any]]]) -> Any:
    """Return the first attempt that doesn't raise NotImplementedError, and record which one ran."""
    skipped: list[str] = []
    for source, attempt in attempts:
        try:
            value = attempt()
        except NotImplementedError as exc:
            skipped.append(str(exc) or source)
            continue
        run.stages.append(Stage(name, source, f"not merged yet: {'; '.join(skipped)}" if skipped else ""))
        return value
    raise RuntimeError(f"no implementation available for {name}")


# ---------------------------------------------------------------------------
# STAND-IN stages. Each is used only while the real module raises NotImplementedError.
# ---------------------------------------------------------------------------

_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_PHONE_RE = re.compile(r"\+?1?[\s.-]?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b")
_DIGITS_RE = re.compile(r"\b\d{4,}\b")
_DEMO_NAMES = ("Linda",)  # STAND-IN: A3 detects names; this only covers the demo customer
_extract = tldextract.TLDExtract(suffix_list_urls=())


def _salt() -> str:
    salt = get_settings().PHONE_HASH_SALT
    return salt.get_secret_value() if salt else "dev-only-salt"


def _phone_hash(number: str) -> str:
    digest = hashlib.sha256((_salt() + re.sub(r"\D", "", number)).encode()).hexdigest()[:4]
    return f"<PHONE_HASH_{digest}>"


def stand_in_redact(text: str) -> RedactedMessage:
    """STAND-IN for A3's `redact`: URLs, emails, phone numbers, long digit runs and the demo name."""
    counts = RedactionCounts()
    raw_urls: list[str] = []

    def url(match: re.Match[str]) -> str:
        raw_urls.append(match.group(0).rstrip(".,)"))
        return f"<URL_{len(raw_urls)}>"

    out = _URL_RE.sub(url, text)
    out, counts.EMAIL = _EMAIL_RE.subn("<EMAIL>", out)
    out, counts.PHONE = _PHONE_RE.subn(lambda m: _phone_hash(m.group(0)), out)
    out, counts.ACCOUNT_DIGITS = _DIGITS_RE.subn("<ACCOUNT_DIGITS>", out)
    for name in _DEMO_NAMES:
        out, n = re.subn(rf"\b{name}\b", "<PERSON>", out)
        counts.PERSON += n
    kept = ["brand"] + (["domain"] if raw_urls else []) + (["deadline"] if re.search(r"\b\d+\s*(hours?|minutes?|days?)\b", out) else [])
    return RedactedMessage(text_redacted=out, report=RedactionReport(counts=counts, kept=kept), raw_urls=raw_urls)


def stand_in_redact_sender(raw: str) -> tuple[SenderType, str]:
    """STAND-IN for A3's `redact_sender`: short codes stay visible, personal numbers are hashed."""
    value = raw.strip()
    digits = re.sub(r"\D", "", value)
    if "@" in value:
        return SenderType.email, "<EMAIL>"
    if digits and len(digits) <= 6 and not value.startswith("+"):
        return SenderType.short_code, digits
    if len(digits) >= 10:
        return SenderType.long_code, _phone_hash(value)
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9 ]{1,10}", value):
        return SenderType.alphanumeric, value
    return SenderType.unknown, "<UNKNOWN>"


def _brands() -> list[dict[str, Any]]:
    return json.loads((DATA_DIR / "brands.json").read_text(encoding="utf-8"))["brands"]


def _squash(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def stand_in_claimed_brand(text_redacted: str) -> Optional[str]:
    """STAND-IN for A9's `detect_claimed_brand`: first brand from brands.json named in the text."""
    squashed = _squash(text_redacted)
    hits = [(squashed.find(_squash(b["name"])), b["name"]) for b in _brands() if _squash(b["name"]) in squashed]
    return min(hits)[1] if hits else None


def stand_in_extract_urls(redacted: RedactedMessage) -> list[UrlInfo]:
    """STAND-IN for A9's `extract_urls`."""
    shorteners = {"bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "is.gd", "rb.gy", "cutt.ly"}
    infos = []
    for i, raw in enumerate(redacted.raw_urls, start=1):
        parts = _extract(raw)
        domain = f"{parts.domain}.{parts.suffix}".lower()
        official = None
        term = None
        for brand in _brands():
            if domain in brand.get("official_domains", []):
                official = brand
            for candidate in [_squash(brand["name"]), *brand.get("brand_terms", [])]:
                if term is None and candidate and candidate in parts.domain.lower().replace("-", ""):
                    term = candidate
        infos.append(
            UrlInfo(
                id=f"URL_{i}",
                registered_domain=domain,
                is_shortener=domain in shorteners,
                brand_term_in_domain=None if official else term,
                is_official_brand_domain=official is not None,
            )
        )
    return infos


def stand_in_extract_features(text_redacted: str) -> Features:
    """STAND-IN for A9's `extract_features`: a few keyword rules."""
    lower = text_redacted.lower()
    deadline = re.search(r"\b(\d+\s*(?:hours?|minutes?|days?))\b", lower)
    money = re.search(r"\$\s?(\d+(?:\.\d{2})?)", text_redacted)
    threat = next((t for k, t in [("locked", "account_lock"), ("suspen", "service_suspension"), ("overdue", "late_payment")] if k in lower), None)
    action = next((a for k, a in [("verify", "click_link_and_verify"), ("pay", "click_link_and_pay")] if k in lower), None)
    asks = [w for k, w in [("verify", "login"), ("sign-in", "login"), ("pay", "payment")] if k in lower]
    return Features(
        urgency_deadline=deadline.group(1) if deadline else None,
        threat=threat,
        requested_action=action,
        asks_for=sorted(set(asks)),
        money_amount_claimed=float(money.group(1)) if money else None,
    )


def baseline_classifier(text_redacted: str) -> ClassifierOutput:
    """A1's baseline, used while L7's `predict` isn't merged. It returns labels only, so the score is a placeholder."""
    message = Message(message_id="scenario", text=text_redacted, sender="<redacted>")
    [label] = baseline_predict([message])
    return ClassifierOutput(category=label, score=0.5, top3=[(label, 0.5)], baseline_score=None)


def stand_in_classifier(text_redacted: str) -> ClassifierOutput:
    """STAND-IN for L7 and A1: keyword scores over the taxonomy categories."""
    lower = text_redacted.lower()
    keywords = {
        "bank_impersonation": ["bank", "sign-in", "account will be locked", "verify", "capital one", "fraud"],
        "billing_scam": ["bill", "overdue", "pay", "suspension", "payment"],
        "delivery_scam": ["package", "delivery", "parcel", "redelivery", "usps"],
    }
    hits = {cat: sum(k in lower for k in words) for cat, words in keywords.items()}
    total = sum(hits.values())
    if total == 0:
        scores = {"legit": 0.7, **{c: 0.1 for c in keywords}}
    else:
        scores = {c: round(0.9 * n / total, 2) for c, n in hits.items()} | {"legit": 0.1}
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])[:3]
    return ClassifierOutput(category=ranked[0][0], score=ranked[0][1], top3=ranked, baseline_score=None)


# ---------------------------------------------------------------------------
# STAND-IN agent loop. Replaced by L8's `run_agent` (same signature).
# Rules from POC_MVP 7.2 pick the tools; no model is called.
# ---------------------------------------------------------------------------

ToolFn = Callable[[Any, AgentInput], BaseModel]

TOOLS: dict[ToolName, ToolFn] = {
    ToolName.check_link: check_link,
    ToolName.check_sender: check_sender,
    ToolName.nessie_recent_activity: nessie_recent_activity,
    ToolName.nessie_bill_status: nessie_bill_status,
}

_TOOL_ISSUE = {
    ToolName.check_link: "A10",
    ToolName.check_sender: "A10",
    ToolName.nessie_recent_activity: "A11",
    ToolName.nessie_bill_status: "A11",
}


@dataclass
class Finding:
    tool: ToolName
    text: str
    risky: Optional[bool]  # True: points to a scam, False: points to safe, None: no signal


def _plan(agent_input: AgentInput) -> list[tuple[ToolName, BaseModel, str]]:
    brand = agent_input.sender.claimed_brand
    features = agent_input.features
    plan: list[tuple[ToolName, BaseModel, str]] = []
    if agent_input.mode == AgentMode.recovery:
        plan.append((ToolName.nessie_recent_activity, NessieRecentActivityArgs(since=agent_input.since), "Customer says they clicked; look for activity since the message"))
        return plan
    if agent_input.urls:
        plan.append((ToolName.check_link, CheckLinkArgs(url_id=agent_input.urls[0].id), "Message contains a link"))
    bill_claim = features.threat in {"late_payment", "service_suspension"} or features.money_amount_claimed is not None
    if brand and not bill_claim:
        plan.append((ToolName.check_sender, CheckSenderArgs(claimed_brand=brand), f"Sender claims to be {brand}"))
    if brand and brand in agent_input.customer_context.linked_institutions:
        plan.append((ToolName.nessie_recent_activity, NessieRecentActivityArgs(days=7), f"Message claims to be the customer's linked bank, {brand}"))
    if brand and bill_claim:
        plan.append((ToolName.nessie_bill_status, NessieBillStatusArgs(payee=brand), f"Message claims a {brand} bill is due"))
    return plan[:MAX_TOOL_CALLS]


def _finding(tool: ToolName, result: BaseModel) -> Finding:
    r = result.model_dump()
    if tool == ToolName.check_link:
        if r["lookalike_of"]:
            return Finding(tool, f"Domain imitates {r['lookalike_of']}", True)
        if r["on_blocklist"]:
            return Finding(tool, "Domain is on our list of known scam domains", True)
        if r["domain_age_days"] is not None and r["domain_age_days"] < 30:
            return Finding(tool, f"Domain is {r['domain_age_days']} days old", True)
        if any(s.startswith("official ") for s in r["signals"]):
            return Finding(tool, "Link goes to the brand's official website", False)
        return Finding(tool, "Nothing unusual about the link's domain", None)
    if tool == ToolName.check_sender:
        if not r["official_channels_known"]:
            return Finding(tool, "The brand's official texting numbers aren't on file", None)
        if r["matches_official_channel"]:
            return Finding(tool, "Sent from an official channel", False)
        return Finding(tool, "Not sent from an official channel", True)
    if tool == ToolName.nessie_recent_activity:
        flagged = r["flagged"]
        if flagged:
            return Finding(tool, f"Found {len(flagged)} item(s) you may not have made", True)
        return Finding(tool, f"No new payees or unusual transfers in {r['items_checked']} items checked", None)
    if tool == ToolName.nessie_bill_status:
        if r["found"] and r["last_status"] == "completed" and not r["amount_due_now"]:
            return Finding(tool, f"The bill was paid on {r['last_payment_date']} and nothing is due now", True)
        if r["found"]:
            return Finding(tool, f"The bill's last status is {r['last_status']}", None)
        return Finding(tool, "No bill from this payee on file", None)
    return Finding(tool, "Checked", None)


def _scam_categories() -> set[str]:
    taxonomy = json.loads((DATA_DIR / "taxonomy.json").read_text(encoding="utf-8"))
    return {c["id"] for c in taxonomy["categories"] if c.get("is_scam")}


def stand_in_agent(agent_input: AgentInput, on_trail: Callable[[TrailEntry], None]) -> AgentResult:
    """STAND-IN for L8's `run_agent`: rule-based plan, direct tool calls, rule-based verdict."""
    step = 0

    def emit(kind: TrailKind, *, tool: ToolName | None = None, why: str | None = None, finding: str | None = None, ms: int | None = None) -> None:
        nonlocal step
        step += 1
        on_trail(TrailEntry(step=step, kind=kind, tool=tool, why=why, finding=finding, ms=ms, at=datetime.now().astimezone()))

    plan = _plan(agent_input)
    emit(TrailKind.plan, why="Stand-in planner (L8 not merged): rules from POC_MVP 7.2", finding=", ".join(t.value for t, _, _ in plan) or "no tools apply")

    findings: list[Finding] = []
    flagged_refs: list[str] = []
    for tool, args, why in plan:
        started = time.perf_counter()
        try:
            result = TOOLS[tool](args, agent_input)
        except NotImplementedError:
            text = f"Not available yet ({_TOOL_ISSUE[tool]} not merged)"
            emit(TrailKind.tool, tool=tool, why=why, finding=text, ms=int((time.perf_counter() - started) * 1000))
            continue
        except Exception as exc:  # errors come back as data, as L5's registry will do
            emit(TrailKind.tool, tool=tool, why=why, finding=f"Couldn't run: {type(exc).__name__}: {exc}", ms=int((time.perf_counter() - started) * 1000))
            continue
        finding = _finding(tool, result)
        findings.append(finding)
        if tool == ToolName.nessie_recent_activity:
            flagged_refs = [f["ref"] for f in result.model_dump()["flagged"]]
        emit(TrailKind.tool, tool=tool, why=why, finding=finding.text, ms=int((time.perf_counter() - started) * 1000))

    risky = [f for f in findings if f.risky]
    risky_tools = {f.tool for f in risky}
    classifier_says_scam = agent_input.classifier.category in _scam_categories()
    recovery = agent_input.mode == AgentMode.recovery

    if len(risky_tools) >= 2:
        verdict, confidence = Verdict.likely_scam, ConfidenceWords.very_likely
    elif risky_tools:
        verdict, confidence = Verdict.likely_scam, ConfidenceWords.likely
    elif classifier_says_scam or not findings:
        verdict, confidence = Verdict.unsure, ConfidenceWords.not_sure
    else:
        verdict, confidence = Verdict.likely_safe, ConfidenceWords.likely

    if recovery and flagged_refs:
        actions = [Action.freeze_card, Action.call_number_on_card, Action.change_password]
    elif verdict == Verdict.likely_scam:
        actions = [Action.block_sender, Action.report_spam]
        if agent_input.sender.claimed_brand in agent_input.customer_context.linked_institutions:
            actions.append(Action.call_number_on_card)
    elif verdict == Verdict.unsure:
        actions = [Action.open_official_app]
    else:
        actions = [Action.ignore]

    shown = (risky or findings)[:2]
    if shown:
        reason = shown[0].text + (f", and {shown[1].text[0].lower()}{shown[1].text[1:]}" if len(shown) > 1 else "") + "."
    else:
        reason = "We couldn't run any checks on this message yet."

    result = AgentResult(
        plan=[t for t, _, _ in plan],
        verdict=verdict,
        confidence_words=confidence,
        reason=reason,
        evidence=[Evidence(tool=f.tool, finding=f.text) for f in findings],
        actions=actions[:3],
        was_this_you=flagged_refs if recovery else [],
        replan=False,
    )
    emit(TrailKind.verdict, why="Stand-in verdict rules (L8 not merged)", finding=f"{verdict.value} ({confidence.value})")
    return result


# The agent loop. When L8 merges: AGENT = run_agent
AGENT: Callable[[AgentInput, Callable[[TrailEntry], None]], AgentResult] = stand_in_agent


# ---------------------------------------------------------------------------
# Scenario runner
# ---------------------------------------------------------------------------


def load_scenario(number: int) -> dict[str, Any]:
    path = SCENARIOS_DIR / f"scenario_{number}.json"
    if not path.exists():
        raise SystemExit(f"No scenario {number}: {path} doesn't exist")
    return json.loads(path.read_text(encoding="utf-8"))


def build_agent_input(run: Run) -> AgentInput:
    message = run.scenario["message"]
    received_at = datetime.fromisoformat(message["received_at"])

    redacted: RedactedMessage = _first_available(run, "redaction", [("real", lambda: redact(message["text"])), ("stand-in", lambda: stand_in_redact(message["text"]))])
    sender_type, sender_value = _first_available(
        run, "sender redaction", [("real", lambda: redact_sender(message["sender"])), ("stand-in", lambda: stand_in_redact_sender(message["sender"]))]
    )
    text = redacted.text_redacted

    urls = _first_available(run, "URL features", [("real", lambda: extract_urls(redacted)), ("stand-in", lambda: stand_in_extract_urls(redacted))])
    features = _first_available(run, "message features", [("real", lambda: extract_features(text)), ("stand-in", lambda: stand_in_extract_features(text))])
    brand = _first_available(run, "claimed brand", [("real", lambda: detect_claimed_brand(text)), ("stand-in", lambda: stand_in_claimed_brand(text))])
    classifier = _first_available(
        run,
        "classifier",
        [
            ("real", lambda: predict(text, features)),
            ("baseline", lambda: baseline_classifier(text)),
            ("stand-in", lambda: stand_in_classifier(text)),
        ],
    )

    return AgentInput(
        message_id=f"scenario_{run.scenario['scenario']}",
        mode=run.mode,
        received_at=received_at,
        since=received_at if run.mode == AgentMode.recovery else None,
        sender=SenderInfo(type=sender_type, value=sender_value, claimed_brand=brand),
        text_redacted=text,
        urls=urls,
        features=features,
        classifier=classifier,
        customer_context=DEMO_CUSTOMER,
    )


def run_scenario(number: int, mode: AgentMode | None = None) -> Run:
    scenario = load_scenario(number)
    run = Run(scenario=scenario, mode=mode or (AgentMode.recovery if number in RECOVERY_SCENARIOS else AgentMode.check))
    run.agent_input = build_agent_input(run)
    run.stages.append(Stage("agent loop", "stand-in" if AGENT is stand_in_agent else "real", "L8 not merged" if AGENT is stand_in_agent else ""))
    result = AGENT(run.agent_input, run.trail.append)
    run.result = AgentResult.model_validate(result.model_dump())
    return run


def _format(run: Run) -> str:
    s = run.scenario
    lines = [f"Scenario {s['scenario']}: {s['title']} ({run.mode.value} mode)", "", "Stages:"]
    for stage in run.stages:
        lines.append(f"  {stage.name:<17} {stage.source:<9} {stage.note}".rstrip())
    lines += ["", f"Redacted text: {run.agent_input.text_redacted}", "", "How we checked:"]
    for e in run.trail:
        label = e.tool.value if e.tool else e.kind.value
        ms = f" ({e.ms} ms)" if e.ms is not None else ""
        lines.append(f"  {e.step}. {label}{ms}: {e.finding}")
        if e.why:
            lines.append(f"     why: {e.why}")
    expected = s.get("expected_plan")
    if expected:
        got = [t.value for t in run.result.plan]
        lines += ["", f"Plan {'matches' if got == expected else 'differs from'} the scenario's expected plan {expected}"]
    lines += ["", "Verdict (schema-valid AgentResult):", run.result.model_dump_json(indent=2)]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a demo scenario end to end and print the trail and verdict.")
    parser.add_argument("scenario", type=int, choices=[1, 2, 3])
    parser.add_argument("--mode", choices=[m.value for m in AgentMode], help="override the scenario's mode")
    parser.add_argument("--json", action="store_true", help="print stages, agent input, trail and result as JSON")
    args = parser.parse_args(argv)

    run = run_scenario(args.scenario, AgentMode(args.mode) if args.mode else None)
    if args.json:
        print(
            json.dumps(
                {
                    "scenario": args.scenario,
                    "mode": run.mode.value,
                    "stages": [stage.__dict__ for stage in run.stages],
                    "agent_input": run.agent_input.model_dump(mode="json"),
                    "trail": [e.model_dump(mode="json") for e in run.trail],
                    "result": run.result.model_dump(mode="json"),
                },
                indent=2,
            )
        )
    else:
        print(_format(run))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
