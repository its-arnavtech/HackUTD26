"""A21: synthetic dataset generator. Fast and offline (no DeepSeek calls)."""

from __future__ import annotations

import hashlib
import json

import pytest

from app.config import DATA_DIR
from app.contracts import Message, MessageSource
from scripts import generate_dataset as gd
from scripts.dataset_prompts import LEGIT_SUBTYPE_POOL, PROMPT_SETS


@pytest.fixture(scope="module")
def taxonomy():
    return gd.load_taxonomy()


# --- taxonomy and prompt sets -------------------------------------------------


def test_taxonomy_shape(taxonomy):
    assert "legit" in taxonomy and taxonomy["legit"]["is_scam"] is False
    scam = [c for c in taxonomy.values() if c["is_scam"]]
    assert len(scam) >= 3
    for cat in taxonomy.values():
        assert cat["label"] and cat["description"] and cat["subtypes"]
    # every legit subtype has a brand pool in both prompt sets
    for subtype in taxonomy["legit"]["subtypes"]:
        pool = LEGIT_SUBTYPE_POOL[subtype]
        for ps in PROMPT_SETS.values():
            assert ps.legit_brands[pool]


def test_every_scam_category_has_brands_in_both_sets(taxonomy):
    for cat_id, cat in taxonomy.items():
        if cat["is_scam"]:
            for ps in PROMPT_SETS.values():
                assert ps.brands[cat_id], (ps.name, cat_id)


def test_train_and_test_prompt_sets_differ():
    train, test = PROMPT_SETS["train_v1"], PROMPT_SETS["test_v1"]
    assert train.system != test.system
    assert train.user_template != test.user_template
    assert not set(train.personas_scam) & set(test.personas_scam)
    assert not set(train.styles) & set(test.styles)
    # test adds brands train never saw, in every scam category with a brand
    for cat_id, brands in test.brands.items():
        if brands != ("no brand",):
            assert set(brands) - set(train.brands[cat_id]), cat_id


# --- job plan ---------------------------------------------------------------


def test_plan_is_deterministic_and_prefix_stable(taxonomy):
    ps = PROMPT_SETS["train_v1"]
    a = gd.plan_jobs(taxonomy, ps)
    b = gd.plan_jobs(taxonomy, ps)
    assert a == b
    small = gd.plan_jobs(taxonomy, ps, max_jobs_per_category=2)
    assert all(job in a for job in small)  # raising the job count keeps earlier jobs
    assert len({j.job_id for j in a}) == len(a)


def test_plan_covers_targets(taxonomy):
    for name, ps in PROMPT_SETS.items():
        jobs = gd.plan_jobs(taxonomy, ps)
        for cat_id, cat in taxonomy.items():
            n_calls = sum(1 for j in jobs if j.category == cat_id)
            assert n_calls * gd.BATCH_SIZE >= gd.category_target(name, cat)


def test_build_request_has_no_braces_left(taxonomy):
    for ps in PROMPT_SETS.values():
        job = gd.plan_jobs(taxonomy, ps, max_jobs_per_category=1)[0]
        req = gd.build_request(job, taxonomy, "deepseek-test")
        user = req["messages"][1]["content"]
        assert '{"messages"' in user and "{n}" not in user and "{brand}" not in user
        assert req["response_format"] == {"type": "json_object"}


# --- cache --------------------------------------------------------------------


def test_cache_records_then_replays(tmp_path):
    calls = []

    def fake_api(request):
        calls.append(request)
        return '{"messages": ["hello there, this is a test message"]}'

    req = {"model": "m", "messages": [{"role": "user", "content": "x"}]}
    first = gd.cached_completion(req, fake_api, cache_dir=tmp_path)
    second = gd.cached_completion(req, None, cache_dir=tmp_path)  # offline replay
    assert first == second and len(calls) == 1


def test_cache_miss_offline_raises(tmp_path):
    with pytest.raises(gd.CacheMiss):
        gd.cached_completion({"model": "m"}, None, cache_dir=tmp_path)


def test_unparseable_response_is_not_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(gd.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError):
        gd.cached_completion({"model": "m"}, lambda r: "", cache_dir=tmp_path, attempts=2)
    assert not list(tmp_path.glob("*.json"))


def test_request_key_ignores_dict_order():
    assert gd.request_key({"a": 1, "b": 2}) == gd.request_key({"b": 2, "a": 1})


# --- parsing and quality ------------------------------------------------------


