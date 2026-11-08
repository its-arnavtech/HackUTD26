"""Tool registry and runtime (L5).

Each tool registers its name, argument model and result model. The registry
exports JSON schemas for Nemotron, applies a per-tool timeout, returns errors as
data, and records every call's inputs for the privacy log (L6).

The six tools stay plain functions in their own modules (Arnav's `link`,
`sender`, `campaign`, `nessie_tools`; Lavanya's `public_reports`), with the
signature `fn(args: ArgsModel, agent_input: AgentInput) -> ResultModel`. This
module registers them in `builtin_tools()`, so tool authors never import the
registry.

    from app.agent import registry

    tools = registry.openai_tool_schemas()             # tools=[...] for Nemotron
    call = registry.call_tool("check_link", {"url_id": "URL_1"}, agent_input, on_call=privacy.append)
    call.to_tool_message()                             # what goes back to Nemotron
    call.ok, call.result, call.error, call.ms          # for the trail and guardrails

Rules:
- `call_tool` never raises for a tool problem: unknown tool, bad arguments, a
  timeout or a crash all come back as `ToolCall(ok=False, error=...)`, so the
  agent can carry on (POC_MVP 7.4). Error text sent to the model is generic;
  details go to the log only.
- Some arguments are filled in by code, never by the model (`injected`). For
  example `match_campaign`'s `message_id` always comes from the agent input, so
  the model can't point a tool at another message. Injected fields are left out
  of the schema Nemotron sees.
- A timed-out tool keeps running on its worker thread (Python can't kill a
  thread); its late answer is ignored.
"""

from __future__ import annotations

import contextvars
import copy
import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ValidationError

from app import contracts as c
from app.contracts import AgentInput, ToolName

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 10.0


@dataclass
class ToolSpec:
    name: ToolName
    description: str
    args_model: type[BaseModel]
    result_model: type[BaseModel]
    fn: Callable[[Any, AgentInput], BaseModel]
    timeout_s: float = DEFAULT_TIMEOUT_S
    # Argument values set by code from the agent input, hidden from the model.
    injected: dict[str, Callable[[AgentInput], Any]] = field(default_factory=dict)
    # Which parts of the agent input the tool reads (shown in the privacy panel).
    reads: tuple[str, ...] = ()


@dataclass
class ToolCall:
    """One tool call: what was asked, what it received, and what came back."""

    name: str
    args: dict[str, Any]  # as validated and passed to the tool (incl. injected), or as the model sent them if invalid
    ok: bool
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None  # {"type": "...", "message": "..."}
    ms: int = 0
    at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_tool_message(self) -> dict[str, Any]:
        """The data returned to Nemotron. Treated as data, never as instructions (POC_MVP 7.4)."""
        if self.ok:
            return {"ok": True, "tool": self.name, "result": self.result}
        return {"ok": False, "tool": self.name, "error": self.error}


PrivacyHook = Callable[[c.PrivacyRecipient], None]


