"""L8: agent loop, prompts and guardrails. Nemotron and the tools are faked; no network."""

from __future__ import annotations

import copy
import json

import pytest

from app import contracts as c
from app.agent import guardrails, loop, prompts
from app.agent.registry import ToolCall
from tests.agent_input_factory import make_input

INPUT = make_input()

GOOD_FINAL = {
    "plan": ["check_link", "check_sender"],
    "verdict": "likely_scam",
    "confidence_words": "very likely",
    "reason": "The link is not a Capital One website and the sender is not an official Capital One channel.",
    "evidence": [
        {"tool": "check_link", "finding": "Domain is 3 days old and imitates Capital One"},
        {"tool": "check_sender", "finding": "Not an official Capital One channel"},
    ],
    "actions": ["block_sender", "report_spam", "call_number_on_card"],
    "was_this_you": [],
    "replan": False,
}

TOOL_RESULTS = {
    "check_link": {"domain": "capone-verify-alert.com", "domain_age_days": 3, "on_blocklist": False, "lookalike_of": "capitalone.com", "signals": []},
    "check_sender": {"sender_type": "long_code", "matches_official_channel": False, "official_channels_known": True, "note": "Not official"},
    "match_campaign": {"campaign_id": "camp_07", "similar_last_24h": 140, "similarity": 0.91},
    "nessie_recent_activity": {"accounts_checked": 2, "items_checked": 23, "flagged": []},
    "nessie_bill_status": {"found": True, "last_status": "completed", "last_payment_date": "2026-11-01", "amount_due_now": 0, "recurring": True},
    "public_scam_reports": {"reports_found": 2, "domain_reported": True},
}


# --- fakes -------------------------------------------------------------------------


def tools_turn(*calls: tuple[str, dict], reasoning: str | None = None) -> dict:
    msg = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": f"call_{name}_{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
            for i, (name, args) in enumerate(calls)
        ],
    }
    if reasoning:
        msg["reasoning_content"] = reasoning
    return {"choices": [{"message": msg, "finish_reason": "tool_calls"}]}


def final_turn(body, reasoning: str | None = None) -> dict:
    content = body if isinstance(body, str) else json.dumps(body)
    msg = {"role": "assistant", "content": content}
    if reasoning:
        msg["reasoning_content"] = reasoning
    return {"choices": [{"message": msg, "finish_reason": "stop"}]}


def json_action(obj) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": json.dumps(obj)}, "finish_reason": "stop"}]}


class FakeChat:
    """Plays back scripted responses and records every request."""

    def __init__(self, *responses, repeat_last: bool = False):
        self.responses = list(responses)
        self.repeat_last = repeat_last
        self.requests: list[list[dict]] = []
        self.tool_choices: list[str] = []

    def __call__(self, messages, tools=None, tool_choice="auto"):
        self.requests.append(copy.deepcopy(messages))
        self.tool_choices.append(tool_choice)
        if not self.responses:
            raise AssertionError("chat called more times than scripted")
        if self.repeat_last and len(self.responses) == 1:
            return copy.deepcopy(self.responses[0])
        resp = self.responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


class FakeTools:
    def __init__(self, ms: int = 5, fail: set[str] = frozenset()):
        self.ms, self.fail = ms, fail
        self.called: list[tuple[str, object]] = []

    def __call__(self, name, args, agent_input, on_call=None):
        self.called.append((name, args))
        if name not in TOOL_RESULTS:
            return ToolCall(name=name, args={}, ok=False, error={"type": "unknown_tool", "message": "no such tool"}, ms=1)
        if name in self.fail:
            return ToolCall(name=name, args=args or {}, ok=False, error={"type": "timeout", "message": "slow"}, ms=self.ms)
        return ToolCall(name=name, args=args or {}, ok=True, result=TOOL_RESULTS[name], ms=self.ms)


def run(chat, tools=None, agent_input=INPUT, protocol="native"):
    trail: list[c.TrailEntry] = []
    result = loop.run_agent(agent_input, trail.append, chat=chat, call_tool=tools or FakeTools(), tool_schemas=[], protocol=protocol)
    return result, trail


def kinds(trail):
    return [t.kind for t in trail]


# --- guardrails: contacts ---------------------------------------------------------------


@pytest.mark.parametrize(
    "text,gone",
    [
        ("Call 1-800-555-0199 now.", "555"),
        ("Call (555) 010-4477 today.", "4477"),
        ("Reply to +15550104477.", "15550104477"),
        ("Visit https://capone-verify.example/login now.", "https"),
        ("Go to www.capital0ne-help.com to verify.", "www"),
        ("The domain capone-verify-alert.com is new.", "capone-verify-alert"),
        ("Text STOP to 227898.", "227898"),
    ],
)
def test_strip_contacts_removes_phones_and_links(text, gone):
    assert gone not in guardrails.strip_contacts(text)


