"""Every mock validates against its contract, and the data files have the right shape."""

from __future__ import annotations

import json

import pytest
from pydantic import TypeAdapter, ValidationError

from app import contracts as c
from app import mocks
from app.config import DATA_DIR


def test_every_mock_file_is_registered():
    on_disk = {p.name for p in mocks.MOCK_DIR.glob("*.json")}
    assert on_disk == set(mocks.MOCK_TYPES)


@pytest.mark.parametrize("name", sorted(mocks.MOCK_TYPES))
def test_mock_validates(name):
    TypeAdapter(mocks.MOCK_TYPES[name]).validate_python(mocks.load_raw(name))


@pytest.mark.parametrize("name", [n for n in mocks.MOCK_TYPES if n.startswith("result_")])
def test_mock_results_follow_guardrails(name):
    poll: c.ResultPoll = mocks.load(name)
    result = poll.result
    assert result is not None and poll.status == c.JobStatus.done
    assert len(result.actions) <= 3
    if result.confidence_words == c.ConfidenceWords.very_likely:
        assert len({e.tool for e in result.evidence}) >= 2
    assert [t.step for t in poll.trail] == list(range(1, len(poll.trail) + 1))
    assert {i.ref for i in poll.was_this_you_items} == set(result.was_this_you)


@pytest.mark.parametrize("n", [1, 2, 3])
def test_scenario_files_match_post_body(n):
    raw = json.loads((DATA_DIR / "scenarios" / f"scenario_{n}.json").read_text(encoding="utf-8"))
    c.MessageIn.model_validate(raw["message"])


def test_taxonomy_placeholder_has_legit():
    taxonomy = json.loads((DATA_DIR / "taxonomy.json").read_text(encoding="utf-8"))
    ids = [cat["id"] for cat in taxonomy["categories"]]
    assert "legit" in ids and len(ids) == len(set(ids))


def test_agent_input_example_from_data_spec():
    example = {
        "message_id": "msg_0142",
        "mode": "check",
        "received_at": "2026-11-08T09:14:00-06:00",
        "sender": {"type": "long_code", "value": "<PHONE_HASH_7f3a>", "claimed_brand": "Capital One"},
        "text_redacted": "Capital One Alert: unusual sign-in for <PERSON>. Your account will be locked in 2 hours. Verify now: <URL_1>",
        "urls": [{"id": "URL_1", "registered_domain": "capone-verify-alert.com", "is_shortener": False, "brand_term_in_domain": "capone", "is_official_brand_domain": False}],
        "features": {"urgency_deadline": "2 hours", "threat": "account_lock", "requested_action": "click_link_and_verify", "asks_for": ["login"], "money_amount_claimed": None},
        "classifier": {"category": "bank_impersonation", "score": 0.94, "top3": [["bank_impersonation", 0.94], ["account_suspension", 0.03], ["legit_alert", 0.02]], "baseline_score": 0.81},
        "customer_context": {"linked_bank": True, "linked_institutions": ["Capital One"]},
    }
    c.AgentInput.model_validate(example)
    with pytest.raises(ValidationError):
        c.AgentInput.model_validate({**example, "mode": "recovery"})


def test_agent_result_rejects_out_of_enum_and_too_many_actions():
    good = {
        "plan": ["check_link"],
        "verdict": "likely_scam",
        "confidence_words": "likely",
        "reason": "r",
        "evidence": [],
        "actions": ["block_sender"],
        "was_this_you": [],
        "replan": False,
    }
    c.AgentResult.model_validate(good)
    with pytest.raises(ValidationError):
        c.AgentResult.model_validate({**good, "verdict": "safe"})
    with pytest.raises(ValidationError):
        c.AgentResult.model_validate({**good, "actions": ["block_sender", "report_spam", "ignore", "freeze_card"]})


def test_nessie_activity_args_need_exactly_one():
    c.NessieRecentActivityArgs(days=7)
    c.NessieRecentActivityArgs(since="2026-11-08T09:14:00-06:00")
    with pytest.raises(ValidationError):
        c.NessieRecentActivityArgs()
    with pytest.raises(ValidationError):
        c.NessieRecentActivityArgs(days=7, since="2026-11-08T09:14:00-06:00")
