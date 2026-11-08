"""L7: train-only TF-IDF + A9 features; validation-only model selection.

No sender, source, ID, category, or other ground-truth field enters features.
The factory accepts A13's text condition as-is, including its raw-cost control.
Production training/inference use redacted text. Nothing calls external services.
"""
from __future__ import annotations

import hashlib
import json
import math
import pickle
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import sklearn
from scipy.sparse import csr_matrix, hstack
from sklearn.feature_extraction import DictVectorizer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

from app.classifier.baseline import (LEGIT, SPLITS_PATH, keyword_features, score,
                                     taxonomy_ids, train_baseline)
from app.config import DATA_DIR
from app.contracts import Features, Message, MessageSource
from app.features.extract import extract_features

ALGORITHM = "l7-tfidf-a9-v1"
MODEL_PATH = DATA_DIR / "models" / "classifier-v1.pkl"
_PHONE = re.compile(r"<PHONE_HASH_[^>]+>")
_URL = re.compile(r"<URL_\d+>")


def normalize(text: str) -> str:
    """Make private salt/URL occurrence numbers non-predictive."""
    return _URL.sub("<URL>", _PHONE.sub("<PHONE_HASH>", text))


def feature_dict(text: str, features: Features | None = None) -> dict:
    features = features if features is not None else extract_features(text)
    data = {"action": features.requested_action or "none", "threat": features.threat or "none",
            "deadline_present": float(features.urgency_deadline is not None),
            "url_count": float(min(5, len(re.findall(r"<URL(?:_\d+)?>", text)))),
            "amount_present": float(features.money_amount_claimed is not None)}
    amount = features.money_amount_claimed
    data["amount_log"] = math.log1p(min(abs(amount), 1e6)) / 14 if amount is not None and math.isfinite(amount) else 0.0
    for value in features.asks_for:
        data["asks=" + value] = 1.0
    return data


@dataclass(frozen=True)
class Config:
    c: float = 2.0
    char_weight: float = 1.0
    feature_weight: float = 0.25


class Encoder:
    def __init__(self):
        self.word = TfidfVectorizer(ngram_range=(1, 2), min_df=1, sublinear_tf=True, max_features=30000)
        self.char = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=2, sublinear_tf=True, max_features=50000)
        self.structured = DictVectorizer()

    def transform(self, texts: list[str], *, fit: bool = False, features: list[Features] | None = None):
        texts = [normalize(text) for text in texts]
        dictionaries = [feature_dict(text, features[i] if features is not None else None) for i, text in enumerate(texts)]
        word = self.word.fit_transform(texts) if fit else self.word.transform(texts)
        char = self.char.fit_transform(texts) if fit else self.char.transform(texts)
        structured = self.structured.fit_transform(dictionaries) if fit else self.structured.transform(dictionaries)
        # Baseline cues are fixed general rules, never learned from validation/test.
        return word, char, hstack([structured, keyword_features(texts)]).tocsr()


def matrix(parts, config: Config) -> csr_matrix:
    return hstack([parts[0], parts[1] * config.char_weight, parts[2] * config.feature_weight]).tocsr()


def adjusted_probabilities(probabilities: np.ndarray, classes, legit_bias: float) -> np.ndarray:
    values = probabilities.copy()
    values[:, list(classes).index(LEGIT)] *= legit_bias
    return values / values.sum(axis=1, keepdims=True)


@dataclass
class ImprovedModel:
    encoder: Encoder
    classifier: LogisticRegression
    config: Config
    legit_bias: float
    report: dict
    baseline: object

    @property
    def classes_(self) -> np.ndarray:
        return self.classifier.classes_

    def predict_proba_texts(self, texts: list[str], features: list[Features] | None = None) -> np.ndarray:
        if not texts:
            return np.empty((0, len(self.classifier.classes_)))
        parts = self.encoder.transform(texts, features=features)
        return adjusted_probabilities(self.classifier.predict_proba(matrix(parts, self.config)),
                                      self.classifier.classes_, self.legit_bias)

    def predict(self, messages: list[Message]) -> list[str]:
        """A13 batch interface: only text is read; labels and metadata are ignored."""
        if not messages:
            return []
        probabilities = self.predict_proba_texts([message.text for message in messages])
        return [str(self.classifier.classes_[index]) for index in probabilities.argmax(axis=1)]


def input_digest(train_set: list[Message], val_set: list[Message]) -> str:
    """Aggregate content hash ties a local artifact to its exact text condition."""
    rows = [(name, row.message_id, row.category, row.text) for name, data in (("train", train_set), ("val", val_set)) for row in data]
    return hashlib.sha256(json.dumps(rows, ensure_ascii=True).encode()).hexdigest()