class ToolRegistry:
    def __init__(self, max_workers: int = 8) -> None:
        self._tools: dict[ToolName, ToolSpec] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="sentinel-tool")

    # -- registration -----------------------------------------------------

    def register(self, spec: ToolSpec, *, replace: bool = False) -> None:
        name = ToolName(spec.name)
        unknown = set(spec.injected) - set(spec.args_model.model_fields)
        if unknown:
            raise ValueError(f"{name.value}: injected fields {sorted(unknown)} are not in {spec.args_model.__name__}")
        if spec.timeout_s <= 0:
            raise ValueError(f"{name.value}: timeout_s must be positive")
        with self._lock:
            if name in self._tools and not replace:
                raise ValueError(f"tool {name.value} is already registered")
            self._tools[name] = spec

    def get(self, name: ToolName | str) -> ToolSpec:
        try:
            return self._tools[ToolName(name)]
        except (ValueError, KeyError):
            raise KeyError(f"unknown tool {name!r}") from None

    def names(self) -> list[ToolName]:
        return list(self._tools)

    def __contains__(self, name: object) -> bool:
        try:
            return ToolName(name) in self._tools  # type: ignore[arg-type]
        except ValueError:
            return False

    # -- schemas --------------------------------------------------------------

    def parameters_schema(self, name: ToolName | str) -> dict[str, Any]:
        """JSON schema of the arguments the model may send (injected fields removed)."""
        spec = self.get(name)
        schema = _inline_refs(spec.args_model.model_json_schema())
        props = schema.get("properties", {})
        for hidden in spec.injected:
            props.pop(hidden, None)
        schema["required"] = [r for r in schema.get("required", []) if r not in spec.injected]
        if not schema["required"]:
            schema.pop("required")
        schema.setdefault("properties", {})
        schema["additionalProperties"] = False
        return _strip_titles(schema)

    def openai_tool_schemas(self, names: list[ToolName | str] | None = None) -> list[dict[str, Any]]:
        """`tools=[...]` for Nemotron's OpenAI-compatible API, in registration order."""
        chosen = [ToolName(n) for n in names] if names is not None else self.names()
        return [
            {
                "type": "function",
                "function": {
                    "name": n.value,
                    "description": self.get(n).description,
                    "parameters": self.parameters_schema(n),
                },
            }
            for n in chosen
        ]

    # -- calls ------------------------------------------------------------------

    def call(
        self,
        name: ToolName | str,
        args: dict[str, Any] | None,
        agent_input: AgentInput,
        *,
        on_call: PrivacyHook | None = None,
        timeout_s: float | None = None,
    ) -> ToolCall:
        """Validate args, run the tool with a timeout, and return the result or an error as data."""
        started = time.perf_counter()
        raw_args = dict(args or {}) if isinstance(args, dict) else {}
        tool_name = getattr(name, "value", str(name))

        def fail(kind: str, message: str, call_args: dict[str, Any] | None = None) -> ToolCall:
            call = ToolCall(
                name=tool_name,
                args=call_args if call_args is not None else raw_args,
                ok=False,
                error={"type": kind, "message": message},
                ms=_ms(started),
            )
            log.info("tool failed", extra={"fields": {"tool": tool_name, "error_type": kind, "ms": call.ms}})
            return call

        if not isinstance(args, (dict, type(None))):
            return fail("invalid_args", "Arguments must be a JSON object.")
        try:
            spec = self.get(name)
        except KeyError:
            return fail("unknown_tool", f"There is no tool named {tool_name!r}. Use one of: {', '.join(n.value for n in self.names())}.")
        tool_name = spec.name.value

        # Injected values always win over anything the model sent for those fields.
        merged = {k: v for k, v in raw_args.items() if k not in spec.injected}
        try:
            merged.update({k: getter(agent_input) for k, getter in spec.injected.items()})
        except Exception:
            log.exception("tool injection failed", extra={"fields": {"tool": tool_name}})
            return fail("tool_error", f"{tool_name} could not run.")
        try:
            parsed = spec.args_model.model_validate(merged)
        except ValidationError as exc:
            problems = "; ".join(_short_error(e) for e in exc.errors())
            return fail("invalid_args", f"Invalid arguments for {tool_name}: {problems}")

        call_args = parsed.model_dump(mode="json", exclude_none=True)
        if on_call is not None:
            _record(on_call, spec, call_args)

        ctx = contextvars.copy_context()  # keep message_id on the tool's log lines
        future = self._pool.submit(ctx.run, spec.fn, parsed, agent_input)
        limit = timeout_s if timeout_s is not None else spec.timeout_s
        try:
            raw_result = future.result(timeout=limit)
        except FutureTimeout:
            future.cancel()
            return fail("timeout", f"{tool_name} took longer than {limit:g} seconds and was skipped.", call_args)
        except NotImplementedError:
            return fail("unavailable", f"{tool_name} is not available yet.", call_args)
        except Exception:
            log.exception("tool raised", extra={"fields": {"tool": tool_name}})
            return fail("tool_error", f"{tool_name} failed while checking.", call_args)

        try:
            result = (
                raw_result
                if isinstance(raw_result, spec.result_model)
                else spec.result_model.model_validate(
                    raw_result.model_dump() if isinstance(raw_result, BaseModel) else raw_result
                )
            )
        except ValidationError:
            log.exception("tool returned an invalid result", extra={"fields": {"tool": tool_name}})
            return fail("tool_error", f"{tool_name} returned an unexpected result.", call_args)

        call = ToolCall(name=tool_name, args=call_args, ok=True, result=result.model_dump(mode="json"), ms=_ms(started))
        log.info("tool ok", extra={"fields": {"tool": tool_name, "ms": call.ms}})
        return call

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ms(started: float) -> int:
    return max(0, round((time.perf_counter() - started) * 1000))


def _short_error(err: dict[str, Any]) -> str:
    loc = ".".join(str(p) for p in err.get("loc", ())) or "arguments"
    return f"{loc}: {err.get('msg', 'invalid')}"


def _record(on_call: PrivacyHook, spec: ToolSpec, call_args: dict[str, Any]) -> None:
    try:
        on_call(
            c.PrivacyRecipient(
                recipient=spec.name.value,
                kind="tool",
                received_fields=[*call_args.keys(), *(f"agent_input.{r}" for r in spec.reads)],
                payload=call_args,
                at=datetime.now(timezone.utc),
            )
        )
    except Exception:  # the privacy log must never break a check
        log.exception("privacy hook failed", extra={"fields": {"tool": spec.name.value}})


