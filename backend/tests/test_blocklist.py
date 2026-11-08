from __future__ import annotations

import json

from app.config import DATA_DIR
from app.contracts import Message
from app.classifier import baseline
from app.tools import blocklist as blocklist_module
from app.tools.blocklist import BLOCKLIST_PATH, build_blocklist, build_domains, load_blocklist
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
            msg("Write to agent@email.com or see example.com", True),
        ]
    )
    assert domains == ["capone-account-help.net"]


def test_reads_a1_train_split_only(monkeypatch):
    split = baseline.Split(
        train=[msg("Verify at https://train-scam.com/x", True)],
        val=[msg("Verify at https://val-scam.com/x", True)],
        test=[msg("Verify at https://test-scam.com/x", True)],
    )
    monkeypatch.setattr(baseline, "load_split", lambda *a, **k: split)
    built = build_blocklist()
    assert built["domains"] == ["train-scam.com"]
    assert built["messages_read"] == 1


def test_train_messages_are_a1s_saved_train_ids():
    saved = json.loads(baseline.SPLITS_PATH.read_text(encoding="utf-8"))
    assert [m.message_id for m in blocklist_module.train_messages()] == saved["train"]


def test_committed_blocklist_matches_a1_train_split():
    rebuilt = build_blocklist()
    committed = json.loads(BLOCKLIST_PATH.read_text(encoding="utf-8"))
    assert committed["domains"] == rebuilt["domains"]
    assert committed["built_from"] == "data/generated/splits.json (train)"
    assert committed["messages_read"] == len(json.loads(baseline.SPLITS_PATH.read_text(encoding="utf-8"))["train"])


def test_demo_scenario_domains_are_not_in_the_blocklist():
    blocked = load_blocklist()
    for path in sorted((DATA_DIR / "scenarios").glob("scenario_*.json")):
        text = json.loads(path.read_text(encoding="utf-8"))["message"]["text"]
        for domain in domains_in_text(text):
            assert domain not in blocked, f"{domain} from {path.name}"


def test_missing_blocklist_is_empty(tmp_path):
    assert load_blocklist(tmp_path / "none.json") == frozenset()
