"""Record/verify the three authored CLI scenarios with a repeatable demo profile.

This profile uses the real agent, redaction, features, A1 baseline, and five real
tools. Optional public search is explicitly unavailable. It is independent of a
developer's ignored L7 artifact and never fits or scores a held-out dataset.
App-wide live/replay acceptance remains G2, after the L9 pipeline is integrated.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.agent import registry
from app.agent.registry import ToolCall
from app.config import DATA_DIR, get_settings
from app.contracts import Action, ToolName, Verdict
from app.integrations import cache
from app.tools import campaign
from app.tools.campaign_store import CampaignStore
from scripts import run_scenario as rs

PROFILE = "authored-cli-baseline-v1"
SYNTHETIC_SALT = "a18-synthetic-salt"  # public, synthetic demo numbers only
MANIFEST = DATA_DIR / "fixtures" / "demo_profile.json"


@contextmanager
def demo_profile(mode: str):
    """Identical inputs on Windows, CI, and machines with/without L7 artifacts."""
    original_call = registry.call_tool
    def call(name, args, agent_input, **kwargs):
        if name == ToolName.public_scam_reports.value:
            return ToolCall(name=name, args=args, ok=False,
                            error={"type": "unavailable", "message": "Public search is not part of this replay profile."})
        return original_call(name, args, agent_input, **kwargs)

    with patch.dict(os.environ, {
        "DEMO_MODE": mode, "PHONE_HASH_SALT": SYNTHETIC_SALT, "GEMINI_API_KEY": "",
        "NEMOTRON_MODEL": "nvidia/nemotron-3.5-bolt-e4b", "NEMOTRON_PROTOCOL": "native",
        "NEMOTRON_BASE_URL": "https://integrate.api.nvidia.com/v1", "NEMOTRON_MAX_TOKENS": "2048",
        "NESSIE_BASE_URL": "https://api.nessieisreal.com",
    }):
        get_settings.cache_clear()
        try:
            with TemporaryDirectory(prefix="sentinel-replay-") as folder:
                store = CampaignStore(Path(folder) / "campaigns.sqlite")
                try:
                    train, validation = campaign.load_training_validation(DATA_DIR / "generated", splits_path=campaign.SPLITS_PATH)
                    campaign.calibrate_threshold(train, validation, store=store, splits_path=campaign.SPLITS_PATH)
                    campaign.seed_campaigns(train, store=store, splits_path=campaign.SPLITS_PATH)
                    with patch.object(campaign, "default_store", return_value=store), \
                         patch.object(rs, "trained_classifier", side_effect=NotImplementedError("Replay profile selects A1 baseline")), \
                         patch.object(registry, "call_tool", side_effect=call):
                        yield
                finally:
                    store.close()
        finally:
            get_settings.cache_clear()


def assert_scenarios(runs: dict) -> None:
    for run in runs.values():
        assert run.result.verdict == Verdict.likely_scam, "A scenario did not produce likely_scam"
        assert len(run.result.actions) <= 3
    assert runs[1].result.plan != runs[3].result.plan, "Bank and bill scenarios need different plans"
    assert ToolName.nessie_recent_activity in runs[1].result.plan
    assert not runs[1].result.was_this_you
    assert runs[2].result.was_this_you and Action.freeze_card in runs[2].result.actions
    assert runs[2].result.replan
    assert ToolName.nessie_bill_status in runs[3].result.plan
    assert any("paid on 2026-11-01" in (entry.finding or "") for entry in runs[3].trail)


def run_all(mode: str) -> dict:
    with demo_profile(mode):
        if mode == "replay":
            def refuse(*args, **kwargs):
                raise AssertionError("Offline replay tried to open a network connection")
            with patch.object(socket.socket, "connect", refuse), patch.object(socket, "create_connection", refuse):
                runs = {n: rs.run_scenario(n) for n in (1, 2, 3)}
        else:
            runs = {n: rs.run_scenario(n) for n in (1, 2, 3)}
        assert_scenarios(runs)
        return runs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["record", "replay"])
    args = parser.parse_args()
    runs = run_all(args.mode)
    summary = {str(n): {"plan": [t.value for t in run.result.plan], "verdict": run.result.verdict.value,
                       "was_this_you": run.result.was_this_you} for n, run in runs.items()}
    if args.mode == "record":
        MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST.write_text(json.dumps({"profile": PROFILE, "recorded_at": datetime.now(timezone.utc).isoformat(),
            "classifier": "A1 baseline (real training split only); not the L7 evaluation model",
            "public_search": "unavailable by explicit profile choice", "scenarios": summary}, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"mode": args.mode, "profile": PROFILE, "scenarios": summary,
                      "fixtures": len(cache.list_fixtures())}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
