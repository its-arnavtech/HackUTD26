"""Classifier inference for the pipeline. Filled in by L7.

Exposes `predict()` on redacted text and extracted features only.
"""

from __future__ import annotations

from app.contracts import ClassifierOutput, Features


def predict(text_redacted: str, features: Features) -> ClassifierOutput:
    """Category from T-Mobile's taxonomy, score, top 3 and the baseline score. (L7)"""
    raise NotImplementedError("L7: classifier predict")