@pytest.mark.parametrize(
    "text",
    [
        "The domain is 3 days old.",
        "A $900 transfer to a new payee 17 minutes later (txn_3).",
        "Your account will be locked in 2 hours.",
        "No unusual activity in 7 days.",
        "Bill paid on 2026-11-01.",
        "Unusual sign-in for <PERSON>. Verify: <URL_1>",
    ],
)
def test_strip_contacts_keeps_ordinary_text(text):
    assert guardrails.strip_contacts(text) == text


def test_strip_contacts_empty():
    assert guardrails.strip_contacts("") == ""


# --- guardrails: validation ---------------------------------------------------------------


def test_validate_accepts_good_result():
    assert guardrails.validate_result(GOOD_FINAL).verdict == c.Verdict.likely_scam


@pytest.mark.parametrize(
    "change",
    [
        {"verdict": "definitely_scam"},
        {"confidence_words": "100%"},
        {"actions": ["wire_money"]},
        {"plan": ["delete_account"]},
        {"evidence": [{"tool": "check_link"}]},
    ],
)
def test_validate_rejects_values_outside_the_enums(change):
    with pytest.raises(ValueError):
        guardrails.validate_result({**GOOD_FINAL, **change})


def test_validate_rejects_missing_fields_and_non_objects():
    with pytest.raises(ValueError):
        guardrails.validate_result({k: v for k, v in GOOD_FINAL.items() if k != "verdict"})
    with pytest.raises(ValueError):
        guardrails.validate_result(["not", "an", "object"])


def test_validate_error_does_not_echo_the_input():
    with pytest.raises(ValueError) as exc:
        guardrails.validate_result({**GOOD_FINAL, "verdict": "SECRET_VALUE_123"})
    assert "SECRET_VALUE_123" not in str(exc.value)


def test_validate_forgives_case_extra_keys_and_too_many_actions():
    raw = {**GOOD_FINAL, "verdict": "Likely_Scam", "confidence_words": "Very Likely", "summary": "extra",
           "actions": ["block_sender", "report_spam", "freeze_card", "change_password", "block_sender"]}
    result = guardrails.validate_result(raw)
    assert result.confidence_words == c.ConfidenceWords.very_likely
    assert result.actions == [c.Action.block_sender, c.Action.report_spam, c.Action.freeze_card]


# --- guardrails: enforcement ------------------------------------------------------------------

SCAM_CLASSIFIER = c.ClassifierOutput(category="bank_impersonation", score=0.94)
LEGIT_CLASSIFIER = c.ClassifierOutput(category="legit", score=0.9)


def result(**update) -> c.AgentResult:
    return guardrails.validate_result({**GOOD_FINAL, **update})


def test_very_likely_needs_two_different_tools():
    one_tool = result(evidence=[{"tool": "check_link", "finding": "a"}, {"tool": "check_link", "finding": "b"}])
    fixed, notes = guardrails.apply_guardrails(one_tool, SCAM_CLASSIFIER)
    assert fixed.confidence_words == c.ConfidenceWords.likely and notes
    assert guardrails.enforce(result(), SCAM_CLASSIFIER).confidence_words == c.ConfidenceWords.very_likely


def test_classifier_legit_but_tools_say_scam_is_unsure():
    fixed = guardrails.enforce(result(), LEGIT_CLASSIFIER)
    assert fixed.verdict == c.Verdict.unsure and fixed.confidence_words == c.ConfidenceWords.not_sure


def test_classifier_scam_but_tools_say_safe_is_unsure():
    safe = result(verdict="likely_safe", confidence_words="likely", actions=["ignore"])
    assert guardrails.enforce(safe, SCAM_CLASSIFIER).verdict == c.Verdict.unsure


def test_low_confidence_classifier_does_not_force_unsure():
    safe = result(verdict="likely_safe", confidence_words="likely", actions=["ignore"])
    weak = c.ClassifierOutput(category="billing_scam", score=0.69)
    assert guardrails.enforce(safe, weak).verdict == c.Verdict.likely_safe


def test_unsure_always_says_not_sure():
    assert guardrails.enforce(result(verdict="unsure", confidence_words="likely"), SCAM_CLASSIFIER).confidence_words == c.ConfidenceWords.not_sure


def test_contacts_stripped_from_reason_and_evidence():
    dirty = result(
        reason="Don't call 1-800-555-0199; the real site is https://capitalone.example.",
        evidence=[{"tool": "check_link", "finding": "Imitates capitalone.com"}, {"tool": "check_sender", "finding": "Call 555-010-4477"}],
    )
    fixed = guardrails.enforce(dirty, SCAM_CLASSIFIER)
    text = fixed.reason + " ".join(e.finding for e in fixed.evidence)
    assert "555" not in text and "http" not in text and "capitalone.com" not in text


