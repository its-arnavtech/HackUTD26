"""Run the L8 agent loop against hosted Nemotron on three synthetic, already-redacted messages.

From backend:  python -m scripts.live_agent_check
Needs NVIDIA_API_KEY in the repo .env. Uses the real L5 registry, so tools that
aren't built yet answer "not available" and the loop carries on. Prints the
trail and verdict per case, plus whether the model returned `reasoning_content`
and whether its first turn called tools. Never prints keys or raw responses.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from app.agent import loop
from app.contracts import AgentInput, TrailEntry

CASES: dict[str, dict[str, Any]] = {
    "bank_link_scam": {
        "sender": {"type": "long_code", "value": "<PHONE_HASH_synthetic1>", "claimed_brand": "Capital One"},
        "text_redacted": "Capital One Alert: unusual sign-in for <PERSON>. Your account will be locked in 2 hours. Verify now: <URL_1>",
        "urls": [{"id": "URL_1", "registered_domain": "capone-verify-alert.com", "is_shortener": False,
                  "brand_term_in_domain": "capone", "is_official_brand_domain": False}],
        "features": {"urgency_deadline": "2 hours", "threat": "account_lock", "requested_action": "click_link_and_verify", "asks_for": ["login"]},
        "classifier": {"category": "bank_impersonation", "score": 0.94, "top3": [["bank_impersonation", 0.94]], "baseline_score": 0.81},
    },
    "bill_claim_no_link": {
        "sender": {"type": "long_code", "value": "<PHONE_HASH_synthetic2>", "claimed_brand": "T-Mobile"},
        "text_redacted": "T-Mobile: your bill is overdue. Pay <AMOUNT> today by calling us back or your service stops tonight.",
        "urls": [],
        "features": {"urgency_deadline": "tonight", "threat": "service_cutoff", "requested_action": "pay_bill", "asks_for": ["payment"]},
        "classifier": {"category": "billing_scam", "score": 0.88, "top3": [["billing_scam", 0.88]], "baseline_score": 0.7},
    },
    "legit_one_time_code": {
        "sender": {"type": "short_code", "value": "227898", "claimed_brand": "Capital One"},
        "text_redacted": "Capital One: your one-time code is <CODE>. We will never call you to ask for this code.",
        "urls": [],
        "features": {"asks_for": []},
        "classifier": {"category": "legit", "score": 0.91, "top3": [["legit", 0.91]], "baseline_score": 0.6},
    },
}


def make_input(name: str, case: dict[str, Any]) -> AgentInput:
    return AgentInput.model_validate({
        "message_id": f"live_{name}",
        "mode": "check",
        "received_at": "2026-11-08T09:14:00-06:00",
        "customer_context": {"linked_bank": True, "linked_institutions": ["Capital One"]},
        **case,
    })


class RecordingChat:
    """Wraps nemotron.chat and notes response shape only (never content)."""

    def __init__(self, debug: bool = False) -> None:
        from app.integrations import nemotron

        self._chat = nemotron.chat
        self.debug = debug
        self.turns: list[dict[str, Any]] = []

    def __call__(self, messages, tools=None, tool_choice="auto"):
        started = time.perf_counter()
        response = self._chat(messages, tools, tool_choice)
        choice = (response.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        self.turns.append({
            "ms": round((time.perf_counter() - started) * 1000),
            "finish": choice.get("finish_reason"),
            "tool_calls": len(message.get("tool_calls") or []),
            "has_reasoning_content": bool(message.get("reasoning_content")),
            "has_reasoning": bool(message.get("reasoning")),
            "message_keys": sorted(k for k, v in message.items() if v not in (None, "", [])),
        })
        if self.debug:  # synthetic inputs only, so the model's text is safe to show
            n = len(self.turns)
            if message.get("reasoning_content"):
                print(f"    [turn {n} reasoning_content]\n      {message['reasoning_content']}")
            if message.get("content"):
                print(f"    [turn {n} content]\n      {message['content']}")
        return response


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cases", nargs="*", choices=[*CASES, []], help="case names (default: all)")
    parser.add_argument("--debug", action="store_true", help="also print the model's reasoning and replies")
    args = parser.parse_args()
    chosen = {k: v for k, v in CASES.items() if not args.cases or k in args.cases}

    logging.basicConfig(level=os.environ.get("LOG_LEVEL_CHECK", "WARNING"))
    os.environ.setdefault("DEMO_MODE", "live")
    ok = 0
    for name, case in chosen.items():
        print(f"\n=== {name} ===")
        trail: list[TrailEntry] = []
        chat = RecordingChat(debug=args.debug)
        started = time.perf_counter()
        try:
            result = loop.run_agent(make_input(name, case), trail.append, chat=chat)
        except Exception as exc:  # run_agent shouldn't raise; report the type only
            print(f"  CRASH {type(exc).__name__}")
            continue
        total = round((time.perf_counter() - started) * 1000)
        for t in trail:
            tool = t.tool.value if t.tool else "-"
            print(f"  {t.step}. {t.kind.value:<7} {tool:<22} {t.ms or 0:>6}ms  finding: {t.finding}")
            print(f"     why: {t.why}")
        print(f"  RESULT {result.verdict.value} / {result.confidence_words.value} / replan={result.replan}")
        print(f"  reason: {result.reason}")
        print(f"  actions: {[a.value for a in result.actions]}  evidence tools: {[e.tool.value for e in result.evidence]}")
        print(f"  model turns: {len(chat.turns)}, total {total}ms")
        for i, turn in enumerate(chat.turns, 1):
            print(f"    turn {i}: {turn}")
        gave_answer = not (result.verdict.value == "unsure" and result.reason.startswith("We couldn't finish"))
        ok += gave_answer
        print(f"  {'ANSWERED' if gave_answer else 'FELL BACK TO UNSURE'}")
    print(f"\n{ok}/{len(chosen)} cases got a real answer from the model")
    return 0 if ok == len(chosen) else 1


if __name__ == "__main__":
    raise SystemExit(main())
