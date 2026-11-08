"""Improved classifier training. Filled in by L7.

TF-IDF word and character n-grams plus extracted features into logistic
regression or gradient-boosted trees. Tune on the validation split only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.contracts import Message


def train(train_set: list[Message], val_set: list[Message]) -> Any:
    """Fit the improved model on train, tune on validation. Never touches test. (L7)"""
    raise NotImplementedError("L7: train classifier")


def save_model(model: Any, path: Path) -> None:
    """Persist the trained model for `predict.py`. (L7)"""
    raise NotImplementedError("L7: save model")