def test_reason_emptied_by_stripping_gets_honest_default():
    fixed = guardrails.enforce(result(reason="https://x.example"), SCAM_CLASSIFIER)
    assert fixed.reason and "fine" not in fixed.reason


def test_evidence_from_tools_that_did_not_run_is_dropped():
    fixed, notes = guardrails.apply_guardrails(result(), SCAM_CLASSIFIER, tools_run=["check_link"])
    assert [e.tool for e in fixed.evidence] == [c.ToolName.check_link]
    assert fixed.confidence_words == c.ConfidenceWords.likely and notes


def test_unsure_fallback_keeps_valid_evidence_only():
    fb = guardrails.unsure_fallback([{"tool": "check_link", "finding": "New domain"}, {"tool": "nope", "finding": "x"}, {"oops": 1}, "junk"])
    assert fb.verdict == c.Verdict.unsure and fb.confidence_words == c.ConfidenceWords.not_sure
    assert [e.tool for e in fb.evidence] == [c.ToolName.check_link] and fb.plan == [c.ToolName.check_link]
    assert guardrails.unsure_fallback([]).evidence == []


# --- prompts -----------------------------------------------------------------------------------


def test_build_messages_shape_and_payload():
    msgs = prompts.build_messages(INPUT)
    assert [m["role"] for m in msgs] == ["system", "user"]
    assert c.AgentInput.model_validate_json(msgs[1]["content"]) == INPUT


def test_system_prompt_names_every_tool_but_not_the_result_schema():
    for tool in c.ToolName:
        assert tool.value in prompts.SYSTEM_PROMPT
    # Two-phase prompting: the result schema comes later.
    assert "confidence_words" not in prompts.SYSTEM_PROMPT and "was_this_you" not in prompts.SYSTEM_PROMPT


def test_final_instruction_lists_keys_and_enums():
    text = prompts.final_instruction("native")
    for key in ("plan", "verdict", "confidence_words", "reason", "evidence", "actions", "was_this_you", "replan"):
        assert key in text
    for value in [*c.Verdict, *c.ConfidenceWords, *c.Action]:
        assert value.value in text
    assert '"action":"finish"' in prompts.final_instruction("json_action")


# --- loop: happy path -------------------------------------------------------------------------


def test_plan_then_tools_then_verdict():
    chat = FakeChat(
        tools_turn(("check_link", {"url_id": "URL_1"}), ("check_sender", {"claimed_brand": "Capital One"})),
        final_turn("I have what I need."),
        final_turn(GOOD_FINAL),
    )
    tools = FakeTools()
    res, trail = run(chat, tools)
    assert res.verdict == c.Verdict.likely_scam and res.confidence_words == c.ConfidenceWords.very_likely
    assert kinds(trail) == [c.TrailKind.plan, c.TrailKind.tool, c.TrailKind.tool, c.TrailKind.verdict]
    assert [t.step for t in trail] == [1, 2, 3, 4]
    assert [t.tool for t in trail[1:3]] == [c.ToolName.check_link, c.ToolName.check_sender]
    assert trail[0].finding == "Plan: check_link, check_sender"
    assert trail[-1].finding == "Very likely a scam"
    assert [n for n, _ in tools.called] == ["check_link", "check_sender"]
    assert res.replan is False


def test_plan_is_logged_before_any_tool_runs():
    trail: list[c.TrailEntry] = []

    def tool(name, args, ai, on_call=None):
        assert trail and trail[0].kind == c.TrailKind.plan, "tool ran before the plan was logged"
        return FakeTools()(name, args, ai)

    chat = FakeChat(tools_turn(("check_link", {"url_id": "URL_1"})), final_turn(GOOD_FINAL))
    loop.run_agent(INPUT, trail.append, chat=chat, call_tool=tool, tool_schemas=[], protocol="native")
    assert trail[0].kind == c.TrailKind.plan


def test_trail_entries_match_data_spec_3_4():
    chat = FakeChat(tools_turn(("check_link", {"url_id": "URL_1"})), final_turn(GOOD_FINAL))
    _, trail = run(chat)
    for entry in trail:
        dumped = entry.model_dump(mode="json")
        assert set(dumped) == {"step", "kind", "tool", "why", "finding", "ms", "at"}
        assert dumped["kind"] in {k.value for k in c.TrailKind}
    tool_entry = trail[1]
    assert tool_entry.tool == c.ToolName.check_link and tool_entry.why and tool_entry.finding and tool_entry.ms is not None


def test_final_schema_sent_only_after_tools_return():
    chat = FakeChat(tools_turn(("check_link", {"url_id": "URL_1"})), final_turn("done"), final_turn(GOOD_FINAL))
    run(chat)
    first, second, third = chat.requests
    schema = prompts.FINAL_INSTRUCTION[:60]
    assert not any(schema in (m.get("content") or "") for m in first)
    assert not any(schema in (m.get("content") or "") for m in second)
    assert any(m["role"] == "system" and schema in m["content"] for m in third)


