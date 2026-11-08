"""Record and replay cache. Filled in by L1.

Every external call (Nemotron, Gemini, Nessie, RDAP, Hugging Face) goes through
here. `DEMO_MODE=live` calls the API, `record` calls it and saves the response
under `data/fixtures/` keyed by a hash of the request, `replay` serves only
saved responses (POC_MVP.md 7.8).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from app.config import DATA_DIR

FIXTURES_DIR = DATA_DIR / "fixtures"

T = TypeVar("T")


def request_key(service: str, request: dict[str, Any]) -> str:
    """Stable hash of a request. (L1)"""
    raise NotImplementedError("L1: request key")


def cached_call(service: str, request: dict[str, Any], fn: Callable[[], T]) -> T:
    """Run `fn` according to DEMO_MODE, recording or replaying its response. (L1)"""
    raise NotImplementedError("L1: record and replay cache")
