"""Evaluation harness (A13): score any model against our baseline and write eval/metrics.json.

Scores two test sets:
- A1's saved test split (`load_split().test`: `test_v1` + hand-written), per category;
- the public real SMS set from A5 (`ucirvine/sms_spam`), as spam vs ham.

Any model plugs in through a factory, `module:attr`, called as
`attr(train, val) -> predictor`, where `predictor.predict(messages)` returns one
taxonomy id per message. The factory may fit on `train` and tune on `val`; it
never sees test or the public set. Our baseline is
`scripts.evaluate:baseline_factory`.

Text condition: the classifier only ever sees redacted text in production
(DATA_SPEC 1), so the main rows are scored on redacted text for both models.
Phone hash tags are collapsed to `<PHONE_HASH>` because the per-number hash
carries no category signal and would make scores depend on the salt. The
redaction-cost row is our model trained and scored on raw text vs. redacted text.

Agent sample mode (`--agent-sample N --agent module:attr`) runs the full agent
on N test messages (stratified, fixed seed) and reports share correct and share
`unsure`. `attr(message) -> AgentResult | Verdict | str`.

Run from `backend/`:
    python -m scripts.evaluate                                  # ours = baseline stand-in until L7
    python -m scripts.evaluate --model app.classifier.train:make_model
    python -m scripts.evaluate --agent-sample 20 --agent app.pipeline:evaluate_message

Writes `eval/metrics.json` (the `Metrics` contract, served by GET /api/metrics)
and `eval/metrics_details.json` (both text conditions, subsets, confusion).
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import json
import os
import random
import re
import secrets
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from app.classifier.baseline import (
    LEGIT,
    Split,
    confusion,
    load_split,
    score,
    taxonomy_ids,
    train_baseline,
)
from app.config import DATA_DIR, EVAL_DIR
from app.contracts import (
    AgentSample,
    CategoryMetrics,
    Message,
    MessageSource,
    Metrics,
    OursVsBaseline,
    PublicSetMetrics,
    RedactionCost,
    Scores,
)

PUBLIC_DIR = DATA_DIR / "raw" / "public_sms"
PUBLIC_PARQUET = PUBLIC_DIR / "plain_text" / "train-00000-of-00001.parquet"
PUBLIC_DATASET = "ucirvine/sms_spam"
METRICS_PATH = EVAL_DIR / "metrics.json"
DETAILS_PATH = EVAL_DIR / "metrics_details.json"
AGENT_SEED = 7
_PHONE_TAG = re.compile(r"<PHONE_HASH_[0-9a-f]+>")


class Predictor(Protocol):
    def predict(self, messages: list[Message]) -> list[str]: ...


ModelFactory = Callable[[list[Message], list[Message]], Predictor]


def baseline_factory(train: list[Message], val: list[Message]) -> Predictor:
    """A1's baseline: fit on train only, no tuning (val unused)."""
    return train_baseline(train)


def load_object(spec: str) -> Any:
    """Import `package.module:attr`."""
    module_name, _, attr = spec.partition(":")
    if not module_name or not attr:
        raise ValueError(f"expected 'module:attr', got {spec!r}")
    return getattr(importlib.import_module(module_name), attr)


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


def ensure_redaction_salt() -> None:
    """redact() refuses to run without PHONE_HASH_SALT. Evaluation collapses the
    hash tags anyway, so a throwaway salt is fine when none is configured."""
    from app.config import get_settings

    salt = get_settings().PHONE_HASH_SALT
    if salt is None or not salt.get_secret_value().strip():
        os.environ["PHONE_HASH_SALT"] = secrets.token_hex(16)
        get_settings.cache_clear()


def redacted_text(text: str) -> str:
    from app.privacy.redact import redact

    return _PHONE_TAG.sub("<PHONE_HASH>", redact(text).text_redacted)


def redact_messages(messages: list[Message]) -> list[Message]:
    return [m.model_copy(update={"text": redacted_text(m.text)}) for m in messages]


def redact_split(split: Split) -> Split:
    return Split(train=redact_messages(split.train), val=redact_messages(split.val), test=redact_messages(split.test))


def load_public_set(path: Path = PUBLIC_PARQUET) -> list[Message] | None:
    """The public real SMS set as `Message`s (spam -> is_scam True). External
    evaluation in the original v1 protocol only. For the user-authorized L7
    follow-up, app.classifier.public_data loads saved development/holdout roles;
    never use this full-set loader to evaluate a public-trained model.
    Returns None when A5's download isn't present."""
    if not path.exists():
        return None
    import pandas as pd

    frame = pd.read_parquet(path)
    return [
        Message(
            message_id=f"pub_{i:05d}",
            text=str(row.sms).strip(),
            sender="unknown",
            is_scam=bool(int(row.label)),
            category=None,
            source=MessageSource.public,
        )
        for i, row in enumerate(frame.itertuples(index=False))
    ]


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def score_public(messages: list[Message], predictions: list[str]) -> dict[str, float]:
    """Spam = any scam category. Recall on spam, false positive rate on ham."""
    spam = [p != LEGIT for m, p in zip(messages, predictions) if m.is_scam]
    ham = [p != LEGIT for m, p in zip(messages, predictions) if not m.is_scam]
    flagged = sum(1 for p in predictions if p != LEGIT)
    tp = sum(spam)
    fp = sum(ham)
    fn, tn = len(spam)-tp, len(ham)-fp
    spam_f1 = 2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0.0
    ham_f1 = 2*tn/(2*tn+fp+fn) if 2*tn+fp+fn else 0.0
    return {
        "n": len(messages),
        "binary_macro_f1": (spam_f1+ham_f1)/2,
        "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        "spam": len(spam),
        "ham": len(ham),
        "spam_recall": tp / len(spam) if spam else 0.0,
        "false_positive_rate": sum(ham) / len(ham) if ham else 0.0,
        "spam_precision": tp / flagged if flagged else 0.0,
    }