def test_tool_results_go_back_as_tool_messages():
    chat = FakeChat(tools_turn(("check_link", {"url_id": "URL_1"})), final_turn(GOOD_FINAL))
    run(chat)
    history = chat.requests[1]
    assistant = next(m for m in history if m["role"] == "assistant")
    tool_msg = next(m for m in history if m["role"] == "tool")
    assert tool_msg["tool_call_id"] == assistant["tool_calls"][0]["id"]
    assert json.loads(tool_msg["content"])["result"]["domain_age_days"] == 3


def test_answer_without_tools_is_accepted_and_plan_logged():
    legit = {**GOOD_FINAL, "plan": [], "verdict": "unsure", "confidence_words": "not sure", "evidence": [], "actions": ["ignore"]}
    res, trail = run(FakeChat(final_turn(legit)))
    assert res.verdict == c.Verdict.unsure
    assert kinds(trail) == [c.TrailKind.plan, c.TrailKind.verdict] and trail[0].finding == "Plan: no checks"


def test_fenced_json_is_read():
    res, _ = run(FakeChat(tools_turn(("check_link", {"url_id": "URL_1"})), final_turn("```json\n" + json.dumps(GOOD_FINAL) + "\n```")))
    assert res.verdict == c.Verdict.likely_scam


def test_check_mode_clears_was_this_you():
    res, _ = run(FakeChat(tools_turn(("check_link", {"url_id": "URL_1"})), final_turn({**GOOD_FINAL, "was_this_you": ["txn_3"]})))
    assert res.was_this_you == []


# --- loop: re-plan -----------------------------------------------------------------------------


def test_new_tool_after_a_result_is_a_replan():
    chat = FakeChat(
        tools_turn(("check_link", {"url_id": "URL_1"})),
        tools_turn(("nessie_recent_activity", {"days": 7}), reasoning="The link imitates the bank, so check the account."),
        final_turn(GOOD_FINAL),
    )
    res, trail = run(chat)
    assert kinds(trail) == [c.TrailKind.plan, c.TrailKind.tool, c.TrailKind.replan, c.TrailKind.tool, c.TrailKind.verdict]
    assert trail[2].finding == "Added: nessie_recent_activity"
    assert trail[2].why == "The link imitates the bank, so check the account."
    assert res.replan is True
    assert c.ToolName.nessie_recent_activity in res.plan  # tools that ran are kept in the plan


# --- loop: limits -------------------------------------------------------------------------------


def test_at_most_six_tool_calls():
    chat = FakeChat(tools_turn(("match_campaign", {})), repeat_last=True)
    tools = FakeTools()
    res, trail = run(chat, tools)
    assert len(tools.called) == 6
    assert sum(t.kind == c.TrailKind.tool for t in trail) == 6
    assert res.verdict == c.Verdict.unsure  # it never gave a final answer


def test_extra_calls_in_one_turn_are_skipped_but_answered():
    many = [("check_link", {"url_id": "URL_1"})] * 8
    chat = FakeChat(tools_turn(*many), final_turn(GOOD_FINAL))
    tools = FakeTools()
    run(chat, tools)
    assert len(tools.called) == 6
    history = chat.requests[1]
    assert sum(m["role"] == "tool" for m in history) == 8  # every tool_call_id gets an answer


def test_slow_step_caps_calls_at_four():
    chat = FakeChat(tools_turn(("match_campaign", {})), repeat_last=True)
    tools = FakeTools(ms=12_000)
    run(chat, tools)
    assert len(tools.called) == 4


# --- loop: retries and failures ------------------------------------------------------------------


def test_invalid_answer_retried_once_then_accepted():
    chat = FakeChat(
        tools_turn(("check_link", {"url_id": "URL_1"}), ("check_sender", {"claimed_brand": "Capital One"})),
        final_turn({**GOOD_FINAL, "verdict": "definitely_scam"}),
        final_turn(GOOD_FINAL),
    )
    res, _ = run(chat)
    assert res.verdict == c.Verdict.likely_scam
    retry_msg = chat.requests[2][-1]
    assert retry_msg["role"] == "user" and "Invalid final result" in retry_msg["content"]


def test_invalid_answer_twice_returns_unsure_with_evidence():
    bad = final_turn({**GOOD_FINAL, "verdict": "definitely_scam"})
    chat = FakeChat(tools_turn(("check_link", {"url_id": "URL_1"})), bad, bad)
    res, trail = run(chat)
    assert res.verdict == c.Verdict.unsure and res.reason == guardrails.UNSURE_REASON
    assert [e.tool for e in res.evidence] == [c.ToolName.check_link]
    assert trail[-1].kind == c.TrailKind.verdict
    assert len(chat.requests) == 3  # tools turn, first answer, one retry: no third attempt


