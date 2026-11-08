"""L15f check_request: flags requests to share a code or password, never a genuine code message."""

from __future__ import annotations

import pytest

from app import contracts as c
from app.agent import loop
from app.tools.request import check_request, mentions_a_request
from tests.test_loop import INPUT


def run(text: str) -> c.CheckRequestResult:
    return check_request(c.CheckRequestArgs(), INPUT.model_copy(update={"text_redacted": text}))


@pytest.mark.parametrize("text", [
    "Amazon: To receive your refund, reply with the 6-digit code we just texted you.",
    "Wells Fargo: Reply with the verification code we sent to confirm it was you.",
    "Hi it's me, can you read me the code that just came to your phone?",
    "Please share the one-time passcode with our agent to unlock your account.",
])
def test_code_requests_are_flagged(text):
    r = run(text)
    assert r.asks_for_code and r.phrases


@pytest.mark.parametrize("text", [
    "Capital One: Your one-time code is 481920. It expires in 10 minutes. We will never call or text to ask for this code.",
    "Chase: Never share your verification code with anyone. Your code is 112233.",
    "Your code is 4417. Do not share this code with anyone, including us.",
])
def test_genuine_code_messages_are_not_flagged(text):
    r = run(text)
    assert not r.asks_for_code and not r.asks_for_password


def test_password_and_plain_reply():
    assert run("PayPal: please send us your password to restore access").asks_for_password
    r = run("Reminder: your appointment is tomorrow at 3 PM. Reply C to confirm.")
    assert r.asks_to_reply and not r.asks_for_code


def test_tool_is_offered_only_when_the_message_asks_for_something():
    plain = INPUT.model_copy(update={"text_redacted": "Capital One Alert: unusual sign-in. Verify now: <URL_1>"})
    asks = INPUT.model_copy(update={"text_redacted": "Reply with the code we sent you."})
    names = lambda ai: {s["function"]["name"] for s in loop._schemas_for(ai)}  # noqa: E731
    assert "check_request" not in names(plain)  # same tool list as before for ordinary messages
    assert "check_request" in names(asks)
    assert not mentions_a_request("Capital One Alert: unusual sign-in. Verify now: <URL_1>")


def test_summary_wording():
    assert loop._sum_request({"asks_for_code": True}) == "It asks you to share a one-time code, which real companies never do"
    assert loop._sum_request({}) == "No request for codes or passwords"


def test_verified_code_request_turns_unsure_into_likely_scam():
    """L15f, seen live: the agent ran check_request, it found a code request, and still answered unsure."""
    from tests.test_loop import GOOD_FINAL, FakeChat, FakeTools, final_turn, tools_turn

    class Tools(FakeTools):
        def __call__(self, name, args, agent_input, on_call=None):
            if name == "check_request":
                from app.agent.registry import ToolCall

                self.called.append((name, args))
                return ToolCall(name=name, args=args, ok=True, result={"asks_for_code": True, "asks_for_password": False,
                                                            "asks_to_reply": True, "phrases": ["reply with the code"]}, ms=1)
            return super().__call__(name, args, agent_input, on_call=on_call)

    unsure = {**GOOD_FINAL, "verdict": "unsure", "confidence_words": "not sure", "evidence": [], "actions": ["ignore"]}
    ai = INPUT.model_copy(update={"text_redacted": "Amazon: reply with the 6-digit code to get your refund."})
    res = loop.run_agent(ai, lambda e: None, chat=FakeChat(tools_turn(("check_request", {})), final_turn(unsure)),
                         call_tool=Tools(), tool_schemas=[], protocol="native")
    assert res.verdict == c.Verdict.likely_scam and res.confidence_words == c.ConfidenceWords.likely
    assert any(e.tool == c.ToolName.check_request for e in res.evidence)
    assert "never" in res.reason


def test_enter_the_code_is_normal_sign_in_wording():
    assert not run("Enter this code in the Chase app to finish signing in: 551204").asks_for_code
