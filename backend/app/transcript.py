"""What Nemotron actually did, turn by turn, for the System view (L14, local only).

`recording_chat(message_id, mode)` wraps the Nemotron chat call the agent loop
uses. For every real model call it notes:

- which model, how long the call took, and how it ended (`finish_reason`)
- what we had just sent (the redacted message, tool results, a nudge, or the
  request for the final answer)
- the tools Nemotron asked for and the arguments it chose (native tool calls or
  the text formats the loop also accepts)
- its reasoning, when the model returns one, and its final verdict

Everything here is data the model already saw or wrote, so it is redacted by
construction (redaction runs before the agent; AGENTS.md section 7). Reasoning
and free text pass through `strip_contacts` before they are kept, and nothing
is written to disk: transcripts live in memory and `clear()` empties them on
demo reset.
"""

from __future__ import annotations

import json
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from app.agent.guardrails import strip_contacts

MAX_MESSAGES = 50
MAX_TEXT = 600


class ToolRequest(BaseModel):
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class Turn(BaseModel):
    n: int
    at: datetime
    ms: int
    model: str
    tool_choice: str
    finish: str | None = None
    sent: str  # what we had just sent, in words
    tools_offered: int = 0
    tool_requests: list[ToolRequest] = Field(default_factory=list)
    requests_as_text: bool = False  # the model wrote its tool calls as text (the loop runs them anyway)
    reasoning: str | None = None
    final: dict[str, Any] | None = None  # the final-answer JSON, when this turn returned it
    reply: str | None = None  # other text the model returned


class Run(BaseModel):
    mode: str
    started_at: datetime
    turns: list[Turn] = Field(default_factory=list)


class AgentTranscript(BaseModel):
    message_id: str
    runs: list[Run] = Field(default_factory=list)


_lock = threading.Lock()
_transcripts: "OrderedDict[str, AgentTranscript]" = OrderedDict()


def clear() -> None:
    with _lock:
        _transcripts.clear()


def get(message_id: str) -> AgentTranscript | None:
    with _lock:
        t = _transcripts.get(message_id)
        return t.model_copy(deep=True) if t else None


def _start_run(message_id: str, mode: str) -> Run:
    with _lock:
        t = _transcripts.get(message_id)
        if t is None:
            t = _transcripts[message_id] = AgentTranscript(message_id=message_id)
            while len(_transcripts) > MAX_MESSAGES:
                _transcripts.popitem(last=False)
        run = Run(mode=mode, started_at=datetime.now(timezone.utc))
        t.runs.append(run)
        return run


def _clip(text: Any) -> str | None:
    if not text:
        return None
    cleaned = strip_contacts(str(text)).strip()
    return cleaned[:MAX_TEXT] + ("…" if len(cleaned) > MAX_TEXT else "") if cleaned else None


def _describe_sent(messages: list[dict[str, Any]]) -> str:
    last = messages[-1] if messages else {}
    role = last.get("role")
    if role == "tool":
        n = 0
        for m in reversed(messages):
            if m.get("role") != "tool":
                break
            n += 1
        return f"{n} tool result{'s' if n != 1 else ''}"
    content = str(last.get("content") or "")
    if role == "user" and content.lstrip().startswith("{") and '"text_redacted"' in content:
        return "The redacted message, classifier score and customer context"
    if role == "user":
        try:  # json_action protocol sends tool results back as user JSON
            data = json.loads(content)
            if isinstance(data, dict) and "tool" in data:
                return "A tool result"
        except ValueError:
            pass
        lowered = content.lower()
        if "final answer" in lowered or "return one json object" in lowered:
            return "Request for the final answer"
        if "no checks have run" in lowered:
            return "A nudge to run checks first"
        return "An instruction from the agent loop"
    return "Conversation so far"


def recording_chat(message_id: str, mode: str, model: str):
    """A drop-in for the loop's `chat` that records each real Nemotron call."""
    from app.agent import loop
    from app.integrations import nemotron

    run = _start_run(message_id, mode)

    def chat(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, tool_choice: str = "auto") -> dict[str, Any]:
        started = time.perf_counter()
        response = nemotron.chat(messages, tools, tool_choice)
        ms = round((time.perf_counter() - started) * 1000)
        choice = (response.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        content = message.get("content") or ""

        requests: list[ToolRequest] = []
        as_text = False
        for tc in message.get("tool_calls") or []:
            fn = tc.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                args = {}
            requests.append(ToolRequest(name=str(fn.get("name", "")), args=args if isinstance(args, dict) else {}))
        if not requests:
            leaked = loop._leaked_tool_calls(content)
            if leaked:
                as_text = True
                requests = [ToolRequest(name=n, args=a) for n, a in leaked]

        final = None
        if not requests and content.strip().startswith("{"):
            try:
                data = json.loads(content)
                if isinstance(data, dict) and "verdict" in data:
                    final = {k: data.get(k) for k in ("plan", "verdict", "confidence_words", "reason", "evidence", "actions")}
                    final["reason"] = _clip(final.get("reason"))
            except ValueError:
                pass

        turn = Turn(
            n=len(run.turns) + 1,
            at=datetime.now(timezone.utc),
            ms=ms,
            model=model,
            tool_choice=tool_choice,
            finish=choice.get("finish_reason"),
            sent=_describe_sent(messages),
            tools_offered=len(tools or []),
            tool_requests=requests,
            requests_as_text=as_text,
            reasoning=_clip(message.get("reasoning_content") or message.get("reasoning")),
            final=final,
            reply=None if (requests or final) else _clip(content),
        )
        with _lock:
            run.turns.append(turn)
        return response

    return chat