def test_unreadable_tool_arguments_use_the_same_single_retry():
    broken = {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
        {"id": "x", "type": "function", "function": {"name": "check_link", "arguments": "{not json"}}]}, "finish_reason": "tool_calls"}]}
    res, _ = run(FakeChat(broken, broken))
    assert res.verdict == c.Verdict.unsure


def test_nemotron_error_returns_unsure_and_never_raises():
    res, trail = run(FakeChat(ConnectionError("upstream 10.0.0.5 said no")))
    assert res.verdict == c.Verdict.unsure
    assert kinds(trail) == [c.TrailKind.plan, c.TrailKind.verdict]
    assert "10.0.0.5" not in json.dumps([t.model_dump(mode="json") for t in trail])


def test_failed_tool_is_shown_but_not_used_as_evidence():
    chat = FakeChat(
        tools_turn(("check_link", {"url_id": "URL_1"}), ("check_sender", {"claimed_brand": "Capital One"})),
        final_turn(GOOD_FINAL),
    )
    res, trail = run(chat, FakeTools(fail={"check_sender"}))
    assert trail[2].finding == "This check took too long and was skipped"
    assert [e.tool for e in res.evidence] == [c.ToolName.check_link]
    assert res.confidence_words == c.ConfidenceWords.likely  # one tool can't make it "very likely"


def test_unknown_tool_is_counted_but_not_shown():
    chat = FakeChat(tools_turn(("delete_everything", {})), tools_turn(("check_link", {"url_id": "URL_1"})), final_turn(GOOD_FINAL))
    tools = FakeTools()
    _, trail = run(chat, tools)
    assert [n for n, _ in tools.called] == ["delete_everything", "check_link"]
    assert all(t.tool != "delete_everything" for t in trail)


def test_broken_trail_writer_does_not_stop_the_check():
    def bad_writer(entry):
        raise RuntimeError("disk full")

    chat = FakeChat(tools_turn(("check_link", {"url_id": "URL_1"})), final_turn(GOOD_FINAL))
    res = loop.run_agent(INPUT, bad_writer, chat=chat, call_tool=FakeTools(), tool_schemas=[], protocol="native")
    assert res.verdict == c.Verdict.likely_scam


def test_classifier_disagreement_applied_in_the_loop():
    legit_input = INPUT.model_copy(update={"classifier": LEGIT_CLASSIFIER})
    chat = FakeChat(tools_turn(("check_link", {"url_id": "URL_1"}), ("check_sender", {"claimed_brand": "Capital One"})), final_turn(GOOD_FINAL))
    res, trail = run(chat, agent_input=legit_input)
    assert res.verdict == c.Verdict.unsure
    assert "disagreed" in trail[-1].why


def test_weak_legit_score_does_not_override_verified_evidence():
    """L15, seen live: a PayPal look-alike scam scored legit 0.65; it must not be forced to unsure."""
    weak = LEGIT_CLASSIFIER.model_copy(update={"score": 0.65, "top3": [("legit", 0.65)]})
    chat = FakeChat(tools_turn(("check_link", {"url_id": "URL_1"}), ("check_sender", {"claimed_brand": "Capital One"})), final_turn(GOOD_FINAL))
    res, _ = run(chat, agent_input=INPUT.model_copy(update={"classifier": weak}))
    assert res.verdict == c.Verdict.likely_scam
    confident = LEGIT_CLASSIFIER.model_copy(update={"score": 0.85, "top3": [("legit", 0.85)]})
    chat = FakeChat(tools_turn(("check_link", {"url_id": "URL_1"}), ("check_sender", {"claimed_brand": "Capital One"})), final_turn(GOOD_FINAL))
    res, _ = run(chat, agent_input=INPUT.model_copy(update={"classifier": confident}))
    assert res.verdict == c.Verdict.unsure  # a confident "legit" still means mixed signals


def test_runs_through_the_real_registry_and_tool():
    """Default `call_tool` and schemas: the L5 registry with A10's real check_sender (local, no network)."""
    chat = FakeChat(tools_turn(("check_sender", {"claimed_brand": "Capital One"})), final_turn({**GOOD_FINAL, "confidence_words": "likely"}))
    trail: list[c.TrailEntry] = []
    records = []
    res = loop.run_agent(INPUT, trail.append, chat=chat, protocol="native", on_call=records.append)
    assert res.verdict == c.Verdict.likely_scam
    tool_entry = next(t for t in trail if t.kind == c.TrailKind.tool)
    assert tool_entry.tool == c.ToolName.check_sender
    assert tool_entry.finding == "The sender is not one of the brand's official channels"
    assert [r.recipient for r in records] == ["check_sender"]  # privacy hook reaches the registry (L6)
    sent = json.loads(next(m for m in chat.requests[1] if m["role"] == "tool")["content"])
    assert sent["ok"] is True and sent["result"]["matches_official_channel"] is False


