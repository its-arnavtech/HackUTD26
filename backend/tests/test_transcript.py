"""L14 System view transcript: records real model turns, redacted, without changing the agent."""

from __future__ import annotations

import json

from app import contracts as c
from app import transcript
from app.agent import loop
from tests.test_loop import GOOD_FINAL, INPUT, FakeTools


def fake_nemotron(responses):
    replies = iter(responses)

    def chat(messages, tools=None, tool_choice="auto"):
        return {"choices": [{"message": next(replies), "finish_reason": "stop"}]}

    return chat


def test_records_text_tool_list_then_final(monkeypatch):
    from app.integrations import nemotron

    listed = json.dumps([{"tool_name": "check_link", "parameters": {"url_id": "URL_1"}}])
    final = {**GOOD_FINAL, "confidence_words": "likely", "reason": "Call 512-555-0199 now, the link is fake."}
    monkeypatch.setattr(nemotron, "chat", fake_nemotron([
        {"role": "assistant", "content": listed, "reasoning_content": "It has a link, check it."},
        {"role": "assistant", "content": json.dumps(final)},
        {"role": "assistant", "content": json.dumps(final)},
    ]))
    transcript.clear()
    chat = transcript.recording_chat("msg_t", "check", "nvidia/nemotron-3.5-bolt-e4b")
    loop.run_agent(INPUT, lambda e: None, chat=chat, call_tool=FakeTools(), tool_schemas=[{"type": "function"}] * 6)
    t = transcript.get("msg_t")
    turns = t.runs[0].turns
    assert turns[0].tool_requests[0].name == "check_link" and turns[0].requests_as_text
    assert turns[0].sent.startswith("The redacted message") and turns[0].tools_offered == 6
    assert turns[0].reasoning == "It has a link, check it."
    assert turns[1].sent == "1 tool result"
    assert any(tn.final and tn.final["verdict"] == "likely_scam" for tn in turns)
    assert "512-555-0199" not in t.model_dump_json()  # contacts stripped from kept text
    transcript.clear()
    assert transcript.get("msg_t") is None


def test_agent_endpoint_is_owner_checked_and_empty_when_mocked(client):
    r = client.get("/api/messages/msg_0001/agent")
    assert r.status_code == 200 and r.json()["runs"] == [] and r.json()["live"] is False
