"""Run our baseline (keyword rules plus TF-IDF and logistic regression) on the held-out test split (A1, gate P1).

Writes:
- `data/generated/splits.json`: the saved 70/15/15 split (message ids)
- `eval/baseline_metrics.json`: the `BaselineMetrics` contract, scored on test
- `eval/baseline_details.json`: validation scores, test scores per subset
  (`test_v1` vs hand-written), binary scam recall/precision, confusion matrix

The model is fit on train only, with default settings. Validation is reported
but nothing is tuned on it, and test is scored once at the end.

Run from `backend/`: `python -m scripts.run_baseline`
"""

from __future__ import annotations

import json
import sys

from app.classifier.baseline import (
    SPLITS_PATH,
    confusion,
    is_handwritten,
    load_messages,
    save_split,
    score,
    stratified_split,
    taxonomy_ids,
    train_baseline,
    baseline_metrics,
)
from app.config import EVAL_DIR


def _r(x: float) -> float:
    return round(x, 4)


def _summary(s: dict) -> dict:
    return {k: (_r(v) if isinstance(v, float) else v) for k, v in s.items() if k != "categories"} | {
        "per_category_f1": {row["category"]: _r(row["f1"]) for row in s["categories"] if row["support"]}
    }


def main(argv: list[str] | None = None) -> int:
    messages = load_messages()
    split = stratified_split(messages)
    save_split(split)
    labels = taxonomy_ids()

    model = train_baseline(split.train)
    val_pred = model.predict(split.val)
    test_pred = model.predict(split.test)

    metrics = baseline_metrics(split.test, test_pred)
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    (EVAL_DIR / "baseline_metrics.json").write_text(metrics.model_dump_json(indent=2) + "\n", encoding="utf-8")

    gold_test = [m.category for m in split.test]
    hw = [i for i, m in enumerate(split.test) if is_handwritten(m)]
    gen = [i for i, m in enumerate(split.test) if not is_handwritten(m)]
    details = {
        "model": "keyword rules (15 binary features) + TF-IDF word 1-2 grams (min_df=2, sublinear tf) -> LogisticRegression (defaults, max_iter=2000)",
        "split": {"seed": 42, "train": len(split.train), "val": len(split.val), "test": len(split.test), "saved_to": SPLITS_PATH.relative_to(SPLITS_PATH.parents[2]).as_posix()},
        "val": _summary(score([m.category for m in split.val], val_pred, labels)),
        "test": _summary(score(gold_test, test_pred, labels)),
        "test_generated_only": _summary(score([gold_test[i] for i in gen], [test_pred[i] for i in gen], labels)),
        "test_handwritten_only": _summary(score([gold_test[i] for i in hw], [test_pred[i] for i in hw], labels)),
        "test_confusion": confusion(gold_test, test_pred),
        "test_handwritten_errors": [
            {"message_id": split.test[i].message_id, "gold": gold_test[i], "pred": test_pred[i], "text": split.test[i].text}
            for i in hw
            if gold_test[i] != test_pred[i]
        ],
    }
    (EVAL_DIR / "baseline_details.json").write_text(json.dumps(details, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"Split: train {len(split.train)}, val {len(split.val)}, test {len(split.test)} (saved to {SPLITS_PATH.name})")
    print(f"Val:  macro F1 {details['val']['macro_f1']:.3f}, FPR {details['val']['false_positive_rate']:.3f}")
    print(f"Test: macro F1 {metrics.macro_f1:.3f}, FPR {metrics.false_positive_rate:.3f}, scam recall {details['test']['scam_recall']:.3f}")
    print(f"  test_v1 only:     macro F1 {details['test_generated_only']['macro_f1']:.3f}, FPR {details['test_generated_only']['false_positive_rate']:.3f}")
    print(f"  hand-written only: macro F1 {details['test_handwritten_only']['macro_f1']:.3f}, FPR {details['test_handwritten_only']['false_positive_rate']:.3f}")
    print("Per category (test): " + ", ".join(f"{c.category} {c.f1:.2f}" for c in metrics.categories))
    print(f"Wrote {EVAL_DIR / 'baseline_metrics.json'} and baseline_details.json")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
