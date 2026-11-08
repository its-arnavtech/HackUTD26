"""Dataset loader, stratified split and our baseline (A1, gate P1).

Reads our generated set (`data/generated/`, made by A21) into
`contracts.Message`. The split is 70/15/15 train/validation/test:

- train + validation come from the `train_v1` prompt set, split about 82/18
  stratified by category with a fixed seed (70/15 of the whole);
- test is the separate `test_v1` prompt set plus the hand-written messages.

The split's message ids are saved to `data/generated/splits.json` so every
later step (L7, A12, A13) uses the same one.

The baseline is keyword rules plus TF-IDF and logistic regression: the rule
hits are extra features next to TF-IDF word n-grams, fed to one multinomial
logistic regression with default settings (no tuning). The keyword lists were
written from general smishing knowledge, never from test messages.

The test split is never used for training, tuning, blocklists, campaign seeds
or prompts.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy.sparse import csr_matrix, hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import precision_recall_fscore_support
from sklearn.model_selection import train_test_split

from app.config import DATA_DIR
from app.contracts import BaselineCategoryMetrics, BaselineMetrics, Message, MessageSource

GENERATED_DIR = DATA_DIR / "generated"
SPLITS_PATH = GENERATED_DIR / "splits.json"
TAXONOMY_PATH = DATA_DIR / "taxonomy.json"
SPLIT_SEED = 42
TRAIN_PROMPT_SET = "train_v1"
TEST_PROMPT_SETS = ("test_v1", "handwritten")
# 70/15/15 overall; train_v1 is 85% of the data, so validation is 15/85 of it.
VAL_FRACTION_OF_POOL = 15 / 85
LEGIT = "legit"


@dataclass
class Split:
    train: list[Message]
    val: list[Message]
    test: list[Message]

    def ids(self) -> dict[str, list[str]]:
        return {name: [m.message_id for m in getattr(self, name)] for name in ("train", "val", "test")}


# ---------------------------------------------------------------------------
# Loading and splitting
# ---------------------------------------------------------------------------


def _read_jsonl(path: Path) -> list[Message]:
    if not path.exists():
        return []
    return [Message.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_messages(generated_dir: Path = GENERATED_DIR) -> list[Message]:
    """Load our generated set plus the hand-written test messages as `Message` objects."""
    messages = _read_jsonl(generated_dir / "messages.jsonl") + _read_jsonl(generated_dir / "handwritten.jsonl")
    if not messages:
        raise FileNotFoundError(f"No messages in {generated_dir}. Run `python -m scripts.generate_dataset --offline` (A21).")
    ids = [m.message_id for m in messages]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate message_id in data/generated/")
    return messages


def stratified_split(messages: list[Message], seed: int = SPLIT_SEED) -> Split:
    """70/15/15: train and validation stratified by category from `train_v1`;
    test is every `test_v1` and hand-written message (a separate prompt set)."""
    pool = sorted((m for m in messages if m.prompt_set == TRAIN_PROMPT_SET), key=lambda m: m.message_id)
    test = sorted((m for m in messages if m.prompt_set in TEST_PROMPT_SETS), key=lambda m: m.message_id)
    unknown = {m.prompt_set for m in messages} - {TRAIN_PROMPT_SET, *TEST_PROMPT_SETS}
    if unknown:
        raise ValueError(f"unknown prompt_set(s): {sorted(map(str, unknown))}")
    train, val = train_test_split(
        pool,
        test_size=VAL_FRACTION_OF_POOL,
        random_state=seed,
        stratify=[m.category for m in pool],
    )
    return Split(train=list(train), val=list(val), test=test)


def save_split(split: Split, path: Path = SPLITS_PATH) -> None:
    payload = {"seed": SPLIT_SEED, "rule": "train/val stratified from train_v1; test = test_v1 + handwritten", **split.ids()}
    path.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")


def load_split(messages: list[Message] | None = None, path: Path = SPLITS_PATH) -> Split:
    """The saved split, so every consumer scores on exactly the same test set."""
    messages = messages if messages is not None else load_messages()
    by_id = {m.message_id: m for m in messages}
    saved = json.loads(path.read_text(encoding="utf-8"))
    return Split(**{name: [by_id[i] for i in saved[name]] for name in ("train", "val", "test")})


# ---------------------------------------------------------------------------
# Keyword rules
# ---------------------------------------------------------------------------

# Written from general smishing knowledge, not from any message in the data.
KEYWORD_RULES: dict[str, str] = {
    # cues per category
    "bank": r"\b(bank|card|debit|credit|checking|savings|zelle|wire|fraud (alert|dept|team)|account (locked|suspended|frozen|restricted))\b",
    "bill": r"\b(bill|billing|past due|overdue|autopay|payment (failed|declined)|service (will be )?(suspended|interrupted|disconnected)|shut ?off|disconnect)\b",
    "delivery": r"\b(package|parcel|shipment|deliver(y|ed)?|redeliver(y)?|tracking|usps|ups|fedex|dhl|customs)\b",
    "account": r"\b(sign[- ]?in|log[- ]?in|password|sim (swap|change)|esim|apple id|verify (your )?(identity|account)|account (will be )?(deleted|disabled|deactivated))\b",
    "toll_gov": r"\b(toll|e-?zpass|sunpass|txtag|fastrak|irs|tax|dmv|license|registration|court|warrant|citation|fine)\b",
    "prize": r"\b(won|winner|giveaway|prize|reward(s)?|gift ?card|points|refund|rebate|survey|congratulations|congrats)\b",
    "job": r"\b(job|hiring|recruit(er|ing)?|position|remote|part[- ]time|daily pay|per day|/day|earn|salary|whatsapp|telegram|crypto|invest(ment)?)\b",
    "personal": r"\b(wrong number|new number|mom|dad|grandma|is this|sorry to bother|lol|hey|hi there)\b",
    # generic red flags
    "url": r"https?://|www\.|\b[\w-]+\.(com|net|org|co|info|xyz|top|vip|io|link|app|site|online|help)\b",
    "urgency": r"\b(urgent|immediately|now|today|within \d+|final notice|act now|expires?|last chance|asap|24 ?hrs?|hours?)\b",
    "threat": r"\b(suspend(ed|sion)?|locked|frozen|closed|terminated|penalty|late fee|legal action|arrest|returned to sender)\b",
    "code_request": r"\b(reply|send|text|share) (us |me )?(with )?(the |your )?(\d-digit )?(code|pin|otp|verification code)\b",
    "do_not_share": r"\b(do not|don'?t|never) (share|give)|we (will )?never (ask|call|text)",
    "money": r"\$\s?\d",
    "reply_stop": r"\breply stop\b|\bstop to (opt out|unsubscribe|cancel|end)\b",
}
_COMPILED = {name: re.compile(p, re.I) for name, p in KEYWORD_RULES.items()}


def keyword_features(texts: list[str]) -> csr_matrix:
    """One binary column per rule."""
    rows = [[1.0 if rx.search(t) else 0.0 for rx in _COMPILED.values()] for t in texts]
    return csr_matrix(np.asarray(rows, dtype=np.float64))


# ---------------------------------------------------------------------------
# Baseline model
# ---------------------------------------------------------------------------


@dataclass
class BaselineModel:
    """Keyword-rule features + TF-IDF word 1-2 grams -> multinomial logistic regression."""

    vectorizer: TfidfVectorizer = field(
        default_factory=lambda: TfidfVectorizer(lowercase=True, ngram_range=(1, 2), min_df=2, sublinear_tf=True)
    )
    clf: LogisticRegression = field(default_factory=lambda: LogisticRegression(max_iter=2000))

    def _features(self, texts: list[str], fit: bool = False) -> csr_matrix:
        tfidf = self.vectorizer.fit_transform(texts) if fit else self.vectorizer.transform(texts)
        return hstack([tfidf, keyword_features(texts)]).tocsr()

    def fit(self, messages: list[Message]) -> "BaselineModel":
        if any(m.prompt_set in TEST_PROMPT_SETS for m in messages):
            raise ValueError("the baseline must never be fit on test-split messages")
        self.clf.fit(self._features([m.text for m in messages], fit=True), [m.category for m in messages])
        return self

    def predict(self, messages: list[Message]) -> list[str]:
        return list(self.clf.predict(self._features([m.text for m in messages])))


def train_baseline(train: list[Message]) -> BaselineModel:
    return BaselineModel().fit(train)


def baseline_predict(messages: list[Message], model: BaselineModel | None = None) -> list[str]:
    """Baseline predictions. Without a model, fits one on the saved train split."""
    if model is None:
        model = train_baseline(load_split().train)
    return model.predict(messages)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def taxonomy_ids(path: Path = TAXONOMY_PATH) -> list[str]:
    return [c["id"] for c in json.loads(path.read_text(encoding="utf-8"))["categories"]]


def false_positive_rate(gold: list[str], pred: list[str]) -> float:
    """Share of legitimate messages flagged as any scam category."""
    legit = [p for g, p in zip(gold, pred) if g == LEGIT]
    return sum(1 for p in legit if p != LEGIT) / len(legit) if legit else 0.0


def score(gold: list[str], pred: list[str], labels: list[str]) -> dict:
    p, r, f, s = precision_recall_fscore_support(gold, pred, labels=labels, zero_division=0)
    per_cat = [
        {"category": c, "support": int(s[i]), "precision": float(p[i]), "recall": float(r[i]), "f1": float(f[i])}
        for i, c in enumerate(labels)
    ]
    present = [row for row in per_cat if row["support"] > 0]
    scam_gold = [g != LEGIT for g in gold]
    scam_pred = [x != LEGIT for x in pred]
    tp = sum(1 for g, x in zip(scam_gold, scam_pred) if g and x)
    return {
        "n": len(gold),
        "categories": per_cat,
        "macro_f1": float(np.mean([row["f1"] for row in present])) if present else 0.0,
        "accuracy": float(np.mean([g == x for g, x in zip(gold, pred)])) if gold else 0.0,
        "false_positive_rate": false_positive_rate(gold, pred),
        "scam_recall": tp / sum(scam_gold) if any(scam_gold) else 0.0,
        "scam_precision": tp / sum(scam_pred) if any(scam_pred) else 0.0,
    }


def baseline_metrics(test: list[Message], predictions: list[str] | None = None) -> BaselineMetrics:
    """Per-category precision, recall, F1, macro F1 and the false positive rate on the test split."""
    if predictions is None:
        predictions = baseline_predict(test)
    gold = [m.category for m in test]
    s = score(gold, predictions, taxonomy_ids())
    return BaselineMetrics(
        generated_at=datetime.now(timezone.utc),
        n_test=len(test),
        categories=[BaselineCategoryMetrics(**{k: round(v, 4) if isinstance(v, float) else v for k, v in row.items()}) for row in s["categories"]],
        macro_f1=round(s["macro_f1"], 4),
        false_positive_rate=round(s["false_positive_rate"], 4),
    )


def confusion(gold: list[str], pred: list[str]) -> dict[str, dict[str, int]]:
    """gold -> {predicted: count}, only non-zero cells."""
    out: dict[str, Counter[str]] = {}
    for g, p in zip(gold, pred):
        out.setdefault(g, Counter())[p] += 1
    return {g: dict(sorted(c.items())) for g, c in sorted(out.items())}


def is_handwritten(m: Message) -> bool:
    return m.source == MessageSource.handwritten
