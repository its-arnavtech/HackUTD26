"""Nemotron agent loop with plan, re-plan and guardrails (L8; recovery details: L11).

POC_MVP.md section 7.2, following the loop A4 proved 5/5 against the hosted
model (`scripts/smoke_nemotron.py`):

1. Send the agent input (DATA_SPEC 3.1) with the tool schemas (L5 registry).
2. The first tools Nemotron asks for are its plan. The plan goes to the trail
   before any tool runs.
3. Loop: run the requested tools, send the results back as data, let Nemotron
   stop, continue, or add a check. A check it hadn't planned is logged as a
   `replan` step. At most 6 tool calls; at most 4 once any step takes over 10 s.
4. When Nemotron stops calling tools, send the final-result schema (two-phase
   prompting) and read the JSON answer (DATA_SPEC 3.3).
5. Guardrails (7.4). An invalid answer is retried once with the error; a second
   failure returns `unsure` with the evidence collected so far.

`run_agent` never raises: a failed Nemotron call or an unexpected error also
ends in an honest `unsure` result, with a verdict entry in the trail.

When the model returns its thinking (`reasoning_content`), it becomes the `why`
of that turn's first trail entry, so "How we checked" shows Nemotron's own
reasoning. It is never sent back to the model.
"""

from __future__ import annotations

import ast
import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app import privacy_log
from app.agent import guardrails, prompts, recovery, registry
from app.agent.registry import PrivacyHook, ToolCall
from app.contracts import (
    AgentInput,
    AgentMode,
    AgentResult,
    ConfidenceWords,
    NessieRecentActivityResult,
    ToolName,
    TrailEntry,
    TrailKind,
    Verdict,
)

log = logging.getLogger(__name__)

MAX_TOOL_CALLS = 6
SLOW_STEP_MS = 10_000  # POC_MVP 7.3: one step over 10 s caps the loop at 4 calls
SLOW_MAX_TOOL_CALLS = 4
# Tool turns, one "now give the final answer" turn, one retry, and slack.
MAX_TURNS = MAX_TOOL_CALLS + 4
WHY_MAX_CHARS = 240

ChatFn = Callable[..., dict[str, Any]]
CallToolFn = Callable[..., ToolCall]

_VERDICT_WORDS = {
    (Verdict.likely_scam, ConfidenceWords.very_likely): "Very likely a scam",
    (Verdict.likely_scam, ConfidenceWords.likely): "Likely a scam",
    (Verdict.likely_safe, ConfidenceWords.very_likely): "Very likely safe",
    (Verdict.likely_safe, ConfidenceWords.likely): "Likely safe",
}


class InvalidTurn(ValueError):
    """Nemotron's reply was neither a usable tool call nor a final answer."""


@dataclass
class _Pending:
    id: str
    name: str
    args: Any


@dataclass
class _Turn:
    tool_calls: list[_Pending] = field(default_factory=list)
    final: dict[str, Any] | None = None
    raw_tool_calls: list[dict[str, Any]] | None = None  # native tool_calls, echoed back in history
    content: str = ""
    why: str | None = None  # json_action's "why"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_agent(
    agent_input: AgentInput,
    on_trail: Callable[[TrailEntry], None],
    *,
    chat: ChatFn | None = None,
    call_tool: CallToolFn | None = None,
    tool_schemas: list[dict[str, Any]] | None = None,
    protocol: str | None = None,
    on_call: PrivacyHook | None = None,
) -> AgentResult:
    """Plan, call tools, re-plan, and return a guardrail-checked result.

    `chat`, `call_tool`, `tool_schemas` and `protocol` default to the real
    Nemotron client, the L5 registry and `NEMOTRON_PROTOCOL`; tests pass fakes.
    `on_call` is the privacy hook handed to every tool call (L6).
    """
    run = _Run(
        agent_input,
        on_trail,
        chat=chat or _default_chat,
        call_tool=call_tool or registry.call_tool,
        tool_schemas=tool_schemas if tool_schemas is not None else registry.openai_tool_schemas(),
        protocol=protocol or _default_protocol(),
        on_call=on_call,
    )
    try:
        return run.execute()
    except Exception as exc:  # the agent must always answer, or the UI waits forever
        log.exception("agent loop failed", extra={"fields": {"error_type": type(exc).__name__}})
        return run.give_up("We couldn't finish checking this message.")


