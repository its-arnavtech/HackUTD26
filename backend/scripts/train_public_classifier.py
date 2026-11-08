"""L7 follow-up: train on public development only; one final held-out run.

python -m scripts.train_public_classifier --prepare-split
python -m scripts.train_public_classifier
python -m scripts.train_public_classifier --evaluate
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from app.classifier import public_data
from app.classifier.baseline import Split, load_split, taxonomy_ids
from app.classifier.hybrid import MODEL_PATH, data_digest, load_hybrid, save_hybrid, train_hybrid
from app.classifier.train import Config, MODEL_PATH as V1_MODEL, load_model, train as train_v1
from app.config import EVAL_DIR
from app.contracts import CategoryMetrics, Metrics, OursVsBaseline, PublicSetMetrics
from scripts import evaluate as ev

FINAL_REPORT = EVAL_DIR / "classifier_v2_final.json"
ARCHIVE = EVAL_DIR / "classifier_v1"


def development():
    split = load_split()
    ev.ensure_redaction_salt()
    synthetic_train, synthetic_val = ev.redact_messages(split.train), ev.redact_messages(split.val)
    public_train = ev.redact_messages(public_data.load_partition("train"))
    public_val = ev.redact_messages(public_data.load_partition("val"))
    return split, (synthetic_train, synthetic_val, public_train, public_val)


def frozen_v1(synthetic_train, synthetic_val):
    previous = json.loads((ARCHIVE / "classifier_validation.json").read_text(encoding="utf-8"))
    if V1_MODEL.exists():
        model = load_model(V1_MODEL)
        if model.report["input_digest"] != previous["input_digest"] or model.report["selected"] != previous["selected"]:
            raise ValueError("Local v1 artifact is not the archived frozen comparison")
        return model
    selected = previous["selected"]
    # Reconstruct only the historically frozen configuration, never tune against
    # the new public rows or choose from models based on test results.
    model = train_v1(synthetic_train, synthetic_val,
                     configs=(Config(selected["c"], selected["char_weight"], selected["feature_weight"]),))
    model.legit_bias = selected["legit_bias"]
    return model


def evaluate_once(model_path: Path = MODEL_PATH, final_path: Path = FINAL_REPORT,
                  metrics_path: Path = EVAL_DIR / "metrics.json") -> dict:
    if final_path.exists():
        raise FileExistsError("Follow-up final evaluation already started/completed; do not retune on held-out results")
    split, partitions = development()
    model = load_hybrid(model_path)
    if model.report["input_digest"] != data_digest(*partitions):
        raise ValueError("Frozen artifact does not match saved development inputs")
    previous = frozen_v1(*partitions[:2])
    archived_metrics = json.loads((ARCHIVE / "metrics.json").read_text(encoding="utf-8"))
    archived_details = json.loads((ARCHIVE / "metrics_details.json").read_text(encoding="utf-8"))
    saved = public_data.read_split()
    if model.report["public_split_digest"] != public_data.guard_public(*partitions[2:]):
        raise ValueError("Frozen artifact public roles differ from saved split")
    final_path.parent.mkdir(parents=True, exist_ok=True)
    with final_path.open("x", encoding="utf-8") as stream:
        json.dump({"status": "started", "selection_frozen": model.report["selected"],
                   "model_sha256": public_data.checksum(model_path)}, stream)
    # First holdout text access since assigning roles. No training follows this.
    public = ev.redact_messages(public_data.load_partition("test", final_scoring=True))
    red_split = Split(partitions[0], partitions[1], ev.redact_messages(split.test))
    # A13 scores this frozen model ONCE on each held-out set.
    ours = ev.run_condition(lambda train, val: model, red_split, public, taxonomy_ids())
    # Pairwise public comparisons use precisely the same new holdout; synthetic
    # v1/baseline results are reused from archives rather than rescored.
    old_public = ev.score_public(public, ev._predict(previous, public))
    baseline_public = ev.score_public(public, ev._predict(model.baseline, public))
    baseline = {**archived_details["conditions"]["redacted"]["baseline"], "public": baseline_public}
    categories = [CategoryMetrics(category=row["category"], support=row["support"], ours=ev._scores(row),
                  baseline=ev._scores(baseline["test"]["categories"][index]))
                  for index, row in enumerate(ours["test"]["categories"])]
    metrics = Metrics(generated_at=datetime.now(timezone.utc), n_test=len(split.test), categories=categories,
        macro_f1=OursVsBaseline(ours=ev._r(ours["test"]["macro_f1"]), baseline=ev._r(baseline["test"]["macro_f1"])),
        false_positive_rate=OursVsBaseline(ours=ev._r(ours["test"]["false_positive_rate"]), baseline=ev._r(baseline["test"]["false_positive_rate"])),
        public_set=PublicSetMetrics(dataset=f"ucirvine/sms_spam: saved 50% holdout (seed {saved['seed']})", n=len(public),
            spam_recall=OursVsBaseline(ours=ev._r(ours["public"]["spam_recall"]), baseline=ev._r(baseline_public["spam_recall"])),
            false_positive_rate=OursVsBaseline(ours=ev._r(ours["public"]["false_positive_rate"]), baseline=ev._r(baseline_public["false_positive_rate"]))),
        redaction_cost=None)  # No new raw-text test pass; historical v1 cost is archived.
    comparison = {
        "synthetic_test": {"n": len(split.test), "v1": archived_details["conditions"]["redacted"]["ours"]["test"], "v2": ours["test"]},
        "public_same_holdout": {"n": len(public), "v1": old_public, "v2": ours["public"], "baseline": baseline_public},
        "public_original_full_set_v1": {"n": archived_metrics["public_set"]["n"],
            "metrics": archived_details["conditions"]["redacted"]["ours"]["public"],
            "binary_macro_f1": json.loads((ARCHIVE / "classifier_final.json").read_text())["public_binary_macro_f1"]["ours"]}}
    report = {"status": "complete", "algorithm": model.report["algorithm"], "selection_frozen": model.report["selected"],
        "model_sha256": public_data.checksum(model_path), "public_split_digest": model.report["public_split_digest"],
        "counts": model.report["counts"], "public_holdout_counts": saved["counts"]["test"], "seed": saved["seed"],
        "protocol": "public development/holdout 50/50; 20% of development validation; train-only fits; synthetic/public validation only; one final redacted scoring run; no post-test tuning",
        "prior_exposure": saved["prior_exposure"], "comparison": comparison,
        "redaction_cost": "not rerun for v2; historical v1 cost remains archived",
        "synthetic_target_met": ours["test"]["macro_f1"] > 0.807 and ours["test"]["false_positive_rate"] <= 0.127,
        "public_improves_baseline": ours["public"]["binary_macro_f1"] > baseline_public["binary_macro_f1"] and ours["public"]["false_positive_rate"] <= baseline_public["false_positive_rate"],
        "public_improves_v1": ours["public"]["binary_macro_f1"] > old_public["binary_macro_f1"] and ours["public"]["false_positive_rate"] <= old_public["false_positive_rate"]}
    details = {"ours_model": "frozen public-binary v2 artifact", "baseline_model": "original synthetic-only A1 baseline",
        "conditions": {"redacted": {"ours": ours, "baseline": baseline},
                       "raw": {**archived_details["conditions"]["raw"], "historical_v1_only": True}},
        "comparison": comparison, "public_split": {"seed": saved["seed"], "counts": saved["counts"], "prior_exposure": saved["prior_exposure"]},
        "split": {"train": len(partitions[0]), "val": len(partitions[1]), "test": len(split.test)},
        "redaction_cost_note": report["redaction_cost"]}
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.write_text(metrics.model_dump_json(indent=2)+"\n", encoding="utf-8")
    metrics_path.with_name(metrics_path.stem+"_details.json").write_text(json.dumps(ev._round_floats(details), indent=2)+"\n", encoding="utf-8")
    final_path.write_text(json.dumps(ev._round_floats(report), indent=2, sort_keys=True)+"\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-split", action="store_true")
    parser.add_argument("--evaluate", action="store_true")
    parser.add_argument("--model", type=Path, default=MODEL_PATH)
    parser.add_argument("--report", type=Path, default=EVAL_DIR / "classifier_validation.json")
    args = parser.parse_args(argv)
    if args.prepare_split:
        saved = public_data.create_split()
        print(json.dumps({"seed": saved["seed"], "counts": saved["counts"], "normalized_text_groups": saved["normalized_text_groups"]}))
    elif args.evaluate:
        report = evaluate_once(args.model)
        print(json.dumps({key: report[key] for key in ("status", "synthetic_target_met", "public_improves_v1", "public_holdout_counts")}))
    else:
        _, partitions = development()
        model = train_hybrid(*partitions)
        save_hybrid(model, args.model)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(model.report, indent=2, sort_keys=True)+"\n", encoding="utf-8")
        print(json.dumps({key: value for key, value in model.report.items() if key != "trials"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
