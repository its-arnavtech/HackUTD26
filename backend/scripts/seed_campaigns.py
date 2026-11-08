"""A12 bootstrap: train-only fingerprints, validation-only threshold, optional demo probe.

From backend: python -m scripts.seed_campaigns --verify-scenario3
No keys except local PHONE_HASH_SALT are needed; no network calls are made.
The authored scenario is loaded ONLY AFTER calibration and training seeding.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.config import DATA_DIR
from app.contracts import MatchCampaignArgs, Message
from app.tools.campaign import (calibrate_threshold, list_campaigns, load_training_validation,
                                match_campaign, message_input, seed_campaigns)
from app.tools.campaign_store import CampaignStore


def verify_scenario3(store: CampaignStore, path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    query = message_input(Message(message_id="scenario_3", source="authored", prompt_set="scenario",
                                  category="billing_scam", is_scam=True, **data["message"]))
    match = match_campaign(MatchCampaignArgs(message_id=query.message_id), query, store=store)
    cards = {card.campaign_id: card for card in list_campaigns(store=store, as_of=query.received_at)}
    support = cards[match.campaign_id].count_total if match.campaign_id in cards else 0
    return {"query_source": "authored scenario 3; category is annotated, not a classifier prediction",
            "query_time": query.received_at.isoformat(), "campaign_id": match.campaign_id,
            "similarity": match.similarity, "historical_support": support,
            "similar_last_24h": match.similar_last_24h,
            "matched_real_campaign": match.campaign_id is not None and support > 1}


def run(generated_dir: Path, splits_path: Path, database: str | Path, *, scenario_path: Path | None = None) -> dict:
    train, validation = load_training_validation(generated_dir, splits_path=splits_path)
    store = CampaignStore(database)
    try:
        calibration = calibrate_threshold(train, validation, store=store, splits_path=splits_path)
        added = seed_campaigns(train, store=store, splits_path=splits_path)
        result = {"calibration": calibration, "validation_metric": "brand/category family proxy, not campaign ground truth",
                  "new_fingerprints": added, "stored_fingerprints": store.count(),
                  "campaigns": len({member.campaign_id for member in store.members()}),
                  "timestamp_policy": "original received_at; no re-dating or fabricated 24-hour counts"}
        if scenario_path is not None:
            result["scenario3"] = verify_scenario3(store, scenario_path)
        return result
    finally:
        store.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generated-dir", type=Path, default=DATA_DIR / "generated")
    parser.add_argument("--splits", type=Path, default=DATA_DIR / "generated" / "splits.json")
    parser.add_argument("--database", default=str(DATA_DIR / "campaigns.sqlite3"))
    parser.add_argument("--report", type=Path, default=DATA_DIR / "campaign_calibration.json")
    parser.add_argument("--verify-scenario3", action="store_true")
    parser.add_argument("--scenario", type=Path, default=DATA_DIR / "scenarios" / "scenario_3.json")
    args = parser.parse_args()
    try:
        report = run(args.generated_dir, args.splits, args.database,
                     scenario_path=args.scenario if args.verify_scenario3 else None)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(report, sort_keys=True))  # Aggregate metadata only.
        return 0 if report.get("scenario3", {}).get("matched_real_campaign", True) else 2
    except Exception as exc:
        # Provider/Pydantic exceptions can contain raw input; never echo them.
        print(f"Campaign seed failed: {type(exc).__name__}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
