"""`check_request`: what the message asks you to do (L15f). Local, no network.

Real companies send one-time codes and say "never share this code". Scammers
ask you to **reply with, send, share or read back** a code, password or PIN,
because that code lets them into your account. No other tool looks at this, so
a code-theft text with no link used to end "not sure".

This reads only the redacted text the agent already has. It flags:
- a request to share a one-time code, verification code or PIN
- a request to share a password
- a request to reply to the text

and it ignores the same words when negated ("never share this code", "we will
never ask for your password"), so a genuine code message isn't flagged. It
returns the short phrases it matched (from the redacted text) as evidence.

The agent is offered this tool only when `mentions_a_request()` sees something
to check (see `agent/loop.py`), so ordinary messages get exactly the same tool
list as before.
"""

from __future__ import annotations

import re

from app.contracts import AgentInput, CheckRequestArgs, CheckRequestResult

_ASK = r"(?:reply|respond|text\s+back|send|share|provide|give|tell|read(?:\s+back)?|forward)"
_CODE = r"(?:one[\s-]*time\s+(?:pass)?code|verification\s+code|security\s+code|confirmation\s+code|otp|passcode|\d[\s-]*digit\s+code|code|pin)"
_PASSWORD = r"(?:password|passcode|login\s+details|credentials)"
_GAP = r"(?:\W+\w+){0,7}?\W+"
_NEGATION = re.compile(r"\b(?:never|not|don'?t|do\s+not|won'?t|will\s+not|no\s+one|nobody)\b[^.!?]{0,40}$", re.I)

_ASK_CODE = re.compile(rf"\b{_ASK}\b{_GAP}(?:the\s+|your\s+|this\s+)?{_CODE}\b", re.I)
_CODE_TO_US = re.compile(rf"\b{_CODE}\b{_GAP}(?:to\s+us|back\s+to\s+us|with\s+us|to\s+this\s+number|in\s+your\s+reply)\b", re.I)
_ASK_PASSWORD = re.compile(rf"\b{_ASK}\b{_GAP}(?:the\s+|your\s+)?{_PASSWORD}\b", re.I)
_ASK_REPLY = re.compile(r"\b(?:reply|respond|text\s+back)\b", re.I)
_CUE = re.compile(rf"{_CODE}|{_PASSWORD}|\breply\b|\brespond\b", re.I)


def _asked(pattern: re.Pattern[str], text: str) -> list[str]:
    """Matches that aren't negated by a "never / do not" just before them, in the same sentence."""
    found = []
    for m in pattern.finditer(text):
        if _NEGATION.search(text[max(0, m.start() - 60):m.start()]):
            continue
        found.append(" ".join(m.group(0).split())[:60])
    return found


def mentions_a_request(text_redacted: str) -> bool:
    """Cheap gate: is there anything for `check_request` to look at?"""
    return bool(_CUE.search(text_redacted or ""))


def check_request(args: CheckRequestArgs, agent_input: AgentInput) -> CheckRequestResult:
    text = agent_input.text_redacted
    code = _asked(_ASK_CODE, text) + _asked(_CODE_TO_US, text)
    password = _asked(_ASK_PASSWORD, text)
    reply = bool(_asked(_ASK_REPLY, text))
    return CheckRequestResult(
        asks_for_code=bool(code),
        asks_for_password=bool(password),
        asks_to_reply=reply,
        phrases=list(dict.fromkeys(code + password))[:3],
    )