def _inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Replace `$ref`s with their definitions; some OpenAI-compatible servers don't resolve them."""
    schema = copy.deepcopy(schema)
    defs = schema.pop("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                target = copy.deepcopy(defs[ref.split("/")[-1]])
                extra = {k: v for k, v in node.items() if k != "$ref"}
                return walk({**target, **extra})
            return {k: walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(schema)


def _strip_titles(node: Any) -> Any:
    """Drop pydantic's auto `title` keys (noise in the prompt). Keeps a property literally named `title`."""
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            if k == "title" and isinstance(v, str):
                continue
            out[k] = {pk: _strip_titles(pv) for pk, pv in v.items()} if k == "properties" else _strip_titles(v)
        return out
    if isinstance(node, list):
        return [_strip_titles(v) for v in node]
    return node


# ---------------------------------------------------------------------------
# Built-in tools (DATA_SPEC 3.2, POC_MVP 7.6)
# ---------------------------------------------------------------------------


def builtin_tools() -> list[ToolSpec]:
    """The six agent tools. Descriptions tell Nemotron which claims each tool checks (POC_MVP 7.2)."""
    from app.tools.campaign import match_campaign
    from app.tools.link import check_link
    from app.tools.nessie_tools import nessie_bill_status, nessie_recent_activity
    from app.tools.public_reports import public_scam_reports
    from app.tools.sender import check_sender

    return [
        ToolSpec(
            name=ToolName.check_link,
            description=(
                "Check one link from the message, by its id (URL_1, URL_2, ...). Returns the domain, its age, "
                "whether it is on our blocklist, which official domain it imitates, where it redirects, and signals. "
                "Use when the message contains a link."
            ),
            args_model=c.CheckLinkArgs,
            result_model=c.CheckLinkResult,
            fn=check_link,
            reads=("urls",),
        ),
        ToolSpec(
            name=ToolName.check_sender,
            description=(
                "Check whether the sender is an official channel of the brand the message claims to be from. "
                "Use when the message claims to come from a company (a bank, a carrier, a delivery service)."
            ),
            args_model=c.CheckSenderArgs,
            result_model=c.CheckSenderResult,
            fn=check_sender,
            reads=("sender",),
        ),
        ToolSpec(
            name=ToolName.match_campaign,
            description=(
                "Check whether this message matches a known scam campaign and how many similar messages were seen "
                "in the last 24 hours. Takes no arguments: it always checks the current message."
            ),
            args_model=c.MatchCampaignArgs,
            result_model=c.MatchCampaignResult,
            fn=match_campaign,
            injected={"message_id": lambda ai: ai.message_id},
            reads=("text_redacted", "urls", "classifier"),
        ),
        ToolSpec(
            name=ToolName.nessie_recent_activity,
            description=(
                "Look at the customer's recent bank activity and flag anything unusual (new payee, unusually large "
                "transfer, first purchase at a merchant). Returns counts and references like txn_3, never names or "
                "account numbers. Give exactly one of `days` or `since`. Use when the message claims to be from the "
                "customer's bank, mentions their account or a charge, or after the customer says they clicked."
            ),
            args_model=c.NessieRecentActivityArgs,
            result_model=c.NessieRecentActivityResult,
            fn=nessie_recent_activity,
            reads=("customer_context",),
        ),
        ToolSpec(
            name=ToolName.nessie_bill_status,
            description=(
                "Look up the customer's bills for one payee: last status, last payment date and amount due now. "
                "Use when the message says a bill is overdue, unpaid or about to cause a service cut-off."
            ),
            args_model=c.NessieBillStatusArgs,
            result_model=c.NessieBillStatusResult,
            fn=nessie_bill_status,
            reads=("customer_context",),
        ),
        ToolSpec(
            name=ToolName.public_scam_reports,
            description=(
                "Search public sources (official brand pages, government, news, security vendors) for reports of this "
                "scam and the brand's own guidance. Sends only the brand, scam category and link domain. Use when "
                "other checks are inconclusive or to confirm a known scam pattern."
            ),
            args_model=c.PublicScamReportsArgs,
            result_model=c.GeminiOutput,
            fn=public_scam_reports,
            timeout_s=20.0,  # grounded search is slower
        ),
    ]


# ---------------------------------------------------------------------------
# Default registry and module-level API (used by the agent loop, L8)
# ---------------------------------------------------------------------------

_default: ToolRegistry | None = None
_default_lock = threading.Lock()


def default_registry() -> ToolRegistry:
    """The process-wide registry with the six built-in tools."""
    global _default
    with _default_lock:
        if _default is None:
            reg = ToolRegistry()
            for spec in builtin_tools():
                reg.register(spec)
            _default = reg
        return _default


def register(spec: ToolSpec, *, replace: bool = False) -> None:
    """Add a tool to the default registry."""
    default_registry().register(spec, replace=replace)


def get_tool(name: ToolName | str) -> ToolSpec:
    """Look up a registered tool."""
    return default_registry().get(name)


def openai_tool_schemas(names: list[ToolName | str] | None = None) -> list[dict[str, Any]]:
    """`tools=[...]` for Nemotron's OpenAI-compatible API."""
    return default_registry().openai_tool_schemas(names)


def call_tool(
    name: ToolName | str,
    args: dict[str, Any] | None,
    agent_input: AgentInput,
    *,
    on_call: PrivacyHook | None = None,
) -> ToolCall:
    """Validate args, run with a timeout, return the result or an error as data."""
    return default_registry().call(name, args, agent_input, on_call=on_call)
