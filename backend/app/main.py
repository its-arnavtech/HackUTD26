"""FastAPI app and routes (POC_MVP.md section 7.1).

While `USE_MOCKS=true` every route returns mocks from `app/mocks/`.
L2 replaces this module-level app with an app factory; L9 wires every route to
the real pipeline through L3's runner.
"""

from __future__ import annotations

import threading

from fastapi import FastAPI, HTTPException

from app import contracts as c
from app import mocks
from app.config import get_settings

app = FastAPI(title="SentinelAI", version="0.1.0")


# ---------------------------------------------------------------------------
# MOCK: replaced by L9. In-memory demo state that simulates pipeline progress.
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_polls: dict[str, int] = {}  # message_id -> result polls served so far
_result_key: dict[str, str] = {}  # message_id -> mock file for its result
_posted: list[c.InboxItem] = []  # messages added with POST /api/messages

_DEFAULT_RESULT_KEYS = {
    "msg_0001": "result_scenario_1.json",
    "msg_0003": "result_scenario_3.json",
    "msg_0101": "result_legit.json",
}


def _reset_state() -> None:
    with _lock:
        _polls.clear()
        _posted.clear()
        _result_key.clear()
        _result_key.update(_DEFAULT_RESULT_KEYS)


_reset_state()


def _require_mocks(issue: str = "L9") -> None:
    if not get_settings().USE_MOCKS:
        raise HTTPException(status_code=501, detail=f"Not implemented yet: {issue} wires the real pipeline")


def _inbox_items() -> list[c.InboxItem]:
    return [*mocks.load("inbox.json"), *_posted]


def _known(message_id: str) -> None:
    if message_id not in _result_key:
        raise HTTPException(status_code=404, detail="Unknown message_id")


def _progress(message_id: str, advance: bool) -> c.ResultPoll:
    """Mock progress: queued, then running with one more trail entry per poll, then done."""
    full: c.ResultPoll = mocks.load(_result_key[message_id])
    with _lock:
        polls = _polls.get(message_id, 0)
        if advance:
            _polls[message_id] = polls + 1
    base = full.model_copy(update={"message_id": message_id})
    n = len(full.trail)
    if polls == 0:
        return base.model_copy(update={"status": c.JobStatus.queued, "trail": [], "result": None, "was_this_you_items": []})
    if polls <= n:
        return base.model_copy(update={"status": c.JobStatus.running, "trail": full.trail[:polls], "result": None, "was_this_you_items": []})
    return base


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/api/inbox", response_model=list[c.InboxItem])
def get_inbox() -> list[c.InboxItem]:
    """Messages in the demo inbox with their status."""
    _require_mocks()
    items = []
    for item in _inbox_items():
        if item.message_id in _polls:
            poll = _progress(item.message_id, advance=False)
            item = item.model_copy(
                update={
                    "status": poll.status,
                    "verdict": poll.result.verdict if poll.result else None,
                    "confidence_words": poll.result.confidence_words if poll.result else None,
                }
            )
        items.append(item)
    return items


@app.post("/api/messages", response_model=c.PostMessageResponse)
def post_message(body: c.MessageIn) -> c.PostMessageResponse:
    """Simulate a message arriving. The real version starts the pipeline in the background (L9)."""
    _require_mocks()
    with _lock:
        message_id = f"msg_{1000 + len(_posted)}"
        text = body.text.lower()
        if "bill" in text:
            key = "result_scenario_3.json"
        elif "http" in text or "verify" in text:
            key = "result_scenario_1.json"
        else:
            key = "result_legit.json"
        _result_key[message_id] = key
        _posted.append(
            c.InboxItem(
                message_id=message_id,
                sender=body.sender,
                text=body.text,
                received_at=body.received_at,
                status=c.JobStatus.queued,
                source=c.MessageSource.authored,
            )
        )
    return c.PostMessageResponse(message_id=message_id)


@app.get("/api/messages/{message_id}/result", response_model=c.ResultPoll)
def get_result(message_id: str) -> c.ResultPoll:
    """Poll every second. The trail grows by one entry per poll until `done`."""
    _require_mocks()
    _known(message_id)
    return _progress(message_id, advance=True)


@app.post("/api/messages/{message_id}/clicked", response_model=c.ClickedResponse)
def post_clicked(message_id: str) -> c.ClickedResponse:
    """Customer says they clicked. Starts the recovery re-plan (L11)."""
    _require_mocks("L11")
    _known(message_id)
    with _lock:
        _result_key[message_id] = "result_scenario_2.json"
        _polls[message_id] = 0
    return c.ClickedResponse(message_id=message_id, status=c.JobStatus.queued)


@app.post("/api/transactions/{ref}/confirm", response_model=c.ConfirmResponse)
def post_confirm(ref: str, body: c.ConfirmRequest) -> c.ConfirmResponse:
    """Answer to "Was this you?"."""
    _require_mocks("L11")
    return c.ConfirmResponse(ref=ref, was_me=body.was_me, recorded=True)


@app.post("/api/actions", response_model=c.ActionResponse)
def post_action(body: c.ActionRequest) -> c.ActionResponse:
    """Simulated block, report or alert. Only called after a customer tap."""
    _require_mocks()
    return c.ActionResponse(
        message_id=body.message_id,
        action=body.action,
        note="Simulated for the demo. Nothing was sent.",
    )


@app.get("/api/privacy/{message_id}", response_model=c.PrivacyView)
def get_privacy(message_id: str) -> c.PrivacyView:
    """What was redacted and exactly what each tool and model received (L6)."""
    _require_mocks("L6")
    _known(message_id)
    return mocks.load("privacy.json").model_copy(update={"message_id": message_id})


@app.get("/api/campaigns", response_model=list[c.Campaign])
def get_campaigns() -> list[c.Campaign]:
    """Campaigns with counts, first seen, template and a redacted example (A12)."""
    _require_mocks("A12")
    return mocks.load("campaigns.json")


@app.get("/api/metrics", response_model=c.Metrics)
def get_metrics() -> c.Metrics:
    """Contents of `eval/metrics.json` for the accuracy page (A13)."""
    _require_mocks("A13")
    return mocks.load("metrics.json")


@app.post("/api/demo/reset", response_model=c.DemoResetResponse)
def post_demo_reset() -> c.DemoResetResponse:
    """Clears demo state and reloads the inbox."""
    _require_mocks()
    _reset_state()
    return c.DemoResetResponse(ok=True, inbox_count=len(_inbox_items()))