def _predict(model: Predictor, messages: list[Message]) -> list[str]:
    preds = list(model.predict(messages))
    if len(preds) != len(messages):
        raise ValueError(f"predict() returned {len(preds)} labels for {len(messages)} messages")
    labels = set(taxonomy_ids())
    bad = sorted({p for p in preds if p not in labels})
    if bad:
        raise ValueError(f"predict() returned ids outside data/taxonomy.json: {bad}")
    return preds


def run_condition(factory: ModelFactory, split: Split, public: list[Message] | None, labels: list[str]) -> dict[str, Any]:
    """Fit through the factory on train/val, score on test and the public set."""
    model = factory(list(split.train), list(split.val))
    test_pred = _predict(model, split.test)
    gold = [m.category for m in split.test]
    hw = [i for i, m in enumerate(split.test) if m.source == MessageSource.handwritten]
    gen = [i for i, m in enumerate(split.test) if m.source != MessageSource.handwritten]
    out: dict[str, Any] = {
        "test": score(gold, test_pred, labels),
        "test_generated_only": score([gold[i] for i in gen], [test_pred[i] for i in gen], labels),
        "test_handwritten_only": score([gold[i] for i in hw], [test_pred[i] for i in hw], labels),
        "test_confusion": confusion(gold, test_pred),
        "public": None,
    }
    if public is not None:
        out["public"] = score_public(public, _predict(model, public))
    return out


def _scores(row: dict) -> Scores:
    return Scores(precision=round(row["precision"], 4), recall=round(row["recall"], 4), f1=round(row["f1"], 4))


def _r(x: float) -> float:
    return round(x, 4)


# ---------------------------------------------------------------------------
# Agent sample
# ---------------------------------------------------------------------------


def stratified_sample(messages: list[Message], n: int, seed: int = AGENT_SEED) -> list[Message]:
    """Round-robin over categories so a small sample still covers every one."""
    rng = random.Random(seed)
    by_cat: dict[str, list[Message]] = {}
    for m in sorted(messages, key=lambda m: m.message_id):
        by_cat.setdefault(m.category or "", []).append(m)
    for items in by_cat.values():
        rng.shuffle(items)
    out: list[Message] = []
    cats = sorted(by_cat)
    while len(out) < min(n, len(messages)):
        for c in cats:
            if by_cat[c] and len(out) < n:
                out.append(by_cat[c].pop())
    return out


def _verdict(result: Any) -> str:
    v = getattr(result, "verdict", result)
    return str(getattr(v, "value", v))


