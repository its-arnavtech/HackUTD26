from __future__ import annotations

import json

import pytest

from app.config import DATA_DIR
from app.contracts import Message
from app.tools.blocklist import (
    BLOCKLIST_PATH,
    PROVISIONAL_TRAIN_SPLIT,
    NotTrainSplitError,
    build_blocklist,
    build_domains,
    load_blocklist,
)
from app.tools.domains import domains_in_text


def msg(text: str, is_scam: bool | None) -> Message:
    return Message(message_id="m", text=text, sender="+15550100000", is_scam=is_scam)


def test_domains_in_text():
    text = "Pay at https://Pay.Example-Bills.co.uk/x?id=1 or www.other.com. Also tmo-billing-update.com, not $1.99"
    assert domains_in_text(text) == ["example-bills.co.uk", "other.com", "tmo-billing-update.com"]


def test_scam_domains_only_minus_legit_official_and_shorteners():
    domains = build_domains(
        [
            msg("Verify at https://capone-account-help.net/now", True),
            msg("Pay here https://bit.ly/abc or capitalone.com", True),
            msg("Shared-domain.com shows up in both", True),
            msg("Your order: shared-domain.com/track", False),
            msg("unlabeled at unlabeled-domain.com", None),
        ]
    )
    assert domains == ["capone-account-help.net"]


@pytest.mark.parametrize("name", ["test.jsonl", "val.jsonl", "train_test.jsonl", "messages.jsonl"])
def test_refuses_anything_but_train(tmp_path, name):
    path = tmp_path / name
    path.write_text("", encoding="utf-8")
    with pytest.raises(NotTrainSplitError):
        build_blocklist(path)


def test_committed_blocklist_matches_provisional_train_split():
    rebuilt = build_blocklist(PROVISIONAL_TRAIN_SPLIT)
    committed = json.loads(BLOCKLIST_PATH.read_text(encoding="utf-8"))
    assert committed["domains"] == rebuilt["domains"]
    assert committed["built_from"] == "data/provisional/train.jsonl"
    assert committed["provisional"] is True


def test_demo_scenario_domains_are_not_in_the_provisional_blocklist():
    blocked = load_blocklist()
    for path in sorted((DATA_DIR / "scenarios").glob("scenario_*.json")):
        text = json.loads(path.read_text(encoding="utf-8"))["message"]["text"]
        for domain in domains_in_text(text):
            assert domain not in blocked, f"{domain} from {path.name}"


def test_missing_blocklist_is_empty(tmp_path):
    assert load_blocklist(tmp_path / "none.json") == frozenset()