# --- loop: live-run findings ------------------------------------------------------------------------


def test_tool_call_written_as_text_is_run():
    """Seen live: Bolt wrote its native call syntax as content and the server left tool_calls empty."""
    chat = FakeChat(final_turn('check_sender{claimed_brand:<|"|>Capital One<|"|>}'), final_turn({**GOOD_FINAL, "confidence_words": "likely"}))
    tools = FakeTools()
    res, trail = run(chat, tools)
    assert tools.called == [("check_sender", {"claimed_brand": "Capital One"})]
    assert kinds(trail)[:2] == [c.TrailKind.plan, c.TrailKind.tool]
    history = chat.requests[1]
    assistant = next(m for m in history if m["role"] == "assistant")
    tool_msg = next(m for m in history if m["role"] == "tool")
    assert assistant["content"] == "" and tool_msg["tool_call_id"] == assistant["tool_calls"][0]["id"]
    assert [e.tool for e in res.evidence] == [c.ToolName.check_sender]


@pytest.mark.parametrize(
    "text,expected",
    [
        ('check_link{url_id:<|"|>URL_1<|"|>}', [("check_link", {"url_id": "URL_1"})]),
        ("call:match_campaign{}", [("match_campaign", {})]),
        ('check_link{"url_id": "URL_1"} check_sender{claimed_brand:<|"|>T-Mobile<|"|>}',
         [("check_link", {"url_id": "URL_1"}), ("check_sender", {"claimed_brand": "T-Mobile"})]),
        ('check_sender(claimed_brand="Capital One")', [("check_sender", {"claimed_brand": "Capital One"})]),
        ('check_link(url_id="URL_1")\nnessie_recent_activity(days=7)', [("check_link", {"url_id": "URL_1"}), ("nessie_recent_activity", {"days": 7})]),
        ("match_campaign()", [("match_campaign", {})]),
        ('check_sender(__import__("os").system("x"))', None),  # positional / non-literal: never executed
        ('check_sender(claimed_brand=open("x").read())', None),
        ('I will call check_link{url_id:<|"|>URL_1<|"|>} next.', None),  # prose around it
        ('delete_everything{confirm:<|"|>yes<|"|>}', None),  # not one of our tools
        (json.dumps(GOOD_FINAL), None),  # a final answer, not a call
        ("NONE", None),
        # L14, seen live with a 0.71 classifier score: a JSON list of {tool_name, parameters}.
        ('[{"tool_name": "check_link", "parameters": {"url_id": "URL_1"}}, {"tool_name": "nessie_recent_activity", "parameters": {"days": "7"}}]',
         [("check_link", {"url_id": "URL_1"}), ("nessie_recent_activity", {"days": "7"})]),
        ('```json\n[{"name": "check_sender", "arguments": "{\\"claimed_brand\\": \\"Capital One\\"}"}]\n```',
         [("check_sender", {"claimed_brand": "Capital One"})]),
        ('{"tool_name": "match_campaign", "parameters": {}}', [("match_campaign", {})]),
        ('[{"function": {"name": "check_link", "arguments": {"url_id": "URL_1"}}}]', [("check_link", {"url_id": "URL_1"})]),
        ('[{"tool_name": "check_link", "parameters": {}}, {"tool_name": "drop_tables", "parameters": {}}]', None),  # one unknown tool: none run
        ('[{"tool_name": "check_link", "parameters": ["URL_1"]}]', None),  # arguments must be an object
        ('[1, 2, 3]', None),
    ],
)
def test_leaked_tool_call_parser(text, expected):
    assert loop._leaked_tool_calls(text) == expected


def test_json_list_of_tool_calls_is_run_not_skipped():
    """Seen live (L14): Bolt chose four checks but wrote them as a JSON list in its text; they were dropped
    and the final answer then cited checks that never ran. Now they run like native tool calls."""
    listed = json.dumps([
        {"tool_name": "check_link", "parameters": {"url_id": "URL_1"}},
        {"tool_name": "check_sender", "parameters": {"claimed_brand": "Capital One"}},
    ])
    chat = FakeChat(final_turn(listed), final_turn({**GOOD_FINAL, "confidence_words": "likely"}))
    tools = FakeTools()
    res, trail = run(chat, tools)
    assert [n for n, _ in tools.called] == ["check_link", "check_sender"]
    assert kinds(trail)[:3] == [c.TrailKind.plan, c.TrailKind.tool, c.TrailKind.tool]
    assert not any(m.get("content") == prompts.NUDGE_TOOLS for req in chat.requests for m in req)  # no nudge needed


