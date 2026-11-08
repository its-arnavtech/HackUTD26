"""How often the Nemotron agent itself is right (L15 feature 1).

The classifier is measured by A13 (`eval/metrics.json`). This measures the
agent, the part that makes the final call, end to end: our classifier, then the
live Nemotron agent with its tools, on a balanced sample from the **held-out
test split** of the multiclass set (`messages_multiclass.jsonl`, `split ==
"test"`, template set B). That's evaluation, which is what a test split is for:
nothing here trains, tunes, builds a blocklist or seeds a campaign.

Scoring, per message:
- a scam is right when the verdict is `likely_scam`
- a real message (`legit`) is right when the verdict is `likely_safe`
- `unsure` is its own bucket, never counted as right or wrong
"""

from __future__ import annotations

import json
import random
import statistics
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import DATA_DIR, EVAL_DIR

TEST_SET = DATA_DIR / "generated" / "messages_multiclass.jsonl"
OUTPUT = EVAL_DIR / "agent_metrics.json"


@dataclass
class Outcome:
    message_id: str
    category: str
    is_scam: bool
    verdict: str  # likely_scam | unsure | likely_safe | error
    ms: int
    tools: list[str] = field(default_factory=list)

    @property
    def correct(self) -> bool:
        return (self.verdict == "likely_scam") if self.is_scam else (self.verdict == "likely_safe")


def load_test_sample(per_category: int, seed: int = 20261108, path: Path = TEST_SET) -> list[dict[str, Any]]:
    """A balanced sample from the held-out test split only."""
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    test = [r for r in rows if r.get("split") == "test"]
    by_cat: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in test:
        by_cat[r["taxonomy_id"]].append(r)
    rng = random.Random(seed)
    sample: list[dict[str, Any]] = []
    for cat in sorted(by_cat):
        items = sorted(by_cat[cat], key=lambda r: r["message_id"])
        sample.extend(rng.sample(items, min(per_category, len(items))))
    return sample


def summarize(outcomes: Iterable[Outcome], *, model: str, per_category: int, started_at: datetime) -> dict[str, Any]:
    outcomes = list(outcomes)
    scored = [o for o in outcomes if o.verdict != "error"]
    n = len(scored)

    def share(xs: list[Outcome], pred: Callable[[Outcome], bool]) -> float | None:
        return round(sum(1 for x in xs if pred(x)) / len(xs), 4) if xs else None

    scams = [o for o in scored if o.is_scam]
    legit = [o for o in scored if not o.is_scam]
    categories = []
    for cat in sorted({o.category for o in scored}):
        rows = [o for o in scored if o.category == cat]
        categories.append({
            "category": cat,
            "n": len(rows),
            "correct": share(rows, lambda o: o.correct),
            "unsure": share(rows, lambda o: o.verdict == "unsure"),
            "wrong": share(rows, lambda o: not o.correct and o.verdict != "unsure"),
        })
    tool_counts = Counter(t for o in scored for t in o.tools)
    times = [o.ms for o in scored]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "started_at": started_at.isoformat(),
        "model": model,
        "split": "test",
        "dataset": "messages_multiclass.jsonl (template set B, held out)",
        "per_category": per_category,
        "n": n,
        "errors": len(outcomes) - n,
        "accuracy": share(scored, lambda o: o.correct),
        "unsure": share(scored, lambda o: o.verdict == "unsure"),
        "scams_caught": share(scams, lambda o: o.verdict == "likely_scam"),
        "false_alarms": share(legit, lambda o: o.verdict == "likely_scam"),
        "avg_seconds": round(statistics.mean(times) / 1000, 2) if times else None,
        "worst_seconds": round(max(times) / 1000, 2) if times else None,
        "avg_tool_calls": round(statistics.mean(len(o.tools) for o in scored), 2) if scored else None,
        "tool_use": {k: round(v / n, 3) for k, v in tool_counts.most_common()} if n else {},
        "categories": categories,
    }


def to_agent_input(record: dict[str, Any], classify: Callable[..., Any]):
    """A test record (already redacted) as the agent's input, with OUR classifier's output, not the file's."""
    from app.contracts import AgentInput, Features
    from app.features.extract import extract_features

    features: Features = extract_features(record["text_redacted"])
    return AgentInput.model_validate({
        "message_id": record["message_id"],
        "mode": "check",
        "received_at": record["received_at"],
        "sender": record["sender"],
        "text_redacted": record["text_redacted"],
        "urls": record.get("urls") or [],
        "features": features.model_dump(mode="json"),
        "classifier": classify(record["text_redacted"], features).model_dump(mode="json"),
        "customer_context": record.get("customer_context") or {"linked_bank": False, "linked_institutions": []},
    })


def run(
    sample: list[dict[str, Any]],
    agent: Callable[..., Any],
    classify: Callable[..., Any],
    on_progress: Callable[[int, Outcome], None] | None = None,
) -> list[Outcome]:
    outcomes: list[Outcome] = []
    for i, record in enumerate(sample, 1):
        started = time.perf_counter()
        trail: list[Any] = []
        try:
            result = agent(to_agent_input(record, classify), trail.append)
            verdict = result.verdict.value
        except Exception:  # noqa: BLE001 - one bad message must not stop the run
            verdict = "error"
        outcome = Outcome(
            message_id=record["message_id"],
            category=record["taxonomy_id"],
            is_scam=bool(record["is_scam"]),
            verdict=verdict,
            ms=round((time.perf_counter() - started) * 1000),
            tools=[t.tool.value for t in trail if getattr(t, "kind", None) and t.kind.value == "tool" and t.tool],
        )
        outcomes.append(outcome)
        if on_progress:
            on_progress(i, outcome)
    return outcomes


def read(path: Path | None = None) -> dict[str, Any] | None:
    path = path or OUTPUT
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