def _default_chat(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, tool_choice: str = "auto") -> dict[str, Any]:
    from app.integrations import nemotron

    return nemotron.chat(messages, tools, tool_choice)


def _default_protocol() -> str:
    try:
        from app.integrations import nemotron

        return nemotron.get_nemotron_settings().NEMOTRON_PROTOCOL
    except Exception:
        return "native"


# ---------------------------------------------------------------------------
# One run of the loop
# ---------------------------------------------------------------------------


class _Run:
    def __init__(
        self,
        agent_input: AgentInput,
        on_trail: Callable[[TrailEntry], None],
        *,
        chat: ChatFn,
        call_tool: CallToolFn,
        tool_schemas: list[dict[str, Any]],
        protocol: str,
        on_call: PrivacyHook | None,
    ) -> None:
        self.input = agent_input
        self.on_trail = on_trail
        self.chat = chat
        self.call_tool = call_tool
        self.tools = tool_schemas
        self.protocol = protocol
        self.on_call = on_call

        self.messages = prompts.build_messages(agent_input)
        privacy_log.record_model("nemotron", json.loads(self.messages[-1]["content"]))  # L6: exactly what Nemotron gets
        self.step = 0
        self.calls = 0
        self.max_calls = MAX_TOOL_CALLS
        self.planned: list[ToolName] | None = None
        self.attempted: list[ToolName] = []
        self.tools_run: list[ToolName] = []  # tools that answered ok
        self.evidence: list[dict[str, str]] = []
        self.replanned = False
        self.recovery_refs: list[str] = []
        self.final_requested = False
        self.retry_used = False
        self.nudged = False
        self.verdict_reasoning: str | None = None
        self.started = time.perf_counter()

    # -- trail -----------------------------------------------------------------

    def trail(self, kind: TrailKind, *, tool: ToolName | None = None, why: str | None = None, finding: str | None = None, ms: int | None = None) -> None:
        self.step += 1
        entry = TrailEntry(step=self.step, kind=kind, tool=tool, why=why, finding=finding, ms=ms, at=datetime.now(timezone.utc))
        try:
            self.on_trail(entry)
        except Exception:  # a broken trail writer must not stop the check
            log.exception("trail write failed", extra={"fields": {"step": self.step}})

    def log_plan(self, names: list[ToolName], why: str | None) -> None:
        self.planned = list(names)
        listed = ", ".join(n.value for n in names) if names else "no checks"
        self.trail(TrailKind.plan, why=why or _plan_why(names), finding=f"Plan: {listed}")

    # -- main loop ---------------------------------------------------------------

    def execute(self) -> AgentResult:
        # The customer's /clicked tap starts a mandatory read-only activity
        # check. Show this code-enforced recovery step before Nemotron chooses
        # further checks; it cannot omit the time window or invent its refs.
        if self.input.mode == AgentMode.recovery and self.input.customer_context.linked_bank:
            args = {"since": self.input.received_at.isoformat()}
            raw = {"id": "recovery_activity", "type": "function", "function": {
                "name": ToolName.nessie_recent_activity.value, "arguments": json.dumps(args),
            }}
            self.run_tools(_Turn(
                tool_calls=[_Pending(raw["id"], ToolName.nessie_recent_activity.value, args)],
                raw_tool_calls=[raw],
            ), "You said you clicked, so we check activity since the text arrived.")
        for _ in range(MAX_TURNS):
            response, ms = self.ask()
            if response is None:
                return self.give_up("We couldn't reach the checking model.")
            if ms > SLOW_STEP_MS:
                self.slow_down(ms)
            message, finish = _first_choice(response)
            reasoning = _reasoning(message)

            try:
                turn = self.parse(message, finish)
            except InvalidTurn as exc:
                if not self.retry(message, str(exc), final=self.final_requested):
                    return self.give_up("The checking model's answer couldn't be read.")
                continue

            if turn.tool_calls:
                if self.final_requested:
                    # Asked for the answer but got more tool calls: answer them as skipped and retry once.
                    self.answer_skipped(turn, "No more checks: give the final answer now.")
                    if not self.retry(None, "You already have the results; return the final answer", final=True):
                        return self.give_up("The checking model didn't give a final answer.")
                    continue
                self.run_tools(turn, reasoning)
                if self.calls >= self.max_calls:
                    self.request_final()
                continue

            # No tool calls. If nothing has been checked yet, nudge once before asking for the answer,
            # unless the model already answered without citing any check.
            answered_cleanly = turn.final is not None and _looks_like_result(turn.final) and not turn.final.get("evidence")
            if not self.final_requested and not self.attempted and not self.nudged and not answered_cleanly:
                self.nudged = True
                self.remember_assistant(turn)
                self.messages.append({"role": "user", "content": prompts.NUDGE_TOOLS})
                log.info("no checks yet, nudging once")
                continue

            # This is (or should be) the final answer.
            if self.planned is None:
                self.log_plan([], reasoning)
                reasoning = None
            if turn.final is None or not self.final_requested and not _looks_like_result(turn.final):
                if not self.final_requested:
                    # The "I'm done" turn usually carries the reasoning behind the verdict; keep it for that entry.
                    self.verdict_reasoning = reasoning or self.verdict_reasoning
                    self.remember_assistant(turn)
                    self.request_final()
                    continue
                if not self.retry(message, "The final answer must be one JSON object", final=True):
                    return self.give_up("The checking model's answer couldn't be read.")
                continue

            try:
                result = guardrails.validate_result(turn.final)
            except ValueError as exc:
                if not self.retry(message, str(exc), final=True):
                    return self.give_up("The checking model's answer didn't pass our checks twice.")
                continue
            return self.finish(result, reasoning)

        return self.give_up("The check took too many steps.")

    # -- Nemotron ----------------------------------------------------------------

    def ask(self) -> tuple[dict[str, Any] | None, int]:
        started = time.perf_counter()
        try:
            # Always "auto", as in A4's proven loop; tool calls after the final request are answered as skipped.
            response = self.chat(self.messages, self.tools, "auto")
        except Exception as exc:  # never log provider bodies: they can echo the request
            log.warning("nemotron call failed", extra={"fields": {"error_type": type(exc).__name__}})
            return None, _ms(started)
        ms = _ms(started)
        log.info("nemotron step", extra={"fields": {"ms": ms, "calls": self.calls}})
        return response, ms

    def parse(self, message: dict[str, Any], finish: str | None) -> _Turn:
        content = message.get("content") or ""
        raw_calls = message.get("tool_calls") or []
        if raw_calls:
            return _Turn(tool_calls=[_pending(tc, i) for i, tc in enumerate(raw_calls)], raw_tool_calls=raw_calls, content=content)

        # Seen live: Bolt sometimes writes its native call syntax as text
        # (`check_sender{claimed_brand:<|"|>Capital One<|"|>}`) and the server
        # doesn't turn it into `tool_calls`. Run it as the tool call it is.
        leaked = _leaked_tool_calls(content)
        if leaked:
            log.info("read a tool call written as text", extra={"fields": {"calls": len(leaked)}})
            raw = [
                {"id": f"text_{self.step}_{self.calls}_{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
                for i, (name, args) in enumerate(leaked)
            ]
            return _Turn(tool_calls=[_pending(tc, i) for i, tc in enumerate(raw)], raw_tool_calls=raw, content="")

        if finish == "tool_calls":
            raise InvalidTurn("Your reply said it called a tool but contained no tool call")

        data = _extract_json(content)
        if self.protocol == "json_action" and isinstance(data, dict) and "action" in data:
            action = data.get("action")
            if action == "call_tool":
                name, args = data.get("tool"), data.get("args", {})
                if not isinstance(name, str) or not isinstance(args, dict):
                    raise InvalidTurn("A call_tool action needs a tool name and an args object")
                why = data.get("why") if isinstance(data.get("why"), str) else None
                return _Turn(tool_calls=[_Pending(id=f"json_{self.step}_{self.calls}", name=name, args=args)], content=content, why=why)
            if action == "finish":
                result = data.get("result")
                if not isinstance(result, dict):
                    raise InvalidTurn("A finish action needs a result object")
                return _Turn(final=result, content=content)
            raise InvalidTurn(f"Unknown action {action!r}; use call_tool or finish")
        return _Turn(final=data if isinstance(data, dict) else None, content=content)

    # -- tools -------------------------------------------------------------------

    def run_tools(self, turn: _Turn, reasoning: str | None) -> None:
        names = [_tool_name(p.name) for p in turn.tool_calls]
        known = [n for n in names if n is not None]
        why = reasoning or (guardrails.strip_contacts(turn.why) if turn.why else None)

        if self.planned is None:
            self.log_plan(known, why)
            if self.input.mode == AgentMode.recovery:
                self.replanned = True
                self.trail(TrailKind.replan, why="You asked for recovery after clicking the link.",
                           finding="Check activity since the text arrived; ask you about flagged items.")
            why = None
        else:
            added = [n for n in dict.fromkeys(known) if n not in self.planned and n not in self.attempted]
            if added:
                self.replanned = True
                self.planned += added
                listed = ", ".join(n.value for n in added)
                self.trail(TrailKind.replan, why=why or f"A result called for another check: {listed}", finding=f"Added: {listed}")
                why = None

        self.remember_assistant(turn)
        for pending, name in zip(turn.tool_calls, names):
            if self.calls >= self.max_calls:
                self.tool_message(pending, _skipped(pending.name, "Skipped: the limit of tool calls was reached."))
                continue
            self.calls += 1
            if name == ToolName.nessie_recent_activity and self.input.mode == AgentMode.recovery:
                pending.args = {"since": self.input.received_at.isoformat()}
            if name in {ToolName.nessie_recent_activity, ToolName.nessie_bill_status} and not self.input.customer_context.linked_bank:
                call = _skipped(pending.name, "The customer has not linked a bank account.")
            else:
                # The registry answers invalid arguments as data.
                call = self.call_tool(pending.name, pending.args, self.input, on_call=self.on_call)
            if call.ms > SLOW_STEP_MS:
                self.slow_down(call.ms)
            self.tool_message(pending, call)
            if name is None:  # unknown tool: the registry told the model; nothing to show the customer
                log.info("model asked for an unknown tool", extra={"fields": {"calls": self.calls}})
                continue
            self.attempted.append(name)
            finding = _summarize(name, call)
            self.trail(TrailKind.tool, tool=name, why=why or _tool_why(name, self.input), finding=finding, ms=call.ms)
            why = None
            if call.ok:
                self.tools_run.append(name)
                self.evidence.append({"tool": name.value, "finding": finding})
                if name == ToolName.nessie_recent_activity and self.input.mode == AgentMode.recovery:
                    activity = NessieRecentActivityResult.model_validate(call.result)
                    self.recovery_refs.extend(item.ref for item in activity.flagged)

    def tool_message(self, pending: _Pending, call: ToolCall) -> None:
        payload = json.dumps(call.to_tool_message(), ensure_ascii=False, default=str)
        privacy_log.record_tool_result("nemotron", json.loads(payload))  # L6: every result sent back, skipped ones too
        if self.protocol == "json_action" and pending.id.startswith("json_"):
            self.messages.append({"role": "user", "content": json.dumps({"tool": pending.name, "result": json.loads(payload)}, ensure_ascii=False)})
        else:
            self.messages.append({"role": "tool", "tool_call_id": pending.id, "content": payload})

    def answer_skipped(self, turn: _Turn, why: str) -> None:
        self.remember_assistant(turn)
        for pending in turn.tool_calls:
            self.tool_message(pending, _skipped(pending.name, why))

    # -- conversation bookkeeping -------------------------------------------------

    def remember_assistant(self, turn: _Turn) -> None:
        """Echo the assistant turn into history. Never includes `reasoning_content`."""
        if turn.raw_tool_calls:
            self.messages.append({"role": "assistant", "content": turn.content or "", "tool_calls": turn.raw_tool_calls})
        elif turn.content:
            self.messages.append({"role": "assistant", "content": turn.content})

    def request_final(self) -> None:
        if not self.final_requested:
            self.final_requested = True
            self.messages.append({"role": "system", "content": prompts.final_instruction(self.protocol)})

    def retry(self, message: dict[str, Any] | None, error: str, *, final: bool) -> bool:
        """Use the single invalid-output retry. Returns False if it was already used."""
        if self.retry_used:
            log.info("invalid output after retry", extra={"fields": {"final": final}})
            return False
        self.retry_used = True
        log.info("invalid output, retrying once", extra={"fields": {"final": final}})
        if message is not None and (message.get("content") or "").strip():
            self.messages.append({"role": "assistant", "content": message["content"]})
        if final:
            self.final_requested = True
            self.messages.append({"role": "user", "content": prompts.retry_instruction(error, self.protocol)})
        else:
            self.messages.append({"role": "user", "content": f"{error}. {prompts.RETRY_TOOL_CALL}"})
        return True

    def slow_down(self, ms: int) -> None:
        if self.max_calls > SLOW_MAX_TOOL_CALLS:
            self.max_calls = SLOW_MAX_TOOL_CALLS
            log.info("slow step, capping tool calls", extra={"fields": {"ms": ms, "max_calls": self.max_calls}})

    # -- endings ---------------------------------------------------------------------

    def finish(self, result: AgentResult, reasoning: str | None) -> AgentResult:
        if self.input.mode == AgentMode.recovery:
            result = result.model_copy(update={"plan": list(dict.fromkeys(self.attempted))})
        result, notes = guardrails.apply_guardrails(result, self.input.classifier, self.tools_run, self.attempted)
        update: dict[str, Any] = {"replan": self.replanned}
        result = result.model_copy(update=update)
        result = recovery.finish_recovery(result, self.input, self.recovery_refs)
        why = " ".join(notes) if notes else (reasoning or self.verdict_reasoning)
        self.trail(TrailKind.verdict, why=why, finding=_verdict_words(result), ms=_ms(self.started))
        log.info(
            "agent done",
            extra={"fields": {"verdict": result.verdict.value, "calls": self.calls, "replan": self.replanned, "notes": len(notes)}},
        )
        return result

    def give_up(self, why: str) -> AgentResult:
        if self.planned is None:
            self.log_plan([], None)
        result = guardrails.unsure_fallback(self.evidence, self.attempted)
        result = recovery.finish_recovery(result, self.input, self.recovery_refs)
        self.trail(TrailKind.verdict, why=why, finding=_verdict_words(result), ms=_ms(self.started))
        log.info("agent gave up", extra={"fields": {"calls": self.calls}})
        return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ms(started: float) -> int:
    return max(0, round((time.perf_counter() - started) * 1000))


def _first_choice(response: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    try:
        choice = response["choices"][0]
        message = choice.get("message") or {}
    except (KeyError, IndexError, TypeError, AttributeError):
        return {}, None
    return (message if isinstance(message, dict) else {}), choice.get("finish_reason")


_DECISION = re.compile(r"\b(should|need to|because|since|so that|to confirm|to see whether|to see if|to check|in order to)\b", re.IGNORECASE)
_LIST_MARKER = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*")


def _reasoning(message: dict[str, Any]) -> str | None:
    """The decision from Nemotron's thinking, if the server returned it, as one short display line.

    Bolt's reasoning (seen live) restates the message, lists the checks done so
    far, then says what it will do and why ("Since X was unavailable, I should
    check public reports to confirm the pattern"). That decision sentence is
    what "How we checked" should show, so pick the last sentence that gives a
    reason, else the last sentence.
    """
    text = message.get("reasoning_content") or message.get("reasoning")
    if not isinstance(text, str) or not text.strip():
        return None
    text = text.replace("`", "")
    sentences = []
    for line in text.splitlines():
        for s in re.split(r"(?<=[.!?])\s+", _LIST_MARKER.sub("", line).strip()):
            s = re.sub(r"\s*\([^()]*\)", "", s).strip()  # drop asides like quoted rules
            s = re.sub(r",?\s*(?:as per|according to|per) the rules?\b.*$", ".", s, flags=re.IGNORECASE).strip()
            s = re.sub(r"^[a-z_]+:\s*", "", s)  # "public_scam_reports: To confirm ..." -> "To confirm ..."
            if len(s) > 3 and not s.endswith(":"):
                sentences.append(s)
    if not sentences:
        return None
    reasons = [s for s in sentences if _DECISION.search(s)]
    chosen = reasons[-1] if reasons else sentences[-1]
    chosen = guardrails.strip_contacts(re.sub(r"\s+", " ", chosen))
    if len(chosen) > WHY_MAX_CHARS:
        chosen = chosen[: WHY_MAX_CHARS - 3].rsplit(" ", 1)[0].rstrip(",;:") + "..."
    return chosen or None


_LEAKED_CALL = re.compile(r"(?:call:)?\s*([a-z_]+)\s*(\{.*?\})", re.DOTALL)


def _leaked_tool_calls(content: str) -> list[tuple[str, dict[str, Any]]] | None:
    """Tool calls written as text, if that's all the reply is.

    Two shapes seen live from Bolt on the hosted endpoint:
    `check_sender{claimed_brand:<|"|>Capital One<|"|>}` and
    `check_sender(claimed_brand="Capital One")`.
    """
    text = _FENCE.sub("", content or "").strip()
    if not text or text.startswith("{"):
        return None
    return _brace_calls(text) or _paren_calls(text)


_PAREN_CALL = re.compile(r"^(?:call:)?\s*([a-z_]+)\s*\((.*)\)$", re.DOTALL)


def _paren_calls(text: str) -> list[tuple[str, dict[str, Any]]] | None:
    """One call per line, Python style. Arguments are read with `literal_eval`: nothing is executed."""
    calls = []
    for line in (ln.strip().rstrip(";") for ln in text.splitlines()):
        if not line:
            continue
        m = _PAREN_CALL.match(line)
        if not m or _tool_name(m.group(1)) is None:
            return None
        try:
            node = ast.parse(f"_({m.group(2)})", mode="eval").body
            if not isinstance(node, ast.Call) or node.args or any(kw.arg is None for kw in node.keywords):
                return None
            args = {kw.arg: ast.literal_eval(kw.value) for kw in node.keywords}
        except (SyntaxError, ValueError):
            return None
        calls.append((m.group(1), args))
    return calls or None


def _brace_calls(text: str) -> list[tuple[str, dict[str, Any]]] | None:
    calls, pos = [], 0
    for m in _LEAKED_CALL.finditer(text):
        if text[pos : m.start()].strip(" ,;\n"):
            return None  # other words around it: prose, not a call
        name = m.group(1)
        args = _loose_args(m.group(2))
        if _tool_name(name) is None or args is None:
            return None
        calls.append((name, args))
        pos = m.end()
    if not calls or text[pos:].strip(" ,;\n"):
        return None
    return calls


def _loose_args(raw: str) -> dict[str, Any] | None:
    """`{claimed_brand:<|"|>Capital One<|"|>}` -> {"claimed_brand": "Capital One"}."""
    text = raw.replace('<|"|>', '"')
    for candidate in (text, re.sub(r'([{,]\s*)([A-Za-z_]\w*)\s*:', r'\1"\2":', text)):
        try:
            value = json.loads(candidate)
        except ValueError:
            continue
        return value if isinstance(value, dict) else None
    return None


def _pending(tc: dict[str, Any], index: int) -> _Pending:
    fn = tc.get("function") or {}
    name = fn.get("name")
    if not isinstance(name, str) or not name:
        raise InvalidTurn("A tool call had no function name")
    raw = fn.get("arguments")
    if raw is None or raw == "":
        args: Any = {}
    elif isinstance(raw, dict):
        args = raw
    else:
        try:
            args = json.loads(raw)
        except (TypeError, ValueError):
            raise InvalidTurn(f"The arguments for {name} were not valid JSON") from None
    return _Pending(id=str(tc.get("id") or f"call_{index}"), name=name, args=args)


_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def _extract_json(content: str) -> Any:
    """Read one JSON object from the model's text, tolerating code fences and stray words around it."""
    text = _FENCE.sub("", content or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        pass
    start = text.find("{")
    if start == -1:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(text[start:])
        return value
    except ValueError:
        return None


def _looks_like_result(data: dict[str, Any]) -> bool:
    return "verdict" in data


def _tool_name(name: str) -> ToolName | None:
    try:
        return ToolName(name)
    except ValueError:
        return None


def _skipped(name: str, message: str) -> ToolCall:
    return ToolCall(name=name, args={}, ok=False, error={"type": "skipped", "message": message})


def _verdict_words(result: AgentResult) -> str:
    return _VERDICT_WORDS.get((result.verdict, result.confidence_words), "We're not sure")


def _plan_why(names: list[ToolName]) -> str:
    if not names:
        return "Nemotron decided this message needs no tool checks."
    return "Nemotron chose these checks for what the message claims."


def _tool_why(name: ToolName, agent_input: AgentInput) -> str:
    brand = agent_input.sender.claimed_brand
    return {
        ToolName.check_link: "The message contains a link",
        ToolName.check_sender: f"The sender claims to be {brand}" if brand else "Checking who sent the message",
        ToolName.match_campaign: "Checking whether this is part of a known scam wave",
        ToolName.nessie_recent_activity: "The message is about the customer's bank account",
        ToolName.nessie_bill_status: "The message makes a claim about a bill",
        ToolName.public_scam_reports: "Looking for public reports of this scam",
    }[name]


def _summarize(name: ToolName, call: ToolCall) -> str:
    """One line for the trail. Says what was checked, never "your account is fine", and has no links."""
    if not call.ok:
        kind = (call.error or {}).get("type")
        return {
            "timeout": "This check took too long and was skipped",
            "unavailable": "This check isn't available yet",
            "invalid_args": "This check was asked for with the wrong details",
        }.get(kind, "This check couldn't be completed")
    r = call.result or {}
    try:
        text = _SUMMARIES[name](r)
    except Exception:
        text = "Check completed"
    return guardrails.strip_contacts(text) or "Check completed"


def _sum_link(r: dict[str, Any]) -> str:
    parts = []
    if r.get("on_blocklist"):
        parts.append("on our blocklist of scam links")
    if r.get("lookalike_of"):
        parts.append("imitates an official website")
    age = r.get("domain_age_days")
    if isinstance(age, int):
        parts.append(f"registered {age} day{'s' if age != 1 else ''} ago")
    if not parts and r.get("signals"):
        parts.append(str(r["signals"][0]))
    return ("The link " + ", ".join(parts)) if parts else "No warning signs found in the link"


def _sum_sender(r: dict[str, Any]) -> str:
    if r.get("matches_official_channel"):
        return "The sender matches one of the brand's official channels"
    if not r.get("official_channels_known"):
        return "We don't have this brand's official channels to compare against"
    return "The sender is not one of the brand's official channels"


def _sum_campaign(r: dict[str, Any]) -> str:
    if r.get("campaign_id"):
        n = r.get("similar_last_24h") or 0
        # Only real counts: A12 never re-dates history, so "0 in the last 24 hours" is common; don't say it.
        return f"Matches a known scam campaign, {n} similar message{'s' if n != 1 else ''} in the last 24 hours" if n else "Matches a known scam campaign"
    return "No match with a known scam campaign"


def _sum_activity(r: dict[str, Any]) -> str:
    flagged = r.get("flagged") or []
    if flagged:
        first = flagged[0]
        more = f" and {len(flagged) - 1} more" if len(flagged) > 1 else ""
        return f"Flagged {first.get('ref', 'an item')}: {first.get('reason', 'unusual activity')}{more}"
    return f"No unusual activity flagged in {r.get('items_checked', 0)} recent items"


def _sum_bill(r: dict[str, Any]) -> str:
    if not r.get("found"):
        return "No bill found for that payee"
    bits = [f"Last bill {r.get('last_status') or 'status unknown'}"]
    if r.get("last_payment_date"):
        bits.append(f"paid on {r['last_payment_date']}")
    due = r.get("amount_due_now")
    if isinstance(due, (int, float)):
        bits.append(f"${due:,.2f} due now")
    return ", ".join(b for b in bits if b)


def _sum_reports(r: dict[str, Any]) -> str:
    n = r.get("reports_found") or 0
    text = f"{n} public report{'s' if n != 1 else ''} of this scam found"
    if r.get("domain_reported"):
        text += ", including the link's domain"
    return text


_SUMMARIES: dict[ToolName, Callable[[dict[str, Any]], str]] = {
    ToolName.check_link: _sum_link,
    ToolName.check_sender: _sum_sender,
    ToolName.match_campaign: _sum_campaign,
    ToolName.nessie_recent_activity: _sum_activity,
    ToolName.nessie_bill_status: _sum_bill,
    ToolName.public_scam_reports: _sum_reports,
}
