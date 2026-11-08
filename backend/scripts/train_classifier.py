"""Train L7 with A1 train and validation only; never score test/public here.

From backend: python -m scripts.train_classifier
Final A13 evaluation is a separate, explicit step after selection is frozen.
"""
from __future__ import annotations

import argparse
import json
import hashlib
from pathlib import Path

from app.classifier.baseline import load_split
from app.classifier.train import MODEL_PATH, input_digest, load_model, save_model, train
from app.config import EVAL_DIR
from scripts import evaluate as evaluation
from scripts.evaluate import ensure_redaction_salt, redact_messages


def binary_macro_f1(row: dict) -> float:
    """Public set has binary labels; derive its two-class F1 from A13 counts."""
    tp = row["spam_recall"] * row["spam"]
    fp = row["false_positive_rate"] * row["ham"]
    fn, tn = row["spam"] - tp, row["ham"] - fp
    spam_f1 = 2*tp / (2*tp+fp+fn) if 2*tp+fp+fn else 0.0
    ham_f1 = 2*tn / (2*tn+fp+fn) if 2*tn+fp+fn else 0.0
    return (spam_f1+ham_f1)/2


def final_evaluation(model_path: Path, final_path: Path, metrics_path: Path) -> dict:
    """One final A13 run. Both text-condition models freeze before test scoring.

    The raw-cost control uses the selected representation/C and tunes only its
    legitimate bias on raw validation. It never replaces the production model.
    A persistent marker prevents accidental repeated held-out evaluation.
    """
    if final_path.exists():
        raise FileExistsError("Final evaluation already started/completed; do not tune or repeat on these test sets")
    split = load_split()
    ensure_redaction_salt()
    model = load_model(model_path)
    red_digest = input_digest(redact_messages(split.train), redact_messages(split.val))
    if model.report["input_digest"] != red_digest:
        raise ValueError("Artifact does not match saved redacted train/validation data; retrain before final evaluation")
    raw_model = train(split.train, split.val, configs=(model.config,))
    raw_digest = input_digest(split.train, split.val)
    def frozen_factory(train_rows, val_rows):
        digest = input_digest(train_rows, val_rows)
        if digest == red_digest:
            return model
        if digest == raw_digest:
            return raw_model
        raise ValueError("A13 supplied an unexpected training condition")
    # Select both models before loading public messages or scoring any test row.
    public = evaluation.load_public_set()
    if public is None:
        raise FileNotFoundError("A5 public SMS set is required for the final L7 evaluation")
    final_path.parent.mkdir(parents=True, exist_ok=True)
    with final_path.open("x", encoding="utf-8") as stream:
        json.dump({"status": "started", "selection_frozen": model.report["selected"]}, stream)
    metrics, details = evaluation.evaluate(frozen_factory, split=split, public=public)
    public_scores = {name: binary_macro_f1(details["conditions"]["redacted"][name]["public"]) for name in ("ours", "baseline")}
    synthetic = details["conditions"]["redacted"]["ours"]["test"]
    public_rows = details["conditions"]["redacted"]
    report = {"status": "complete", "algorithm": model.report["algorithm"],
              "model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
              "selection_frozen": model.report["selected"], "split_digest": model.report["split_digest"],
              "raw_control_selection": raw_model.report["selected"],
              "protocol": "one final A13 evaluation; train-only fits; validation-only selection; raw control frozen before scoring; no post-test tuning",
              "synthetic_macro_f1": synthetic["macro_f1"], "synthetic_false_positive_rate": synthetic["false_positive_rate"],
              "synthetic_strict_target_met": synthetic["macro_f1"] > 0.807 and synthetic["false_positive_rate"] <= 0.127,
              "public_binary_macro_f1": public_scores,
              "public_no_worse_than_baseline": public_scores["ours"] >= public_scores["baseline"] and public_rows["ours"]["public"]["false_positive_rate"] <= public_rows["baseline"]["public"]["false_positive_rate"],
              "optional_encoders": "not attempted; local sparse model selected on validation",
              "raw_control_note": "same selected TF-IDF representation/C; raw validation selects legit bias; production artifact remains redacted"}
    details.update({"ours_model": "frozen local L7 artifact", "baseline_model": "scripts.evaluate:baseline_factory",
                    "l7_final_protocol": report["protocol"], "public_binary_macro_f1": public_scores})
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.write_text(metrics.model_dump_json(indent=2)+"\n", encoding="utf-8")
    metrics_path.with_name(metrics_path.stem+"_details.json").write_text(json.dumps(details, indent=2)+"\n", encoding="utf-8")
    final_path.write_text(json.dumps(report, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=MODEL_PATH)
    parser.add_argument("--report", type=Path, default=EVAL_DIR / "classifier_validation.json")
    parser.add_argument("--evaluate", action="store_true", help="one final A13 run on both held-out sets using the frozen artifact")
    parser.add_argument("--final-report", type=Path, default=EVAL_DIR / "classifier_final.json")
    parser.add_argument("--metrics", type=Path, default=EVAL_DIR / "metrics.json")
    args = parser.parse_args(argv)
    if args.evaluate:
        print(json.dumps(final_evaluation(args.model, args.final_report, args.metrics), sort_keys=True))
        return 0
    split = load_split()  # Only train/val are passed to training; test stays untouched.
    ensure_redaction_salt()
    model = train(redact_messages(split.train), redact_messages(split.val))
    save_model(model, args.model)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(model.report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in model.report.items() if key != "trials"}, sort_keys=True))
    print(f"Saved local artifact: {args.model}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