@pytest.mark.parametrize(
    "content,expected",
    [
        ('{"messages": ["one", " two  three "]}', ["one", "two three"]),
        ('```json\n{"messages": ["a"]}\n```', ["a"]),
        ('{"texts": ["x", "y"]}', ["x", "y"]),
        ('{"messages": [{"text": "z"}]}', ["z"]),
        ('Sure! {"messages": ["q"]} hope this helps', ["q"]),
        ("", []),
        ('{"messages": ["cut off', []),
    ],
)
def test_parse_messages(content, expected):
    assert gd.parse_messages(content) == expected


def test_fictionalize_phones_rewrites_only_non_fictional():
    text, n = gd.fictionalize_phones("Call 214-555-0143 or 1-800-432-1000 or (972) 618-2290 or +12145550199 or +19725551234")
    assert n == 3
    assert "214-555-0143" in text and "+12145550199" in text  # already fictional, kept
    assert "800-555-01" in text and "972-555-01" in text and "+1972555" + "01" in text
    assert gd.fictionalize_phones(text)[1] == 0  # idempotent


def test_fictionalize_phones_leaves_codes_and_amounts():
    text = "Your code is 482913. Balance $1,842.17. Order #114-8823. Tracking 9400111202."
    assert gd.fictionalize_phones(text) == (text, 0)


@pytest.mark.parametrize(
    "text,is_scam,reason",
    [
        ("short", True, "too_short"),
        ("x" * 500, False, "too_long"),
        ("As an AI, I can't write this message for you, sorry.", True, "refusal"),
        ("Hi [Name], your package is waiting at the depot.", True, "placeholder"),
        ("This is a scam text pretending to be your bank, click here.", True, "label_leak"),
        ("Chase: we will never ask for your code. Beware of scams. Balance $40.", False, None),
        ("USPS: your parcel is held, update your address at usps-help.top", True, None),
    ],
)
def test_quality_issue(text, is_scam, reason):
    assert gd.quality_issue(text, is_scam) == reason


def test_normalize_masks_urls_and_digits():
    a = gd.normalize("Pay $312 now: https://tmobile-billpay-now.com/pay")
    b = gd.normalize("Pay $999 now: https://other-site.net/x")
    assert a == b


# --- dedupe -------------------------------------------------------------------


def _cand(text, category="legit"):
    job = gd.Job("j", "train_v1", category, category != "legit", "s", "bank", "b", "p", "st", 8)
    return gd.Candidate(text=text, job=job, norm=gd.normalize(text))


def test_dedupe_exact_and_near():
    cands = [
        _cand("Your package is out for delivery today between 2 and 6 pm."),
        _cand("Your package is out for delivery today between 3 and 7 pm."),  # exact after digit masking
        _cand("Your package is out for delivery today between 2 and 6 pm!!"),  # exact after punctuation
        _cand("Your package is out for delivry today between 2 and 6pm."),  # near
        _cand("Reminder: dentist appointment Monday at 9am. Reply C to confirm."),
    ]
    kept, stats = gd.dedupe(cands)
    assert [c.text for c in kept] == [cands[0].text, cands[4].text]
    assert stats["exact_duplicate"] == 2 and stats["near_duplicate"] == 1


def test_drop_close_to_reference():
    ref = [gd.normalize("USPS: your parcel is held, update your address at usps-help.top")]
    cands = [_cand("USPS: your parcel is held. Update your address at usps-fix.top", "delivery_scam"), _cand("Totally different text about a dentist visit")]
    kept, dropped = gd.drop_close_to(cands, ref)
    assert dropped == 1 and kept[0].text.startswith("Totally")


# --- senders and times ----------------------------------------------------------


def test_senders_are_synthetic_and_deterministic():
    for i in range(200):
        mid = f"tr_{i:05d}"
        s = gd.assign_sender(mid, "bank_impersonation", True, "bank_impersonation")
        assert s == gd.assign_sender(mid, "bank_impersonation", True, "bank_impersonation")
        if s.startswith("+"):
            assert s.startswith("+155501") and len(s) == 12
        elif "@" not in s:
            assert s.isdigit() and len(s) in (5, 6)


def test_sender_types_overlap_between_scam_and_legit():
    def kinds(category, is_scam, pool):
        out = set()
        for i in range(300):
            s = gd.assign_sender(f"x{i}", category, is_scam, pool)
            out.add("email" if "@" in s else "long" if s.startswith("+") else "short")
        return out

    assert {"long", "short"} <= kinds("bank_impersonation", True, "bank_impersonation")
    assert {"long", "short"} <= kinds("legit", False, "bank")


