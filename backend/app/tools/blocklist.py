"""Local blocklist of scam domains, built from the train split only (POC_MVP.md 7.6, DATA_SPEC.md 2).

Build it with `python -m scripts.build_blocklist`; `check_link` reads `data/blocklist.json`.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import DATA_DIR
from app.contracts import Message
from app.tools.brands import load_brands
from app.tools.domains import SHORTENERS, domains_in_text

BLOCKLIST_PATH = DATA_DIR / "blocklist.json"

# TODO(A1): point this at A1's saved train split once it lands, then rebuild the blocklist from it.
A1_TRAIN_SPLIT = DATA_DIR / "splits" / "train.jsonl"
PROVISIONAL_TRAIN_SPLIT = DATA_DIR / "provisional" / "train.jsonl"


class NotTrainSplitError(ValueError):
    """Raised when asked to build the blocklist from anything but a train split."""


def default_train_split() -> Path:
    return A1_TRAIN_SPLIT if A1_TRAIN_SPLIT.exists() else PROVISIONAL_TRAIN_SPLIT


def read_messages(path: Path) -> list[Message]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [Message.model_validate_json(line) for line in lines if line.strip()]


def _check_train_only(path: Path) -> None:
    name = path.name.lower()
    if "train" not in name or any(word in name for word in ("test", "val")):
        raise NotTrainSplitError(f"{path.name}: the blocklist is built from the train split only")


def build_domains(messages: Iterable[Message]) -> list[str]:
    """Domains seen in scam-labeled messages, minus official brand domains, shorteners and anything seen in a legit message."""
    official = {d for brand in load_brands() for d in brand.official_domains}
    scam: set[str] = set()
    legit: set[str] = set()
    for message in messages:
        if message.is_scam is None:
            continue
        (scam if message.is_scam else legit).update(domains_in_text(message.text))
    return sorted(scam - legit - official - SHORTENERS)


def build_blocklist(train_path: Path) -> dict[str, Any]:
    _check_train_only(train_path)
    messages = read_messages(train_path)
    try:
        built_from = train_path.resolve().relative_to(DATA_DIR.parent).as_posix()
    except ValueError:
        built_from = train_path.name
    return {
        "built_from": built_from,
        "provisional": train_path.resolve() != A1_TRAIN_SPLIT.resolve(),
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "messages_read": len(messages),
        "domains": build_domains(messages),
    }


def write_blocklist(blocklist: dict[str, Any], path: Path = BLOCKLIST_PATH) -> None:
    path.write_text(json.dumps(blocklist, indent=2) + "\n", encoding="utf-8")


@lru_cache(maxsize=4)
def load_blocklist(path: Path = BLOCKLIST_PATH) -> frozenset[str]:
    if not path.exists():
        return frozenset()
    return frozenset(json.loads(path.read_text(encoding="utf-8"))["domains"])
