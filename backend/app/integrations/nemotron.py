"""Nemotron client (NVIDIA's OpenAI-compatible API). Filled in by A4 (gate P2).

Reads `NEMOTRON_BASE_URL` and `NEMOTRON_MODEL` from env. Every call goes
through `integrations/cache.py`. Logs latency per call.
"""

from __future__ import annotations

from typing import Any, Optional


def list_models() -> list[str]:
    """`GET /v1/models`, used to confirm the model ID. (A4)"""
    raise NotImplementedError("A4: list models")


def chat(
    messages: list[dict[str, Any]],
    tools: Optional[list[dict[str, Any]]] = None,
    tool_choice: str = "auto",
) -> dict[str, Any]:
    """One chat completion with optional native tool calling. Returns the raw response dict. (A4)"""
    raise NotImplementedError("A4: Nemotron chat")
