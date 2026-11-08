"""Dataset loader, stratified split and our baseline. Filled in by A1 (gate P1).

Reads our generated set (`data/generated/`, made by A21) into
`contracts.Message`. Split is 70/15/15 train/validation/test, stratified by
category, with a fixed seed; the test split comes from the separate prompt set
plus the hand-written messages. The baseline is keyword rules plus TF-IDF and
logistic regression. The test split is never used for training, tuning,
blocklists, campaign seeds or prompts.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.config import DATA_DIR
from app.contracts import BaselineMetrics, Message

GENERATED_DIR = DATA_DIR / "generated"
SPLIT_SEED = 42


@dataclass
class Split:
    train: list[Message]
    val: list[Message]
    test: list[Message]


def load_messages(generated_dir: Path = GENERATED_DIR) -> list[Message]:
    """Load our generated message set as `Message` objects. (A1)"""
    raise NotImplementedError("A1: dataset loader")


def stratified_split(messages: list[Message], seed: int = SPLIT_SEED) -> Split:
    """70/15/15 split stratified by category; test from the separate prompt set. (A1)"""
    raise NotImplementedError("A1: stratified split")


def baseline_predict(messages: list[Message]) -> list[str]:
    """Baseline predictions (keyword rules plus TF-IDF and logistic regression). (A1)"""
    raise NotImplementedError("A1: baseline predictions")


def baseline_metrics(test: list[Message]) -> BaselineMetrics:
    """Per-category precision, recall, F1 and the false positive rate on the test split. (A1)"""
    raise NotImplementedError("A1: baseline metrics")
