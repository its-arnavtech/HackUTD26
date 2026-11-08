"""L7 follow-up: public binary supervision without invented category labels."""
from __future__ import annotations

import hashlib
import json
import pickle
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import sklearn
from sklearn.linear_model import LogisticRegression

from app.classifier.baseline import LEGIT, SPLITS_PATH, score, taxonomy_ids, train_baseline
from app.classifier.public_data import SPLITS, guard_public
from app.classifier.train import Config, Encoder, adjusted_probabilities, guard_partitions, matrix
from app.config import DATA_DIR
from app.contracts import Features, Message

ALGORITHM = "l7-public-binary-v2"
MODEL_PATH = DATA_DIR / "models" / "classifier-v2.pkl"
BIASES = (0.25, 0.5, 0.75, 1.0, 1.5, 2.0)


def binary_scores(rows: list[Message], predictions: list[str]) -> dict:
    if len(rows) != len(predictions):
        raise ValueError("Binary prediction length mismatch")
    gold = ["scam" if row.is_scam else LEGIT for row in rows]
    pred = ["scam" if value != LEGIT else LEGIT for value in predictions]
    report = score(gold, pred, [LEGIT, "scam"])
    return {key: report[key] for key in ("n", "macro_f1", "false_positive_rate", "scam_recall", "scam_precision")}


def data_digest(*partitions: list[Message]) -> str:
    data = [[(row.message_id, row.text, row.category, row.is_scam) for row in rows] for rows in partitions]
    return hashlib.sha256(json.dumps(data, ensure_ascii=True).encode()).hexdigest()


@dataclass
class HybridModel:
    encoder: Encoder
    binary: LogisticRegression
    category_head: LogisticRegression
    config: Config
    legit_bias: float
    baseline: object
    report: dict

    @property
    def classes_(self) -> np.ndarray:
        return np.append(self.category_head.classes_, LEGIT)

    def _probabilities(self, values) -> np.ndarray:
        p_scam = self.binary.predict_proba(values)[:, list(self.binary.classes_).index(True)]
        categories = self.category_head.predict_proba(values)
        return np.column_stack([categories*p_scam[:, None], 1-p_scam])

    def predict_proba_texts(self, texts: list[str], features: list[Features] | None = None) -> np.ndarray:
        if not texts:
            return np.empty((0, len(self.classes_)))
        values = matrix(self.encoder.transform(texts, features=features), self.config)
        return adjusted_probabilities(self._probabilities(values), self.classes_, self.legit_bias)

    def predict(self, messages: list[Message]) -> list[str]:
        if not messages:
            return []
        values = self.predict_proba_texts([row.text for row in messages])
        return [str(self.classes_[index]) for index in values.argmax(axis=1)]