# --- end to end on fake responses -------------------------------------------------


def test_build_set_end_to_end(taxonomy, monkeypatch):
    monkeypatch.setitem(gd.TARGETS, "train_v1", {"legit": 2, "scam_each": 1})
    jobs = gd.plan_jobs(taxonomy, PROMPT_SETS["train_v1"], max_jobs_per_category=1)
    def distinct(seed: str) -> str:  # letters only, so texts stay far apart after normalizing
        return " ".join(hashlib.sha256(f"{seed}{i}".encode()).hexdigest().translate(str.maketrans("0123456789", "ghijklmnop"))[:8] for i in range(6))

    responses = {
        j.job_id: [
            f"Note {distinct(j.job_id + 'a')}",
            f"Note {distinct(j.job_id + 'a')}",  # duplicate
            f"Other {distinct(j.job_id + 'b')}",
            "[Name] placeholder text that should be rejected by quality",
        ]
        for j in jobs
    }
    records, report = gd.build_set("train_v1", jobs, responses, taxonomy, [])
    assert report["pipeline"]["rejected_placeholder"] == len(jobs)
    assert report["pipeline"]["exact_duplicate"] == len(jobs)
    assert report["per_category"]["legit"] == 2
    assert all(report["per_category"][c] == 1 for c in taxonomy if c != "legit")
    assert not report["shortfall"]
    for msg, meta in records:
        assert msg.prompt_set == "train_v1" and msg.source == MessageSource.generated
        assert meta["message_id"] == msg.message_id
        assert msg.is_scam == taxonomy[msg.category]["is_scam"]


# --- committed outputs -------------------------------------------------------


def _read_messages(path):
    return [Message.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_handwritten_set_is_valid(taxonomy):
    msgs = gd.load_handwritten()
    assert 40 <= len(msgs) <= 70
    assert gd.check_handwritten(msgs, taxonomy) == []
    assert sum(1 for m in msgs if not m.is_scam) / len(msgs) >= 1 / 3


@pytest.mark.skipif(not gd.MESSAGES_PATH.exists(), reason="dataset not generated yet")
def test_generated_dataset_contract(taxonomy):
    msgs = _read_messages(gd.MESSAGES_PATH)
    ids = [m.message_id for m in msgs]
    assert len(ids) == len(set(ids))
    for m in msgs:
        assert m.category in taxonomy and m.is_scam == taxonomy[m.category]["is_scam"]
        assert m.prompt_set in ("train_v1", "test_v1") and m.source == MessageSource.generated
        assert gd.fictionalize_phones(m.text)[1] == 0
        assert gd.quality_issue(m.text, bool(m.is_scam)) is None
    assert sum(1 for m in msgs if not m.is_scam) / len(msgs) >= 1 / 3
    # no exact (normalized) overlap between train and test prompt sets
    train = {gd.normalize(m.text) for m in msgs if m.prompt_set == "train_v1"}
    test = {gd.normalize(m.text) for m in msgs if m.prompt_set == "test_v1"}
    assert not train & test
    metas = [json.loads(line) for line in gd.META_PATH.read_text(encoding="utf-8").splitlines()]
    assert [m["message_id"] for m in metas] == ids


@pytest.mark.skipif(not gd.REPORT_PATH.exists(), reason="dataset not generated yet")
def test_offline_rebuild_matches_committed_output(tmp_path, monkeypatch):
    """The committed cache rebuilds exactly the committed dataset, with no key."""
    before = gd.MESSAGES_PATH.read_text(encoding="utf-8").splitlines()  # lines, not bytes: git may check out CRLF
    monkeypatch.setattr(gd, "MESSAGES_PATH", tmp_path / "messages.jsonl")
    monkeypatch.setattr(gd, "META_PATH", tmp_path / "meta.jsonl")
    monkeypatch.setattr(gd, "REPORT_PATH", tmp_path / "quality_report.json")
    model = json.loads((DATA_DIR / "generated" / "quality_report.json").read_text(encoding="utf-8"))["model"]
    assert gd.main(["--offline", "--model", model, "--workers", "4"]) == 0
    assert (tmp_path / "messages.jsonl").read_text(encoding="utf-8").splitlines() == before