def guard_partitions(train_set: list[Message], val_set: list[Message], splits_path: Path) -> str:
    saved = json.loads(splits_path.read_text(encoding="utf-8"))
    partitions = [set(saved[name]) for name in ("train", "val", "test")]
    if any(len(saved[name]) != len(set(saved[name])) for name in ("train", "val", "test")) or any(partitions[i] & partitions[j] for i in range(3) for j in range(i)):
        raise ValueError("Saved splits must have unique, disjoint IDs")
    labels = set(taxonomy_ids())
    for name, rows in (("train", train_set), ("val", val_set)):
        ids = [row.message_id for row in rows]
        if not rows or len(ids) != len(set(ids)) or set(ids) != set(saved[name]):
            raise ValueError("Training and validation must match their saved split IDs exactly")
        if any(row.source != MessageSource.generated or row.prompt_set != "train_v1" or row.category not in labels
               or row.is_scam != (row.category != LEGIT) for row in rows):
            raise ValueError("Only labeled generated train_v1 observations may train or tune")
        if LEGIT not in {row.category for row in rows} or len({row.category for row in rows}) < 2:
            raise ValueError("Train/validation each need legitimate and scam observations")
    return hashlib.sha256(json.dumps({name: sorted(saved[name]) for name in ("train", "val")}, sort_keys=True).encode()).hexdigest()


def train(train_set: list[Message], val_set: list[Message], *, splits_path: Path = SPLITS_PATH,
          configs: tuple[Config, ...] | None = None) -> ImprovedModel:
    """All fits use train; vocabulary, IDF and dictionary never fit validation."""
    digest = guard_partitions(train_set, val_set, splits_path)
    encoder = Encoder()
    training = encoder.transform([row.text for row in train_set], fit=True)
    validation = encoder.transform([row.text for row in val_set])
    labels = taxonomy_ids()
    gold = [row.category for row in val_set]
    baseline = train_baseline(train_set)
    baseline_validation = score(gold, baseline.predict(val_set), labels)
    # An explicit FPR constraint before looking at any test/public result.
    fpr_limit = min(0.10, baseline_validation["false_positive_rate"])
    configs = configs if configs is not None else tuple(Config(c, char_weight, feature_weight)
        for c in (0.5, 2.0, 8.0) for char_weight in (0.5, 1.0) for feature_weight in (0.25, 1.0))
    trials, candidates = [], []
    for config in configs:
        if not all(math.isfinite(value) and value > 0 for value in (config.c, config.char_weight, config.feature_weight)):
            raise ValueError("Model weights and regularization must be finite and positive")
        classifier = LogisticRegression(C=config.c, max_iter=1500, random_state=42)
        classifier.fit(matrix(training, config), [row.category for row in train_set])
        raw = classifier.predict_proba(matrix(validation, config))
        for bias in (0.75, 1.0, 1.5, 2.0, 3.0):
            probabilities = adjusted_probabilities(raw, classifier.classes_, bias)
            predictions = [str(classifier.classes_[index]) for index in probabilities.argmax(axis=1)]
            metrics = score(gold, predictions, labels)
            trial = {"c": config.c, "char_weight": config.char_weight, "feature_weight": config.feature_weight,
                     "legit_bias": bias, "macro_f1": metrics["macro_f1"], "false_positive_rate": metrics["false_positive_rate"]}
            trials.append(trial)
            key = (metrics["false_positive_rate"] <= fpr_limit, metrics["macro_f1"], -metrics["false_positive_rate"], -config.c, bias)
            candidates.append((key, config, bias, classifier, trial))
    if not candidates:
        raise ValueError("No classifier candidates")
    _, config, bias, classifier, selected = max(candidates, key=lambda candidate: candidate[0])
    report = {"algorithm": ALGORITHM, "sklearn_version": sklearn.__version__, "split_digest": digest,
              "train_rows": len(train_set), "validation_rows": len(val_set), "input_digest": input_digest(train_set, val_set),
              "validation_fpr_limit": fpr_limit, "validation_constraint_met": selected["false_positive_rate"] <= fpr_limit,
              "baseline_validation": {key: baseline_validation[key] for key in ("macro_f1", "false_positive_rate")},
              "selected": selected, "trials": trials,
              "selection": "validation macro F1 under FPR constraint; ties lower FPR, stronger regularization, larger legit bias",
              "probabilities": "relative model scores after validation-selected legit bias; not calibrated risk"}
    return ImprovedModel(encoder, classifier, config, bias, report, baseline)


def make_model(train_set: list[Message], val_set: list[Message]) -> ImprovedModel:
    """A13 factory; receives only its supplied train/validation text condition."""
    return train(train_set, val_set)


def save_model(model: ImprovedModel, path: Path = MODEL_PATH) -> None:
    """Local trusted artifact only; aggregate report has no message text or IDs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as stream:
        pickle.dump({"algorithm": ALGORITHM, "sklearn_version": sklearn.__version__, "model": model}, stream,
                    protocol=pickle.HIGHEST_PROTOCOL)
    temporary.replace(path)


def load_model(path: Path = MODEL_PATH) -> ImprovedModel:
    # Only load artifacts generated locally by train_classifier; pickle is not
    # a format for user uploads or untrusted downloads.
    with path.open("rb") as stream:
        payload = pickle.load(stream)
    if payload.get("algorithm") != ALGORITHM or payload.get("sklearn_version") != sklearn.__version__ or not isinstance(payload.get("model"), ImprovedModel):
        raise ValueError("Classifier artifact version mismatch; retrain locally")
    return payload["model"]