def train_hybrid(synthetic_train: list[Message], synthetic_val: list[Message], public_train: list[Message], public_val: list[Message],
                 *, synthetic_splits: Path = SPLITS_PATH, public_splits: Path = SPLITS,
                 configs: tuple[Config, ...] | None = None) -> HybridModel:
    syn_digest = guard_partitions(synthetic_train, synthetic_val, synthetic_splits)
    public_digest = guard_public(public_train, public_val, splits_path=public_splits)
    encoder = Encoder()
    fitting = synthetic_train+public_train
    parts = encoder.transform([row.text for row in fitting], fit=True)
    syn_val_parts = encoder.transform([row.text for row in synthetic_val])
    pub_val_parts = encoder.transform([row.text for row in public_val])
    scam_indices = [index for index, row in enumerate(synthetic_train) if row.is_scam]
    category_labels = [synthetic_train[index].category for index in scam_indices]
    if len(set(category_labels)) < 2:
        raise ValueError("Category head needs multiple synthetic scam categories")
    baseline = train_baseline(synthetic_train)
    syn_gold = [row.category for row in synthetic_val]
    baseline_val = score(syn_gold, baseline.predict(synthetic_val), taxonomy_ids())
    limits = {"synthetic": min(0.10, baseline_val["false_positive_rate"]), "public": 0.03}
    configs = configs if configs is not None else tuple(Config(c, char_weight, feature_weight)
        for c in (0.5, 2.0, 8.0) for char_weight in (0.5, 1.0) for feature_weight in (0.25, 1.0))
    trials, candidates = [], []
    for config in configs:
        if any(not np.isfinite(value) or value <= 0 for value in (config.c, config.char_weight, config.feature_weight)):
            raise ValueError("Classifier configuration must be finite/positive")
        values = matrix(parts, config)
        binary = LogisticRegression(C=config.c, max_iter=1500, random_state=42)
        binary.fit(values, [bool(row.is_scam) for row in fitting])
        category_head = LogisticRegression(C=config.c, max_iter=1500, random_state=42)
        # Public spam never receives a fabricated synthetic scam category.
        category_head.fit(values[scam_indices], category_labels)
        model = HybridModel(encoder, binary, category_head, config, 1.0, baseline, {})
        syn_raw = model._probabilities(matrix(syn_val_parts, config))
        pub_raw = model._probabilities(matrix(pub_val_parts, config))
        for bias in BIASES:
            syn_pred = [str(model.classes_[index]) for index in adjusted_probabilities(syn_raw, model.classes_, bias).argmax(axis=1)]
            pub_pred = [str(model.classes_[index]) for index in adjusted_probabilities(pub_raw, model.classes_, bias).argmax(axis=1)]
            syn = score(syn_gold, syn_pred, taxonomy_ids())
            pub = binary_scores(public_val, pub_pred)
            objective = (syn["macro_f1"]+pub["macro_f1"])/2
            excess = max(0, syn["false_positive_rate"]-limits["synthetic"])+max(0, pub["false_positive_rate"]-limits["public"])
            trial = {"c": config.c, "char_weight": config.char_weight, "feature_weight": config.feature_weight,
                     "legit_bias": bias, "synthetic_macro_f1": syn["macro_f1"], "synthetic_fpr": syn["false_positive_rate"],
                     "public_binary_macro_f1": pub["macro_f1"], "public_fpr": pub["false_positive_rate"], "objective": objective,
                     "constraints_met": excess == 0}
            trials.append(trial)
            candidates.append(((excess == 0, -excess, objective, -config.c, bias), model, bias, trial))
    if not candidates:
        raise ValueError("No classifier candidates")
    _, selected_model, bias, selected = max(candidates, key=lambda value: value[0])
    selected_model.legit_bias = bias
    selected_model.report = {"algorithm": ALGORITHM, "sklearn_version": sklearn.__version__, "numpy_version": np.__version__,
        "synthetic_split_digest": syn_digest, "public_split_digest": public_digest,
        "input_digest": data_digest(synthetic_train, synthetic_val, public_train, public_val),
        "counts": {"synthetic_train": len(synthetic_train), "synthetic_val": len(synthetic_val),
                   "public_fit": len(public_train), "public_val": len(public_val), "binary_fit": len(fitting), "category_fit": len(scam_indices)},
        "selected": selected, "validation_fpr_limits": limits, "trials": trials,
        "selection": "mean synthetic category/public binary validation macro F1 under separate FPR limits; no holdout access",
        "labels": "binary head uses synthetic/public scam or legitimate; category head uses synthetic scams only",
        "probabilities": "hierarchical relative scores with validation-selected legitimate bias; not calibrated risk"}
    return selected_model


def save_hybrid(model: HybridModel, path: Path = MODEL_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix+".tmp")
    with temporary.open("wb") as stream:
        pickle.dump({"algorithm": ALGORITHM, "sklearn_version": sklearn.__version__, "model": model}, stream, protocol=pickle.HIGHEST_PROTOCOL)
    temporary.replace(path)


def load_hybrid(path: Path = MODEL_PATH) -> HybridModel:
    # Trusted locally generated artifacts only, never uploaded/downloaded pickles.
    with path.open("rb") as stream:
        payload = pickle.load(stream)
    if payload.get("algorithm") != ALGORITHM or payload.get("sklearn_version") != sklearn.__version__ or not isinstance(payload.get("model"), HybridModel):
        raise ValueError("Hybrid artifact version mismatch; retrain locally")
    return payload["model"]
