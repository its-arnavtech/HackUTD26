"""Measure the Nemotron agent end to end on the held-out test split (L15 feature 1).

    python -m scripts.evaluate_agent --per-category 5     # 45 messages, about 8 minutes live

Run from `backend/` with NVIDIA_API_KEY set and DEMO_MODE=live. Writes
`eval/agent_metrics.json`, which `GET /api/agent-metrics` and the Agent accuracy
page serve. Prints progress per message (category, verdict, right or not),
never message text or keys.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from app import agent_eval
from app.agent.loop import run_agent
from app.config import get_settings
from app.pipeline import classify, warm_classifier


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--per-category", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20261108)
    args = parser.parse_args(argv)

    started = datetime.now(timezone.utc)
    sample = agent_eval.load_test_sample(args.per_category, args.seed)
    print(f"Agent evaluation: {len(sample)} held-out test messages, {args.per_category} per category")
    warm_classifier()

    def progress(i: int, o: agent_eval.Outcome) -> None:
        mark = "ok" if o.correct else ("unsure" if o.verdict == "unsure" else "WRONG")
        print(f"  {i:3d}/{len(sample)}  {o.category:18}  {o.verdict:12}  {mark:6}  {o.ms / 1000:5.1f}s  tools={len(o.tools)}", flush=True)

    outcomes = agent_eval.run(sample, run_agent, classify, progress)
    summary = agent_eval.summarize(outcomes, model=get_settings().NEMOTRON_MODEL, per_category=args.per_category, started_at=started)
    agent_eval.OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    agent_eval.OUTPUT.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"\naccuracy {summary['accuracy']}  unsure {summary['unsure']}  scams caught {summary['scams_caught']}  "
          f"false alarms {summary['false_alarms']}  avg {summary['avg_seconds']}s  -> {agent_eval.OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
