"""Tool registry and runtime. Filled in by L5.

Each tool registers its name, argument model and result model. The registry
exports JSON schemas for Nemotron, applies a per-tool timeout, returns errors as
data, and records every call's inputs for the privacy log (L6).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from app.contracts import AgentInput, ToolName


@dataclass
class ToolSpec:
    name: ToolName
    description: str
    args_model: type[BaseModel]
    result_model: type[BaseModel]
    fn: Callable[[Any, AgentInput], BaseModel]
    timeout_s: float = 10.0


def register(spec: ToolSpec) -> None:
    """Add a tool to the registry. (L5)"""
    raise NotImplementedError("L5: register tool")


def get_tool(name: ToolName) -> ToolSpec:
    """Look up a registered tool. (L5)"""
    raise NotImplementedError("L5: get tool")


def openai_tool_schemas() -> list[dict[str, Any]]:
    """`tools=[...]` for Nemotron's OpenAI-compatible API. (L5)"""
    raise NotImplementedError("L5: tool schemas")


def call_tool(name: ToolName, args: dict[str, Any], agent_input: AgentInput) -> dict[str, Any]:
    """Validate args, run with a timeout, return the result or an error as data. (L5)"""
    raise NotImplementedError("L5: call tool")
