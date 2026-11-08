"""A13: evaluation harness. Offline and fast (tiny data; one full CLI run)."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from app.classifier.baseline import Split, taxonomy_ids
from app.config import EVAL_DIR, get_settings
from app.contracts import AgentResult, BaselineMetrics, Message, MessageSource, Metrics
from scripts import evaluate as ev


@pytest.fixture(autouse=True)
def salt(monkeypatch):
    monkeypatch.setenv("PHONE_HASH_SALT", "a13-test-salt")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _m(mid, text, cat, prompt_set="train_v1", source=MessageSource.generated):
    return Message(message_id=mid, text=text, sender="+15550100000", is_scam=cat != "legit", category=cat, source=source, prompt_set=prompt_set)


TEXTS = {
    "delivery_scam": ["USPS parcel held, pay redelivery fee at usps-fix.top", "FedEx package customs fee due today, pay now", "UPS parcel tracking: redelivery fee required"],
    "bank_impersonation": ["Chase card locked, verify identity now", "Wells Fargo fraud alert, confirm your debit card", "Bank account frozen, verify card details today"],
    "legit": ["can you grab milk on the way home", "see you at dinner tonight, bring the salad", "running late, home by 7, call 214-555-0143"],
}


def tiny_split() -> Split:
    train, test = [], []
    for cat, texts in TEXTS.items():
        for i, t in enumerate(texts):
            train.append(_m(f"tr_{cat}_{i}", t, cat))
            test.append(_m(f"te_{cat}_{i}", t + " please", cat, "test_v1"))
    test.append(_m("hw_1", "Hi Linda, your package fee is due at usps-fix.top", "delivery_scam", "handwritten", MessageSource.handwritten))
    return Split(train=train, val=train[:3], test=test)


class Oracle:
    def predict(self, messages):
        return [m.category or "legit" for m in messages]


class AllLegit:
    def predict(self, messages):
        return ["legit"] * len(messages)


def oracle_factory(train, val):
    assert all(m.prompt_set == "train_v1" for m in train + val)  # never handed test
    return Oracle()


def legit_factory(train, val):
    return AllLegit()


# --- scoring ---------------------------------------------------------------------


def test_oracle_vs_all_legit():
    metrics, details = ev.evaluate(oracle_factory, legit_factory, split=tiny_split())
    assert isinstance(metrics, Metrics)
    assert metrics.macro_f1.ours == 1.0 and metrics.false_positive_rate.ours == 0.0
    assert metrics.false_positive_rate.baseline == 0.0
    assert details["conditions"]["redacted"]["baseline"]["test"]["scam_recall"] == 0.0
    assert [c.category for c in metrics.categories] == taxonomy_ids()
    assert metrics.redaction_cost.macro_f1_unredacted == metrics.redaction_cost.macro_f1_redacted == 1.0
    assert metrics.public_set is None and metrics.agent_sample is None


def test_models_see_redacted_text_in_main_condition():
    seen = []

    class Spy:
        def predict(self, messages):
            seen.extend(m.text for m in messages)
            return ["legit"] * len(messages)

    ev.evaluate(lambda tr, va: Spy(), legit_factory, split=tiny_split())
    assert any("<PERSON>" in t for t in seen)  # redacted pass ("Hi Linda")
    assert any("Linda" in t for t in seen)  # raw pass for the redaction-cost row
    assert any("<PHONE_HASH>" in t for t in seen) and not any("<PHONE_HASH_" in t for t in seen)


def test_bad_predictions_are_rejected():
    class Short:
        def predict(self, messages):
            return ["legit"]

    class Unknown:
        def predict(self, messages):
            return ["spam"] * len(messages)

    with pytest.raises(ValueError):
        ev.evaluate(lambda tr, va: Short(), legit_factory, split=tiny_split())
    with pytest.raises(ValueError):
        ev.evaluate(lambda tr, va: Unknown(), legit_factory, split=tiny_split())


def test_score_public():
    msgs = [Message(message_id=f"p{i}", text="x", sender="unknown", is_scam=s, source=MessageSource.public) for i, s in enumerate([True, True, False, False, False, False])]
    s = ev.score_public(msgs, ["billing_scam", "legit", "legit", "legit", "legit", "job_offer"])
    assert s["spam_recall"] == 0.5 and s["false_positive_rate"] == 0.25 and s["spam_precision"] == 0.5


def test_public_set_scored_with_both_models(tmp_path):
    path = tmp_path / "sms.parquet"
    pd.DataFrame({"sms": ["WIN a free prize, txt CLAIM now", "see you at 5"], "label": [1, 0]}).to_parquet(path)
    public = ev.load_public_set(path)
    assert [m.is_scam for m in public] == [True, False] and all(m.category is None for m in public)
    metrics, _ = ev.evaluate(lambda tr, va: Oracle(), legit_factory, split=tiny_split(), public=public)
    assert metrics.public_set.n == 2
    assert metrics.public_set.spam_recall.baseline == 0.0
    assert metrics.public_set.false_positive_rate.ours == 0.0  # oracle says legit for category=None


def test_missing_public_set_returns_none(tmp_path):
    assert ev.load_public_set(tmp_path / "nope.parquet") is None


# --- agent sample ------------------------------------------------------------------


def test_stratified_sample_is_deterministic_and_covers_categories():
    test = tiny_split().test
    a = ev.stratified_sample(test, 3)
    assert [m.message_id for m in a] == [m.message_id for m in ev.stratified_sample(test, 3)]
    assert {m.category for m in a} == set(TEXTS)


def test_agent_sample_counts_correct_and_unsure():
    def agent(m):
        if m.category == "legit":
            return "unsure"
        return AgentResult(plan=[], verdict="likely_scam", confidence_words="likely", reason="r")

    sample, rows = ev.agent_sample(agent, tiny_split().test, 6)
    assert sample.n == 6 and len(rows) == 6
    assert sample.share_unsure == pytest.approx(2 / 6, abs=1e-3)
    assert sample.share_correct == pytest.approx(4 / 6, abs=1e-3)


# --- CLI and committed output -------------------------------------------------------


def test_load_object():
    assert ev.load_object("scripts.evaluate:baseline_factory") is ev.baseline_factory
    with pytest.raises(ValueError):
        ev.load_object("no_colon_here")


def test_cli_writes_valid_metrics(tmp_path):
    out = tmp_path / "metrics.json"
    assert ev.main(["--no-public", "--out", str(out)]) == 0
    m = Metrics.model_validate_json(out.read_text(encoding="utf-8"))
    assert m.n_test == 388 and m.public_set is None
    assert m.macro_f1.ours == m.macro_f1.baseline  # ours is the baseline stand-in
    details = json.loads((tmp_path / "metrics_details.json").read_text(encoding="utf-8"))
    assert details["ours_model"] == "scripts.evaluate:baseline_factory"


def test_cli_rejects_agent_sample_without_agent():
    with pytest.raises(SystemExit):
        ev.main(["--agent-sample", "5"])


def test_committed_metrics_match_a1_baseline_on_raw_text():
    """The raw-text condition reproduces A1's gate P1 numbers exactly."""
    metrics = Metrics.model_validate_json((EVAL_DIR / "metrics.json").read_text(encoding="utf-8"))
    a1 = BaselineMetrics.model_validate_json((EVAL_DIR / "baseline_metrics.json").read_text(encoding="utf-8"))
    raw = json.loads((EVAL_DIR / "metrics_details.json").read_text(encoding="utf-8"))["conditions"]["raw"]["baseline"]["test"]
    assert metrics.n_test == a1.n_test
    assert raw["macro_f1"] == a1.macro_f1 and raw["false_positive_rate"] == a1.false_positive_rate
