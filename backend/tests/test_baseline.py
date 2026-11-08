"""A1: loader, saved stratified split and baseline (gate P1). Offline."""

from __future__ import annotations

import json
from collections import Counter

import pytest

from app.classifier import baseline as bl
from app.config import EVAL_DIR
from app.contracts import BaselineMetrics, Message, MessageSource


@pytest.fixture(scope="module")
def messages():
    return bl.load_messages()


@pytest.fixture(scope="module")
def split(messages):
    return bl.stratified_split(messages)


def _msg(mid, text, category, prompt_set="train_v1"):
    return Message(
        message_id=mid,
        text=text,
        sender="+15550100000",
        is_scam=category != "legit",
        category=category,
        source=MessageSource.handwritten if prompt_set == "handwritten" else MessageSource.generated,
        prompt_set=prompt_set,
    )


# --- loader and split -----------------------------------------------------------


def test_loader_reads_generated_and_handwritten(messages):
    assert all(isinstance(m, Message) for m in messages)
    sets = Counter(m.prompt_set for m in messages)
    assert sets["train_v1"] > 0 and sets["test_v1"] > 0 and sets["handwritten"] > 0
    assert len({m.message_id for m in messages}) == len(messages)


def test_split_is_70_15_15_and_disjoint(messages, split):
    n = len(messages)
    assert len(split.train) + len(split.val) + len(split.test) == n
    assert abs(len(split.train) / n - 0.70) < 0.01
    assert abs(len(split.val) / n - 0.15) < 0.01
    assert abs(len(split.test) / n - 0.15) < 0.01
    ids = split.ids()
    assert not set(ids["train"]) & set(ids["val"])
    assert not set(ids["train"]) & set(ids["test"])
    assert not set(ids["val"]) & set(ids["test"])


def test_test_split_is_the_separate_prompt_set(split):
    assert {m.prompt_set for m in split.test} == {"test_v1", "handwritten"}
    assert {m.prompt_set for m in split.train + split.val} == {"train_v1"}


def test_split_is_stratified(split):
    train = Counter(m.category for m in split.train)
    val = Counter(m.category for m in split.val)
    for cat in train:
        share_train = train[cat] / len(split.train)
        share_val = val[cat] / len(split.val)
        assert abs(share_train - share_val) < 0.01, cat


def test_split_is_deterministic_and_matches_saved(messages, split):
    assert bl.stratified_split(messages).ids() == split.ids()
    saved = bl.load_split(messages)
    assert saved.ids() == split.ids()


def test_unknown_prompt_set_is_rejected():
    with pytest.raises(ValueError):
        bl.stratified_split([_msg("x1", "hello there friend", "legit", prompt_set="mystery")])


# --- keyword rules and model ------------------------------------------------------


def test_keyword_features_fire():
    X = bl.keyword_features(
        [
            "USPS: your parcel is held, pay $1.99 at usps-help.top now",
            "Your code is 123456. Never share it. Reply STOP to opt out.",
        ]
    ).toarray()
    names = list(bl.KEYWORD_RULES)
    assert X.shape == (2, len(names))
    first, second = dict(zip(names, X[0])), dict(zip(names, X[1]))
    assert first["delivery"] and first["url"] and first["money"] and first["urgency"]
    assert second["do_not_share"] and second["reply_stop"] and not second["url"]


def test_model_refuses_test_split_messages():
    test_msg = _msg("hw_x", "hey it's me, new number", "legit", prompt_set="handwritten")
    with pytest.raises(ValueError):
        bl.BaselineModel().fit([test_msg])


def test_model_learns_tiny_set():
    train = [
        _msg(f"t{i}", text, cat)
        for i, (text, cat) in enumerate(
            [
                ("USPS parcel held, pay redelivery fee at usps-fix.top", "delivery_scam"),
                ("FedEx package delivery failed, pay customs fee now", "delivery_scam"),
                ("UPS parcel tracking: redelivery fee required today", "delivery_scam"),
                ("can you grab milk on the way home", "legit"),
                ("see you at dinner tonight, bring the salad", "legit"),
                ("running late, home by 7, grab milk please", "legit"),
            ]
        )
    ]
    model = bl.train_baseline(train)
    assert model.predict([_msg("q", "USPS parcel redelivery fee due", "delivery_scam")]) == ["delivery_scam"]


# --- metrics -----------------------------------------------------------------------


def test_false_positive_rate():
    gold = ["legit", "legit", "legit", "legit", "bank_impersonation"]
    pred = ["legit", "billing_scam", "legit", "legit", "legit"]
    assert bl.false_positive_rate(gold, pred) == 0.25


def test_score_macro_ignores_absent_categories():
    s = bl.score(["legit", "job_offer"], ["legit", "job_offer"], bl.taxonomy_ids())
    assert s["macro_f1"] == 1.0 and s["false_positive_rate"] == 0.0 and s["scam_recall"] == 1.0


def test_baseline_metrics_contract():
    test = [_msg("a", "x" * 25, "legit", "test_v1"), _msg("b", "y" * 25, "bank_impersonation", "test_v1")]
    m = bl.baseline_metrics(test, ["legit", "legit"])
    assert isinstance(m, BaselineMetrics) and m.n_test == 2
    assert m.false_positive_rate == 0.0
    assert [c.category for c in m.categories] == bl.taxonomy_ids()


# --- committed output (gate P1) ------------------------------------------------------


def test_committed_baseline_metrics_reproduce(split):
    """eval/baseline_metrics.json validates and a fresh fit on train gives the same numbers."""
    path = EVAL_DIR / "baseline_metrics.json"
    saved = BaselineMetrics.model_validate_json(path.read_text(encoding="utf-8"))
    assert saved.n_test == len(split.test)
    fresh = bl.baseline_metrics(split.test, bl.train_baseline(split.train).predict(split.test))
    assert fresh.macro_f1 == saved.macro_f1
    assert fresh.false_positive_rate == saved.false_positive_rate
    details = json.loads((EVAL_DIR / "baseline_details.json").read_text(encoding="utf-8"))
    assert details["split"]["test"] == len(split.test)
