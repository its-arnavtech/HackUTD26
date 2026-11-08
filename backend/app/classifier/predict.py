"""L7 pipeline inference on redacted text and A9 Features, entirely local."""
from __future__ import annotations

from functools import lru_cache

import numpy as np

from app.classifier.train import MODEL_PATH, ImprovedModel, load_model
from app.contracts import ClassifierOutput, Features


@lru_cache(maxsize=1)
def get_model() -> ImprovedModel:
    """Load once per process. After retraining, restart or get_model.cache_clear()."""
    if not MODEL_PATH.exists():
        raise FileNotFoundError("Train L7 first: python -m scripts.train_classifier")
    return load_model(MODEL_PATH)


def predict(text_redacted: str, features: Features, *, model: ImprovedModel | None = None) -> ClassifierOutput:
    """Category, relative score and top 3; no raw text, URLs or sender needed."""
    active = model if model is not None else get_model()
    values = active.predict_proba_texts([text_redacted], [features])[0]
    indices = np.argsort(-values, kind="stable")[:3]
    classes = active.classifier.classes_
    chosen = str(classes[indices[0]])
    baseline_values = active.baseline.clf.predict_proba(active.baseline._features([text_redacted]))[0]
    baseline_classes = list(active.baseline.clf.classes_)
    return ClassifierOutput(category=chosen, score=float(values[indices[0]]),
                            top3=[(str(classes[index]), float(values[index])) for index in indices],
                            baseline_score=float(baseline_values[baseline_classes.index(chosen)]))