def agent_sample(agent: Callable[[Message], Any], test: list[Message], n: int) -> tuple[AgentSample, list[dict]]:
    """Run the full agent on a stratified sample of test messages. A verdict is
    correct when likely_scam matches a scam label or likely_safe a legit one;
    unsure is counted separately (neither correct nor wrong)."""
    sample = stratified_sample(test, n)
    rows, correct, unsure = [], 0, 0
    for m in sample:
        verdict = _verdict(agent(m))
        if verdict == "unsure":
            unsure += 1
        elif (verdict == "likely_scam") == bool(m.is_scam) and verdict in ("likely_scam", "likely_safe"):
            correct += 1
        rows.append({"message_id": m.message_id, "category": m.category, "verdict": verdict})
    k = len(sample)
    return AgentSample(n=k, share_correct=_r(correct / k) if k else 0.0, share_unsure=_r(unsure / k) if k else 0.0), rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def evaluate(
    ours: ModelFactory,
    baseline: ModelFactory = baseline_factory,
    *,
    split: Split | None = None,
    public: list[Message] | None = None,
    agent: Callable[[Message], Any] | None = None,
    agent_n: int = 0,
) -> tuple[Metrics, dict[str, Any]]:
    labels = taxonomy_ids()
    split = split if split is not None else load_split()
    ensure_redaction_salt()
    red_split = redact_split(split)
    red_public = redact_messages(public) if public is not None else None

    ours_red = run_condition(ours, red_split, red_public, labels)
    base_red = run_condition(baseline, red_split, red_public, labels)
    ours_raw = run_condition(ours, split, public, labels)
    base_raw = run_condition(baseline, split, public, labels)

    by_cat_ours = {row["category"]: row for row in ours_red["test"]["categories"]}
    by_cat_base = {row["category"]: row for row in base_red["test"]["categories"]}
    categories = [
        CategoryMetrics(category=c, support=by_cat_ours[c]["support"], ours=_scores(by_cat_ours[c]), baseline=_scores(by_cat_base[c]))
        for c in labels
    ]
    public_metrics = None
    if public is not None:
        public_metrics = PublicSetMetrics(
            dataset=PUBLIC_DATASET,
            n=len(public),
            spam_recall=OursVsBaseline(ours=_r(ours_red["public"]["spam_recall"]), baseline=_r(base_red["public"]["spam_recall"])),
            false_positive_rate=OursVsBaseline(
                ours=_r(ours_red["public"]["false_positive_rate"]), baseline=_r(base_red["public"]["false_positive_rate"])
            ),
        )
    sample, sample_rows = (None, [])
    if agent is not None and agent_n > 0:
        sample, sample_rows = agent_sample(agent, split.test, agent_n)  # the agent redacts on its own

    metrics = Metrics(
        generated_at=datetime.now(timezone.utc),
        n_test=len(split.test),
        categories=categories,
        macro_f1=OursVsBaseline(ours=_r(ours_red["test"]["macro_f1"]), baseline=_r(base_red["test"]["macro_f1"])),
        false_positive_rate=OursVsBaseline(
            ours=_r(ours_red["test"]["false_positive_rate"]), baseline=_r(base_red["test"]["false_positive_rate"])
        ),
        public_set=public_metrics,
        redaction_cost=RedactionCost(
            macro_f1_unredacted=_r(ours_raw["test"]["macro_f1"]), macro_f1_redacted=_r(ours_red["test"]["macro_f1"])
        ),
        agent_sample=sample,
    )
    details = {
        "conditions": {
            "redacted": {"ours": ours_red, "baseline": base_red},
            "raw": {"ours": ours_raw, "baseline": base_raw},
        },
        "split": {"train": len(split.train), "val": len(split.val), "test": len(split.test)},
        "public_set": {"dataset": PUBLIC_DATASET, "path": "data/raw/public_sms (A5, gitignored)", "present": public is not None},
        "agent_sample": sample_rows,
    }
    return metrics, _round_floats(details)


def _round_floats(obj: Any) -> Any:
    if isinstance(obj, float):
        return round(obj, 4)
    if isinstance(obj, dict):
        return {k: _round_floats(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round_floats(v) for v in obj]
    return obj


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score a model against the baseline and write eval/metrics.json.")
    parser.add_argument("--model", default="scripts.evaluate:baseline_factory", help="ours: factory 'module:attr' called as attr(train, val)")
    parser.add_argument("--agent", default=None, help="agent callable 'module:attr' called as attr(message)")
    parser.add_argument("--agent-sample", type=int, default=0, help="score the full agent on N test messages")
    parser.add_argument("--no-public", action="store_true", help="skip the public SMS set")
    parser.add_argument("--out", default=str(METRICS_PATH))
    args = parser.parse_args(argv)
    if args.agent_sample and not args.agent:
        parser.error("--agent-sample needs --agent module:attr (the full pipeline, L8/L9)")

    ours = load_object(args.model)
    if not callable(ours) or len(inspect.signature(ours).parameters) < 2:
        parser.error("--model must name a factory taking (train, val)")
    public = None if args.no_public else load_public_set()
    if public is None and not args.no_public:
        print(f"Public SMS set not found at {PUBLIC_PARQUET}; run `python -m scripts.setup_huggingface` (A5). Skipping it.")
    agent = load_object(args.agent) if args.agent else None

    metrics, details = evaluate(ours, public=public, agent=agent, agent_n=args.agent_sample)
    details = {"ours_model": args.model, "baseline_model": "scripts.evaluate:baseline_factory", **details}

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(metrics.model_dump_json(indent=2) + "\n", encoding="utf-8")
    out.with_name(out.stem + "_details.json").write_text(json.dumps(details, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"Ours: {args.model}" + ("  (baseline stand-in until L7)" if args.model.endswith(":baseline_factory") else ""))
    print(f"Test ({metrics.n_test}, redacted): macro F1 ours {metrics.macro_f1.ours:.3f} vs baseline {metrics.macro_f1.baseline:.3f}; "
          f"FPR ours {metrics.false_positive_rate.ours:.3f} vs baseline {metrics.false_positive_rate.baseline:.3f}")
    rc = metrics.redaction_cost
    print(f"Redaction cost (ours): macro F1 raw {rc.macro_f1_unredacted:.3f} -> redacted {rc.macro_f1_redacted:.3f}")
    if metrics.public_set:
        p = metrics.public_set
        print(f"Public {p.dataset} ({p.n}): spam recall ours {p.spam_recall.ours:.3f} vs baseline {p.spam_recall.baseline:.3f}; "
              f"FPR ours {p.false_positive_rate.ours:.3f} vs baseline {p.false_positive_rate.baseline:.3f}")
    if metrics.agent_sample:
        a = metrics.agent_sample
        print(f"Agent sample ({a.n}): correct {a.share_correct:.2f}, unsure {a.share_unsure:.2f}")
    print(f"Wrote {out} and {out.stem}_details.json")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