def test_no_checks_yet_gets_one_nudge_then_tools_run():
    chat = FakeChat(final_turn("This looks like a normal code message."), tools_turn(("check_sender", {"claimed_brand": "Capital One"})),
                    final_turn({**GOOD_FINAL, "confidence_words": "likely"}))
    tools = FakeTools()
    run(chat, tools)
    assert chat.requests[1][-1] == {"role": "user", "content": prompts.NUDGE_TOOLS}
    assert [n for n, _ in tools.called] == ["check_sender"]


def test_nudge_happens_only_once():
    legit = {**GOOD_FINAL, "plan": [], "verdict": "likely_safe", "confidence_words": "likely", "evidence": [], "actions": ["ignore"]}
    chat = FakeChat(final_turn("Looks fine to me."), final_turn("NONE"), final_turn(legit))
    res, trail = run(chat, agent_input=INPUT.model_copy(update={"classifier": LEGIT_CLASSIFIER}))
    nudges = [m for req in chat.requests for m in req if m.get("content") == prompts.NUDGE_TOOLS]
    assert len(chat.requests) == 3 and nudges  # nudge, then the final-answer request, no second nudge
    assert res.verdict == c.Verdict.likely_safe and kinds(trail) == [c.TrailKind.plan, c.TrailKind.verdict]


def test_invented_check_is_dropped_and_reason_replaced():
    """Seen live: with no tool run, the answer said "The sender was checked against the claimed brand"."""
    invented = {**GOOD_FINAL, "verdict": "unsure", "confidence_words": "not sure", "reason": "The sender was checked against the claimed brand.",
                "evidence": [{"tool": "check_sender", "finding": "The sender is an official channel for Capital One."}], "actions": ["ignore"]}
    chat = FakeChat(final_turn(invented), final_turn(invented))  # nudged once, still no tools
    res, trail = run(chat)
    assert res.evidence == [] and "checked" not in res.reason
    assert res.reason == guardrails._EMPTY_REASON[c.Verdict.unsure]
    assert "didn't run" in trail[-1].why


def test_failed_check_cited_as_evidence_is_dropped_quietly():
    """Seen live: the model listed an unavailable tool as evidence. It ran, so it isn't an invented check."""
    answer = {**GOOD_FINAL, "confidence_words": "likely", "reason": "The sender couldn't be confirmed and the bill check was unavailable.",
              "evidence": [{"tool": "check_sender", "finding": "Couldn't confirm"}, {"tool": "nessie_bill_status", "finding": "Unavailable"}]}
    chat = FakeChat(tools_turn(("check_sender", {"claimed_brand": "T-Mobile"}), ("nessie_bill_status", {"payee": "T-Mobile"})), final_turn(answer))
    res, trail = run(chat, FakeTools(fail={"nessie_bill_status"}))
    assert [e.tool for e in res.evidence] == [c.ToolName.check_sender]
    assert res.reason == answer["reason"] and "didn't run" not in (trail[-1].why or "")


def test_stripping_a_contact_is_not_shown_in_the_trail():
    dirty = result(evidence=[{"tool": "check_link", "finding": "Imitates capitalone.com"}, {"tool": "check_sender", "finding": "Not official"}])
    _, notes = guardrails.apply_guardrails(dirty, SCAM_CLASSIFIER)
    assert notes == []


@pytest.mark.parametrize(
    "result,expected",
    [
        ({"campaign_id": "camp_07", "similar_last_24h": 140}, "Matches a known scam campaign, 140 similar messages in the last 24 hours"),
        ({"campaign_id": "camp_07", "similar_last_24h": 1}, "Matches a known scam campaign, 1 similar message in the last 24 hours"),
        ({"campaign_id": "camp_07", "similar_last_24h": 0}, "Matches a known scam campaign"),  # seen live: scenario 3
        ({"campaign_id": None, "similar_last_24h": 0}, "No match with a known scam campaign"),
    ],
)
def test_campaign_summary_never_says_zero_in_24_hours(result, expected):
    call = ToolCall(name="match_campaign", args={}, ok=True, result=result)
    assert loop._summarize(c.ToolName.match_campaign, call) == expected


def test_prompt_says_unknown_channels_prove_nothing():
    assert "official_channels_known is false" in prompts.SYSTEM_PROMPT


# --- loop: JSON action protocol -----------------------------------------------------------------


def test_json_action_protocol():
    chat = FakeChat(
        json_action({"action": "call_tool", "tool": "check_link", "args": {"url_id": "URL_1"}, "why": "There is a link"}),
        json_action({"action": "call_tool", "tool": "check_sender", "args": {"claimed_brand": "Capital One"}, "why": "Claims a bank"}),
        json_action({"action": "finish", "result": GOOD_FINAL}),
    )
    tools = FakeTools()
    res, trail = run(chat, tools, protocol="json_action")
    assert res.verdict == c.Verdict.likely_scam and res.confidence_words == c.ConfidenceWords.very_likely
    assert [n for n, _ in tools.called] == ["check_link", "check_sender"]
    assert trail[0].why == "There is a link"
    # Results go back as user messages (no tool_call_id in this protocol).
    assert not any(m["role"] == "tool" for m in chat.requests[1])
    assert json.loads(chat.requests[1][-1]["content"])["tool"] == "check_link"


