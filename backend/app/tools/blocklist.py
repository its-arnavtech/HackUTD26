"""Local blocklist of scam domains, built from A1's train split only (POC_MVP.md 7.6, DATA_SPEC.md 2).

Build it with `python -m scripts.build_blocklist`; `check_link` reads `data/blocklist.json`.
The split comes from `classifier.baseline.load_split()` (`data/generated/splits.json`),
so the same train set feeds the baseline, L7 and this list.
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
BUILT_FROM = "data/generated/splits.json (train)"

# Reserved example domains (RFC 2606) and free-mail providers: generated messages use
# them as placeholders or in email addresses, and blocking them would flag legit mail.
NEVER_BLOCK = frozenset(
    {"example.com", "example.net", "example.org", "email.com", "gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com", "aol.com"}
)


def train_messages() -> list[Message]:
    """A1's saved train split. Validation and test are never read here."""
    from app.classifier.baseline import load_split  # scikit-learn; keep it out of check_link's import

    return load_split().train


def build_domains(messages: Iterable[Message]) -> list[str]:
    """Domains seen in scam-labeled messages, minus official brand domains, shorteners,
    reserved and free-mail domains, and anything seen in a legit message."""
    official = {d for brand in load_brands() for d in brand.official_domains}
    scam: set[str] = set()
    legit: set[str] = set()
    for message in messages:
        if message.is_scam is None:
            continue
        (scam if message.is_scam else legit).update(domains_in_text(message.text))
    return sorted(scam - legit - official - SHORTENERS - NEVER_BLOCK)


def build_blocklist(messages: Iterable[Message] | None = None) -> dict[str, Any]:
    """Build from A1's train split; `messages` is for tests."""
    messages = list(train_messages() if messages is None else messages)
    return {
        "built_from": BUILT_FROM,
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
