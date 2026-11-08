"""JSON mocks for every API route, valid against `app.contracts`.

Served while `USE_MOCKS=true`. Data is synthetic and based on the three
scenarios in POC_MVP.md section 4.3. Numbers here are placeholders, never
shown as real results. # MOCK: replaced by L9
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from app import contracts as c

MOCK_DIR = Path(__file__).resolve().parent

# File name -> the contract type it must validate against.
MOCK_TYPES: dict[str, Any] = {
    "inbox.json": list[c.InboxItem],
    "result_scenario_1.json": c.ResultPoll,
    "result_scenario_2.json": c.ResultPoll,
    "result_scenario_3.json": c.ResultPoll,
    "result_legit.json": c.ResultPoll,
    "post_message.json": c.PostMessageResponse,
    "clicked.json": c.ClickedResponse,
    "confirm.json": c.ConfirmResponse,
    "action.json": c.ActionResponse,
    "privacy.json": c.PrivacyView,
    "campaigns.json": list[c.Campaign],
    "metrics.json": c.Metrics,
    "demo_reset.json": c.DemoResetResponse,
}


def load_raw(name: str) -> Any:
    return json.loads((MOCK_DIR / name).read_text(encoding="utf-8"))


@lru_cache
def load(name: str) -> Any:
    """Load a mock and validate it against its contract type."""
    return TypeAdapter(MOCK_TYPES[name]).validate_python(load_raw(name))
