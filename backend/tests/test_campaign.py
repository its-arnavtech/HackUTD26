"""Synthetic campaign fixtures; split leakage, persistence and count invariants."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from app.contracts import MatchCampaignArgs, Message, MessageSource
from app.privacy import redact as privacy
from app.tools import campaign as c
from app.tools.campaign_store import CampaignStore, Fingerprint
from scripts import seed_campaigns as cli

NOW = datetime(2026, 11, 8, 16, 0, tzinfo=timezone.utc)
BILL = "T-Mobile: your bill is overdue. Pay $20 within 2 hours to avoid suspension: https://tmobile-bill.example/pay?customer=Mira"
BANK = "Capital One: your account will be locked in 2 hours. Verify now: https://capone-verify.example/private"


def message(key, text=BILL, *, category="billing_scam", time=None, scam=True, prompt="train_v1", source=MessageSource.generated):
    return Message(message_id=key, text=text, sender="2025550134", received_at=time or NOW-timedelta(hours=1),
                   category=category, is_scam=scam, prompt_set=prompt, source=source)


@pytest.fixture(autouse=True)
def salt(monkeypatch):
    monkeypatch.setattr(privacy, "get_settings", lambda: SimpleNamespace(PHONE_HASH_SALT=SecretStr("synthetic-campaign-salt")))


@pytest.fixture
def corpus(tmp_path):
    train = [message("t1", time=NOW-timedelta(hours=3)), message("t2", BILL.replace("$20", "$30"), time=NOW-timedelta(hours=2)),
             message("t3", BANK, category="bank_impersonation"),
             message("t4", "T-Mobile bill was paid.", category="legit", scam=False)]
    val = [message("v1", BILL.replace("$20", "$40")), message("v2", BANK, category="bank_impersonation"),
           message("v3", "Capital One: your statement is ready.", category="legit", scam=False)]
    split = tmp_path / "splits.json"
    split.write_text(json.dumps({"train": [m.message_id for m in train], "val": [m.message_id for m in val], "test": ["test-forbidden"]}))
    return train, val, split


@pytest.fixture
def seeded(corpus):
    train, val, split = corpus
    store = CampaignStore()
    report = c.calibrate_threshold(train, val, store=store, splits_path=split)
    assert c.seed_campaigns(train, store=store, splits_path=split) == 3
    yield store, report
    store.close()


def query(key="incoming", *, time=NOW):
    return c.message_input(message(key, time=time))


def test_calibration_uses_validation_and_never_inserts_it(corpus):
    train, val, split = corpus
    store = CampaignStore()
    try:
        report = c.calibrate_threshold(train, val, store=store, splits_path=split)
        assert report["threshold"] in c.THRESHOLDS and report["validation_rows"] == 3
        assert report["training_fingerprints"] == 3 and store.count() == 0
        assert report["f1"] == 1
        assert c.seed_campaigns(train, store=store, splits_path=split) == 3
        hashes = {member.fingerprint.event_hash for member in store.members()}
        assert not hashes.intersection(c._event_hash(m.message_id) for m in val)
    finally:
        store.close()


def test_seed_is_idempotent_and_excludes_legit(corpus, seeded):
    train, _, split = corpus
    store, _ = seeded
    assert c.seed_campaigns(train, store=store, splits_path=split) == 0
    assert store.count() == 3
    assert all(member.fingerprint.category != "legit" for member in store.members())


@pytest.mark.parametrize("partition", ["val", "test", "authored"])
def test_seed_rejects_leakage_before_any_text_processing(corpus, monkeypatch, partition):
    train, val, split = corpus
    bad = val[0] if partition == "val" else message("test-forbidden" if partition == "test" else "authored", prompt="test_v1", source=MessageSource.authored)
    store = CampaignStore()
    def forbidden(*args):
        raise AssertionError("forbidden message was processed")
    monkeypatch.setattr(c, "message_input", forbidden)
    try:
        with pytest.raises(ValueError, match="designated"):
            c.seed_campaigns([train[0], bad], store=store, splits_path=split)
        assert store.count() == 0
    finally:
        store.close()


def test_calibration_rejects_train_validation_swap(corpus):
    train, val, split = corpus
    with pytest.raises(ValueError, match="designated"):
        c.calibrate_threshold(val, train, store=CampaignStore(), splits_path=split)


def test_loader_does_not_validate_test_text_or_open_handwritten(corpus, tmp_path):
    train, val, split = corpus
    rows = [m.model_dump(mode="json") for m in train + val]
    rows.insert(1, {"message_id": "test-forbidden", "text": {"do_not_process": True}})
    (tmp_path / "messages.jsonl").write_text("\n".join(json.dumps(row) for row in rows))
    (tmp_path / "handwritten.jsonl").write_text("NOT JSON: must never open this file")
    loaded_train, loaded_val = c.load_training_validation(tmp_path, splits_path=split)
    assert [m.message_id for m in loaded_train] == [m.message_id for m in train]
    assert [m.message_id for m in loaded_val] == [m.message_id for m in val]


def test_overlapping_or_duplicate_split_ids_are_rejected(corpus):
    train, _, split = corpus
    data = json.loads(split.read_text()); data["val"].append(train[0].message_id); split.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="disjoint"):
        c.seed_campaigns(train, store=CampaignStore(), splits_path=split)


def test_fingerprints_normalize_private_fields_amounts_and_deadlines():
    first = c.message_input(message("first", "T-Mobile: Hi Mira Vale, call 2025550134. Pay $20 in 2 hours at https://tmobile-pay.example/a?person=Mira"))
    second = c.message_input(message("second", "T-Mobile: Hi Rhea Cove, call 2025550135. Pay $40 in 3 hours at https://tmobile-pay.example/b?person=Rhea"))
    left, right = c.fingerprint(first), c.fingerprint(second)
    assert left["template_hash"] == right["template_hash"]
    assert left["wording_simhash"] == right["wording_simhash"]
    rendered = json.dumps(left)
    assert all(private not in rendered for private in ("Mira", "Vale", "2025550134", "person=", "your bill", "https://"))
    assert "text" not in left and "sender" not in left


def test_sqlite_persists_fingerprints_only_and_survives_reopen(corpus, tmp_path):
    train, val, split = corpus
    path = tmp_path / "campaigns.sqlite3"
    store = CampaignStore(path)
    c.calibrate_threshold(train, val, store=store, splits_path=split)
    c.seed_campaigns(train, store=store, splits_path=split)
    dump = "\n".join(store._db.iterdump())
    assert all(private not in dump for private in ("Mira", "customer=", "/private", "2025550134", BILL, BANK, "t1"))
    store.close()
    reopened = CampaignStore(path)
    try:
        assert reopened.count() == 3 and reopened.threshold > 0
        assert c.list_campaigns(store=reopened, as_of=NOW)[0].linked_message_ids == []
    finally:
        reopened.close()


def test_match_is_read_only_has_real_counts_and_contract(seeded):
    store, _ = seeded
    incoming = query()
    before = store.count()
    result = c.match_campaign(MatchCampaignArgs(message_id=incoming.message_id), incoming, store=store)
    again = c.match_campaign(MatchCampaignArgs(message_id=incoming.message_id), incoming, store=store)
    assert result == again and store.count() == before
    assert result.campaign_id and result.similar_last_24h == 2 and result.similarity == 1
    cards = {card.campaign_id: card for card in c.list_campaigns(store=store, as_of=NOW)}
    card = cards[result.campaign_id]
    assert card.count_total == 2 and card.count_last_24h == 2
    assert card.redacted_example.startswith("Pattern preview:")
    assert "Mira" not in card.model_dump_json() and "https://" not in card.model_dump_json()


def test_observation_is_explicit_idempotent_and_excludes_self(seeded):
    store, _ = seeded
    incoming = query("runtime")
    assert c.record_message(incoming, store=store) == 1
    assert c.record_message(incoming, store=store) == 0
    result = c.match_campaign(MatchCampaignArgs(message_id="runtime"), incoming, store=store)
    assert result.similar_last_24h == 2
    card = next(card for card in c.list_campaigns(store=store, as_of=NOW) if card.campaign_id == result.campaign_id)
    assert card.count_total == 3 and card.linked_message_ids == ["runtime"]


def test_unique_observation_is_thread_safe(seeded):
    store, _ = seeded
    incoming = query("threaded")
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: c.record_message(incoming, store=store), range(8)))
    assert sum(results) == 1 and store.count() == 4


def test_time_window_preserves_original_dates_and_excludes_future(corpus):
    train, val, split = corpus
    store = CampaignStore()
    try:
        c.calibrate_threshold(train, val, store=store, splits_path=split)
        rows = [train[0].model_copy(update={"received_at": NOW-timedelta(hours=25)}),
                train[1].model_copy(update={"received_at": NOW-timedelta(hours=24)})]
        c.seed_campaigns(rows, store=store, splits_path=split)
        c.record_message(query("future", time=NOW+timedelta(hours=1)), store=store)
        result = c.match_campaign(MatchCampaignArgs(message_id="incoming"), query(), store=store)
        assert result.similar_last_24h == 1
        card = c.list_campaigns(store=store, as_of=NOW)[0]
        assert card.count_total == 2 and card.count_last_24h == 1
        later = c.match_campaign(MatchCampaignArgs(message_id="later"), query("later", time=NOW+timedelta(days=3)), store=store)
        assert later.campaign_id and later.similar_last_24h == 0
    finally:
        store.close()


def test_self_alone_is_not_campaign_evidence(corpus):
    train, val, split = corpus
    store = CampaignStore()
    try:
        c.calibrate_threshold(train, val, store=store, splits_path=split)
        incoming = query("only")
        c.record_message(incoming, store=store)
        result = c.match_campaign(MatchCampaignArgs(message_id="only"), incoming, store=store)
        assert result.campaign_id is None and result.similar_last_24h == 0
    finally:
        store.close()


def test_empty_store_and_bad_args(seeded):
    empty = CampaignStore()
    try:
        assert c.match_campaign(MatchCampaignArgs(message_id="incoming"), query(), store=empty).campaign_id is None
        with pytest.raises(ValueError, match="message_id"):
            c.match_campaign(MatchCampaignArgs(message_id="wrong"), query(), store=empty)
    finally:
        empty.close()


def test_unknown_category_and_naive_dates_fail_closed():
    incoming = query()
    incoming.classifier.category = "arbitrary_person_name"
    with pytest.raises(ValueError, match="category"):
        c.fingerprint(incoming)
    incoming = query(); incoming.received_at = NOW.replace(tzinfo=None)
    with pytest.raises(ValueError, match="timezone"):
        c.fingerprint(incoming)


def test_conflicting_observation_rolls_back_batch(corpus, seeded):
    train, _, _ = corpus
    store, _ = seeded
    changed = Fingerprint(**c.fingerprint(c.message_input(train[0].model_copy(update={"text": "T-Mobile different billing demand"}))))
    new = Fingerprint(**c.fingerprint(query("new-before-conflict", time=NOW-timedelta(days=2))))
    before = store.count()
    with pytest.raises(ValueError, match="different fingerprint"):
        store.add([new, changed], c.similarity)
    assert store.count() == before


def test_calibration_cannot_change_under_existing_rows(seeded):
    store, report = seeded
    changed = {**report, "threshold": 0.55 if report["threshold"] != 0.55 else 0.60}
    with pytest.raises(ValueError, match="fresh"):
        store.set_calibration(changed)
    with pytest.raises(ValueError, match="metadata"):
        store.set_calibration({**report, "raw_text": "never persist"})


def test_sql_injection_like_id_is_hashed_and_never_persisted(seeded):
    store, _ = seeded
    key = "msg'); DROP TABLE fingerprints; --"
    assert c.record_message(query(key), store=store) == 1
    assert key not in "\n".join(store._db.iterdump()) and store.count() == 4


def test_cli_uses_saved_partitions_and_aggregate_report(corpus, tmp_path, monkeypatch, capsys):
    train, val, split = corpus
    (tmp_path / "messages.jsonl").write_text("\n".join(m.model_dump_json() for m in train+val))
    report_path = tmp_path / "report.json"
    monkeypatch.setattr("sys.argv", ["seed_campaigns", "--generated-dir", str(tmp_path), "--splits", str(split),
                                    "--database", str(tmp_path / "db.sqlite3"), "--report", str(report_path)])
    assert cli.main() == 0
    report = json.loads(report_path.read_text())
    assert report["stored_fingerprints"] == 3 and report["new_fingerprints"] == 3
    assert BILL not in capsys.readouterr().out
    assert cli.main() == 0 and json.loads(report_path.read_text())["new_fingerprints"] == 0



def test_semantic_fingerprint_compares_paraphrases_without_storing_features():
    first = c.message_input(message("wording-one", "T-Mobile: please pay $20 at https://tmobile-pay.example/"))
    second = c.message_input(message("wording-two", "T-Mobile: settle your balance of $30 via https://tmobile-bill.example/"))
    left, right = Fingerprint(**c.fingerprint(first)), Fingerprint(**c.fingerprint(second))
    assert c.similarity(left, right, semantic_weight=0.75) > c.similarity(left, right, semantic_weight=0)
    assert "click_link_and_pay" not in json.dumps(c.fingerprint(first))


def test_semantic_weight_is_selected_and_stored_by_validation(seeded):
    store, report = seeded
    assert report["semantic_weight"] in c.SEMANTIC_WEIGHTS
    assert store.semantic_weight == report["semantic_weight"]




def test_semantic_overlap_allows_optional_detail_but_requires_shared_intent():
    short = c.message_input(message("short", "T-Mobile: pay your balance at https://tmobile-pay.example/"))
    detailed = c.message_input(message("detailed", "T-Mobile: settle your bill of $30 within 2 hours to avoid service suspension at https://tmobile-pay.example/"))
    unrelated = c.message_input(message("other", "T-Mobile: visit https://tmobile-pay.example/"))
    left, right, other = (Fingerprint(**c.fingerprint(item)) for item in (short, detailed, unrelated))
    assert c.similarity(left, right, semantic_weight=0.75) > c.similarity(left, right)
    assert c.similarity(left, other, semantic_weight=0.75) == c.similarity(left, other)



def test_real_train_validation_bootstrap_and_authored_scenario_have_real_counts():
    from app.config import DATA_DIR
    train, validation = c.load_training_validation()
    saved = json.loads(c.SPLITS_PATH.read_text())
    store = CampaignStore()
    try:
        calibration = c.calibrate_threshold(train, validation, store=store)
        assert c.seed_campaigns(train, store=store) == sum(bool(message.is_scam) for message in train)
        before = store.count()
        probe = cli.verify_scenario3(store, DATA_DIR / "scenarios" / "scenario_3.json")
        assert probe["matched_real_campaign"]
        members = store.members(as_of=datetime.fromisoformat(probe["query_time"]))
        cohort = [member for member in members if member.campaign_id == probe["campaign_id"]]
        assert probe["historical_support"] == len(cohort) > 1
        cutoff = datetime.fromisoformat(probe["query_time"])-timedelta(hours=24)
        assert probe["similar_last_24h"] == sum(datetime.fromisoformat(member.fingerprint.observed_at) >= cutoff for member in cohort)
        forbidden = {c._event_hash(key) for key in saved["val"]+saved["test"]+["scenario_3"]}
        assert not forbidden.intersection(member.fingerprint.event_hash for member in store.members())
        assert store.count() == before
        report = json.loads((DATA_DIR / "campaign_calibration.json").read_text())
        assert report["calibration"] == calibration
    finally:
        store.close()
