import json

import pytest

from scripts import smoke_nemotron as smoke


def response(content=None, calls=None):
    return {"choices": [{"message": {"role": "assistant", "content": content, "tool_calls": calls}}]}


def result(tools):
    return {"plan": tools, "verdict": "likely_scam", "confidence_words": "likely",
            "reason": "The claimed bill was already paid.", "evidence": [{"tool": t, "finding": "Synthetic check completed"} for t in tools],
            "actions": ["open_official_app"], "was_this_you": [], "replan": False}


@pytest.mark.parametrize("case", smoke.CASES, ids=lambda c: c.name)
@pytest.mark.parametrize("protocol", ["native", "json_action"])
def test_five_cases_dispatch_and_validate(monkeypatch, case, protocol):
    queue = []
    names = sorted(case.expected)
    for i, name in enumerate(names):
        args = {"payee": "T-Mobile"} if name == "get_bill_status" else {"domain": "billing-check.example"}
        if protocol == "native":
            queue.append(response(calls=[{"id": str(i), "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]))
        else:
            queue.append(response(json.dumps({"action": "call_tool", "tool": name, "args": args, "why": "Check the claim"})))
    final = result([smoke.ALIASES[name] for name in names])
    queue.append(response(json.dumps({"action": "finish", "result": final} if protocol == "json_action" else final)))
    transcripts = []
    def chat(messages, tools):
        transcripts.append(json.loads(json.dumps(messages)))
        return queue.pop(0)
    monkeypatch.setattr(smoke.nemotron, "chat", chat)
    outcome = smoke.run_case(case, protocol)
    assert outcome.passed and set(outcome.calls) == case.expected
    assert any("last_payment_date" in (m["content"] or "") or "domain_age_days" in (m["content"] or "") for m in transcripts[-1])


def test_fabricated_final_is_not_a_pass(monkeypatch):
    monkeypatch.setattr(smoke.nemotron, "chat", lambda *a: response(json.dumps(result(["nessie_bill_status"])) ))
    assert not smoke.run_case(smoke.CASES[0], "native").passed


def test_unknown_tool_never_dispatches(monkeypatch):
    monkeypatch.setattr(smoke.nemotron, "chat", lambda *a: response(calls=[{"id": "0", "function": {"name": "transfer_money", "arguments": "{}"}}]))
    outcome = smoke.run_case(smoke.CASES[0], "native")
    assert not outcome.passed and not outcome.calls


def test_repeated_tool_hits_limit(monkeypatch):
    monkeypatch.setattr(smoke.nemotron, "chat", lambda *a: response(calls=[{"id": "0", "function": {"name": "get_bill_status", "arguments": '{"payee":"T-Mobile"}'}}]))
    outcome = smoke.run_case(smoke.CASES[0], "native")
    assert not outcome.passed and len(outcome.calls) == 6


def test_slow_model_caps_tool_calls_at_four(monkeypatch):
    clock = iter(range(0, 1000, 11))
    monkeypatch.setattr(smoke.time, "perf_counter", lambda: next(clock))
    monkeypatch.setattr(smoke.nemotron, "chat", lambda *a: response(calls=[{"id": "0", "function": {"name": "get_bill_status", "arguments": '{"payee":"T-Mobile"}'}}]))
    outcome = smoke.run_case(smoke.CASES[0], "native")
    assert not outcome.passed and len(outcome.calls) == 4