def test_json_action_unknown_action_is_retried():
    clean = {**GOOD_FINAL, "confidence_words": "likely", "evidence": []}  # cites no checks, so no nudge
    chat = FakeChat(json_action({"action": "dance"}), json_action({"action": "finish", "result": clean}))
    res, _ = run(chat, protocol="json_action")
    assert res.verdict == c.Verdict.likely_scam and len(chat.requests) == 2


# --- reasoning in the trail (stretch) -----------------------------------------------------------


def test_reasoning_content_becomes_the_why():
    chat = FakeChat(
        tools_turn(("check_link", {"url_id": "URL_1"}), reasoning="The message has a link that may imitate the bank."),
        final_turn(GOOD_FINAL, reasoning="Both checks point to a scam."),
    )
    _, trail = run(chat)
    assert trail[0].why == "The message has a link that may imitate the bank."
    assert trail[1].why == "The message contains a link"  # template for the rest of that turn


def test_long_reasoning_is_trimmed_and_stripped_of_contacts():
    long = "Call 1-800-555-0199 maybe. " + "word " * 200
    chat = FakeChat(tools_turn(("check_link", {"url_id": "URL_1"}), reasoning=long), final_turn(GOOD_FINAL))
    _, trail = run(chat)
    assert len(trail[0].why) <= loop.WHY_MAX_CHARS and "555" not in trail[0].why


def test_missing_reasoning_falls_back_to_templates():
    _, trail = run(FakeChat(tools_turn(("check_sender", {"claimed_brand": "Capital One"})), final_turn(GOOD_FINAL)))
    assert trail[0].why and trail[1].why == "The sender claims to be Capital One"


LIVE_STYLE_REASONING = """The user provided a bank impersonation scam text from "Capital One".
I have already performed:
1. `check_sender` for "Capital One" -> Result: Sender is not an official channel.
2. `check_link` for `URL_1` -> Result: Domain `capone-verify-alert.com` is suspicious.
3. `nessie_recent_activity` -> Result: Unavailable.

The initial checks strongly suggest this is a scam.
Since `nessie_recent_activity` is unavailable, I should check public scam reports to confirm the pattern, as per the rules ("When the other checks are inconclusive, or to confirm a known scam pattern").

I will call `public_scam_reports`."""


def test_reasoning_shows_the_decision_sentence():
    why = loop._reasoning({"reasoning_content": LIVE_STYLE_REASONING})
    assert why == "Since nessie_recent_activity is unavailable, I should check public scam reports to confirm the pattern."
    assert "`" not in why and "capone-verify-alert" not in why


def test_reasoning_drops_a_trailing_quoted_rule():
    text = 'Since the checks were unavailable, I should use public_scam_reports, as per the rule: "When the other checks are inconclusive".'
    assert loop._reasoning({"reasoning_content": text}) == "Since the checks were unavailable, I should use public_scam_reports."


def test_reasoning_drops_a_leading_tool_name():
    text = "Next steps:\n1. `public_scam_reports`: To confirm known patterns for this scam."
    assert loop._reasoning({"reasoning_content": text}) == "To confirm known patterns for this scam."


def test_verdict_why_uses_the_reasoning_of_the_done_turn():
    chat = FakeChat(
        tools_turn(("check_link", {"url_id": "URL_1"})),
        final_turn("Done checking.", reasoning="The link is a lookalike, so I have enough to conclude it is a scam."),
        final_turn({**GOOD_FINAL, "confidence_words": "likely", "evidence": [{"tool": "check_link", "finding": "Lookalike"}]}),
    )
    _, trail = run(chat)
    assert trail[-1].kind == c.TrailKind.verdict
    assert trail[-1].why == "The link is a lookalike, so I have enough to conclude it is a scam."


def test_final_instruction_says_unknown_channels_are_unconfirmed():
    assert "official_channels_known false" in prompts.FINAL_INSTRUCTION


def test_reasoning_without_a_reason_word_uses_the_last_sentence():
    assert loop._reasoning({"reasoning_content": "Looked at it. I will call check_link."}) == "I will call check_link."
    assert loop._reasoning({"reasoning_content": "   "}) is None
    assert loop._reasoning({}) is None


def test_reasoning_is_never_sent_back_to_the_model():
    chat = FakeChat(
        tools_turn(("check_link", {"url_id": "URL_1"}), reasoning="secret thoughts"),
        final_turn("done", reasoning="more thoughts"),
        final_turn(GOOD_FINAL),
    )
    run(chat)
    for request in chat.requests:
        for m in request:
            assert "reasoning_content" not in m and "secret thoughts" not in json.dumps(m)
