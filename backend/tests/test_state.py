"""L3: state store, job runner, trail writer, and the routes on the real store."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone

import pytest

from app import contracts as c
from app.errors import ConflictError, NotFoundError
from app.logs import current_message_id
from app.state import FAILED_REASON, JobRunner, StateStore, TrailWriter

MSG = c.MessageIn(
    text="Capital One Alert: unusual sign-in. Verify now: https://capone-verify-alert.example/verify",
    sender="+15550104477",
    received_at=datetime(2026, 11, 8, 9, 14, tzinfo=timezone.utc),
)

RESULT = c.AgentResult(
    plan=[c.ToolName.check_link, c.ToolName.check_sender],
    verdict=c.Verdict.likely_scam,
    confidence_words=c.ConfidenceWords.very_likely,
    reason="The link is not Capital One's and the sender is not an official channel.",
    evidence=[c.Evidence(tool=c.ToolName.check_link, finding="Lookalike domain")],
    actions=[c.Action.block_sender, c.Action.report_spam],
)


def entry(step: int, kind=c.TrailKind.tool, tool=c.ToolName.check_link) -> c.TrailEntry:
    return c.TrailEntry(step=step, kind=kind, tool=tool, why="why", finding="found", ms=10, at=datetime.now(timezone.utc))


def wait_done(store: StateStore, message_id: str, timeout: float = 5.0) -> c.ResultPoll:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        poll = store.poll(message_id)
        if poll.status == c.JobStatus.done:
            return poll
        time.sleep(0.01)
    raise AssertionError(f"{message_id} not done after {timeout}s: {store.poll(message_id).status}")


@pytest.fixture
def store():
    s = StateStore()
    yield s
    s.close()


@pytest.fixture
def runner(store):
    r = JobRunner(store, max_workers=2)
    yield r
    r.shutdown()


# --- store ------------------------------------------------------------------


def test_add_and_get_message(store):
    mid = store.add_message(MSG)
    assert mid == "msg_0001"
    m = store.get_message(mid)
    assert m.text == MSG.text and m.sender == MSG.sender and m.received_at == MSG.received_at
    assert m.status == c.JobStatus.queued and m.run == 0 and m.source == c.MessageSource.authored
    assert m.as_message_in() == MSG
    assert store.add_message(MSG) == "msg_0002"


def test_explicit_ids_and_duplicates(store):
    assert store.add_message(MSG, c.MessageSource.scenario, message_id="msg_0101") == "msg_0101"
    with pytest.raises(ConflictError):
        store.add_message(MSG, message_id="msg_0101")
    with pytest.raises(NotFoundError):
        store.get_message("msg_nope")


def test_store_is_in_memory_only(store):
    # DATA_SPEC 5: message text stays in memory for the session.
    db_list = store._db.execute("PRAGMA database_list").fetchall()
    assert all(row["file"] == "" for row in db_list)


def test_run_lifecycle_and_poll(store):
    mid = store.add_message(MSG)
    run = store.start_run(mid)
    assert run == 1 and store.poll(mid).status == c.JobStatus.queued
    assert store.set_running(mid, run) and store.poll(mid).status == c.JobStatus.running
    store.append_trail(mid, run, entry(1, c.TrailKind.plan, None))
    store.append_trail(mid, run, entry(2))
    poll = store.poll(mid)
    assert [t.step for t in poll.trail] == [1, 2] and poll.result is None
    assert store.finish(mid, run, RESULT)
    poll = store.poll(mid)
    assert poll.status == c.JobStatus.done and poll.result == RESULT and poll.mode == c.AgentMode.check


def test_new_run_clears_trail_and_drops_stale_writes(store):
    mid = store.add_message(MSG)
    check = store.start_run(mid)
    store.append_trail(mid, check, entry(1))
    recovery = store.start_run(mid, c.AgentMode.recovery)
    poll = store.poll(mid)
    assert poll.mode == c.AgentMode.recovery and poll.trail == [] and poll.status == c.JobStatus.queued
    # the old check run finishing late changes nothing
    assert store.append_trail(mid, check, entry(2)) is False
    assert store.finish(mid, check, RESULT) is False
    assert store.poll(mid).status == c.JobStatus.queued
    # the old trail is still there for that run
    assert len(store.trail(mid, check)) == 1 and store.trail(mid, recovery) == []


def test_was_this_you_items(store):
    mid = store.add_message(MSG)
    run = store.start_run(mid, c.AgentMode.recovery)
    item = c.WasThisYouItem(ref="txn_3", type="transfer", amount=900.0, payee="Unknown Payee", at=MSG.received_at)
    store.set_was_this_you(mid, run, [item])
    assert store.poll(mid).was_this_you_items == [item]


def test_inbox_newest_first_with_verdicts(store):
    early = store.add_message(MSG.model_copy(update={"received_at": datetime(2026, 11, 8, 8, 0, tzinfo=timezone.utc)}))
    late = store.add_message(MSG)
    run = store.start_run(late)
    store.finish(late, run, RESULT)
    inbox = store.inbox()
    assert [i.message_id for i in inbox] == [late, early]
    assert inbox[0].status == c.JobStatus.done and inbox[0].verdict == c.Verdict.likely_scam
    assert inbox[1].verdict is None


def test_inbox_orders_by_time_across_time_zones(store):
    utc_10 = store.add_message(MSG.model_copy(update={"received_at": datetime.fromisoformat("2026-11-08T10:00:00+00:00")}))
    # 09:30 in Chicago is 15:30 UTC: later, even though "09:30" < "10:00" as text
    chi = store.add_message(MSG.model_copy(update={"received_at": datetime.fromisoformat("2026-11-08T09:30:00-06:00")}))
    assert [i.message_id for i in store.inbox()] == [chi, utc_10]


def test_reset(store):
    store.add_message(MSG)
    store.reset()
    assert store.inbox() == []
    assert store.add_message(MSG) == "msg_0001"


def test_trail_writer_numbers_steps(store):
    mid = store.add_message(MSG)
    run = store.start_run(mid)
    writer = TrailWriter(store, mid, run)
    writer.add(c.TrailKind.plan, why="Check the link and the sender")
    writer(entry(2))
    third = writer.add(c.TrailKind.verdict, finding="Very likely a scam")
    assert third.step == 3
    assert [t.kind for t in store.poll(mid).trail] == [c.TrailKind.plan, c.TrailKind.tool, c.TrailKind.verdict]


# --- runner -------------------------------------------------------------------


def test_runner_goes_queued_running_done_with_live_trail(store, runner):
    mid = store.add_message(MSG)
    go = threading.Event()
    seen_running = threading.Event()

    def job(message_id, message, on_trail):
        assert message.text == MSG.text
        on_trail.add(c.TrailKind.plan, why="plan")
        seen_running.set()
        go.wait(5)
        on_trail.add(c.TrailKind.tool, tool=c.ToolName.check_link, finding="Lookalike domain", ms=5)
        return RESULT

    runner.submit(mid, job)
    assert seen_running.wait(5)
    poll = store.poll(mid)
    assert poll.status == c.JobStatus.running and len(poll.trail) == 1 and poll.result is None
    go.set()
    poll = wait_done(store, mid)
    assert poll.result == RESULT and len(poll.trail) == 2


def test_failed_job_still_ends_done_with_honest_result(store, runner):
    mid = store.add_message(MSG)

    def job(*_):
        raise RuntimeError("Nemotron timed out")

    runner.submit(mid, job)
    poll = wait_done(store, mid)
    assert poll.result.verdict == c.Verdict.unsure and poll.result.confidence_words == c.ConfidenceWords.not_sure
    assert poll.result.reason == FAILED_REASON and "fine" not in poll.result.reason
    assert "Nemotron timed out" in store.error(mid)


def test_job_returning_wrong_type_is_a_failure(store, runner):
    mid = store.add_message(MSG)
    runner.submit(mid, lambda *_: {"verdict": "likely_scam"})
    assert wait_done(store, mid).result.verdict == c.Verdict.unsure


def test_recovery_supersedes_a_running_check(store, runner):
    mid = store.add_message(MSG)
    release = threading.Event()

    def slow_check(message_id, message, on_trail):
        release.wait(5)
        on_trail.add(c.TrailKind.tool, tool=c.ToolName.check_link)
        return RESULT

    def recovery(message_id, message, on_trail):
        assert message.mode == c.AgentMode.recovery
        on_trail.add(c.TrailKind.replan, why="Customer clicked")
        return RESULT.model_copy(update={"was_this_you": ["txn_3"], "plan": [c.ToolName.nessie_recent_activity]})

    runner.submit(mid, slow_check)
    runner.submit(mid, recovery, mode=c.AgentMode.recovery)
    poll = wait_done(store, mid)
    release.set()
    time.sleep(0.1)  # let the slow check try (and fail) to write
    poll = store.poll(mid)
    assert poll.mode == c.AgentMode.recovery and poll.result.was_this_you == ["txn_3"]
    assert [t.kind for t in poll.trail] == [c.TrailKind.replan]


def test_runner_logs_carry_message_id(store, runner, caplog):
    caplog.set_level(logging.INFO, logger="app.state")
    mid = store.add_message(MSG)
    ids = []

    def job(message_id, message, on_trail):
        ids.append(current_message_id())
        return RESULT

    runner.submit(mid, job)
    wait_done(store, mid)
    assert ids == [mid]
    done = [r for r in caplog.records if r.getMessage() == "job done"]
    assert done and done[0].message_id == mid


def test_reset_while_running_drops_the_job(store, runner):
    mid = store.add_message(MSG)
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def job(message_id, message, on_trail):
        started.set()
        release.wait(5)
        try:
            return RESULT
        finally:
            finished.set()

    future = runner.submit(mid, job)
    assert started.wait(5)
    store.reset()
    release.set()
    future.result(timeout=5)  # no exception escapes the worker
    assert finished.is_set() and store.inbox() == []


def test_many_messages_in_parallel(store, runner):
    ids = [store.add_message(MSG) for _ in range(10)]
    for mid in ids:
        runner.submit(mid, lambda message_id, message, on_trail: (on_trail.add(c.TrailKind.plan), RESULT)[1])
    for mid in ids:
        poll = wait_done(store, mid)
        assert poll.result == RESULT and len(poll.trail) == 1


# --- routes on the real store (mocks off for these routes) -----------------------

LIVE = "inbox,post_message,result,clicked,demo_reset"


def test_routes_use_store_and_runner(make_client, monkeypatch):
    from app import main

    def fake_pipeline(message_id, message, on_trail):
        on_trail.add(c.TrailKind.plan, why=f"plan for {message.mode.value}")
        return RESULT

    monkeypatch.setattr(main, "pipeline_job", fake_pipeline)
    client = make_client(DEMO_MODE="replay", LIVE_ROUTES=LIVE)
    body = {"text": MSG.text, "sender": MSG.sender, "received_at": MSG.received_at.isoformat()}
    mid = client.post("/api/messages", json=body).json()["message_id"]
    assert mid == "msg_0001"

    deadline = time.monotonic() + 5
    while (poll := client.get(f"/api/messages/{mid}/result").json())["status"] != "done":
        assert time.monotonic() < deadline
        time.sleep(0.01)
    assert poll["result"]["verdict"] == "likely_scam" and poll["trail"][0]["why"] == "plan for check"
    assert client.get("/api/inbox").json()[0]["verdict"] == "likely_scam"

    r = client.post(f"/api/messages/{mid}/clicked")
    assert r.status_code == 200 and r.json()["mode"] == "recovery"
    while (poll := client.get(f"/api/messages/{mid}/result").json())["status"] != "done":
        assert time.monotonic() < deadline
        time.sleep(0.01)
    assert poll["mode"] == "recovery" and poll["trail"][0]["why"] == "plan for recovery"

    assert client.post("/api/demo/reset").json() == {"ok": True, "inbox_count": 0}
    assert client.get(f"/api/messages/{mid}/result").status_code == 404


def test_unknown_message_on_store_routes_is_404(make_client):
    client = make_client(DEMO_MODE="replay", LIVE_ROUTES=LIVE)
    assert client.get("/api/messages/msg_9999/result").json()["error"]["code"] == "not_found"
    assert client.post("/api/messages/msg_9999/clicked").status_code == 404


def test_before_l9_a_posted_message_ends_unsure(make_client):
    """Until L9 fills in run_pipeline, the real route still finishes with an honest unsure result."""
    client = make_client(DEMO_MODE="replay", LIVE_ROUTES=LIVE)
    body = {"text": "hello", "sender": "+15550100000", "received_at": "2026-11-08T10:00:00-06:00"}
    mid = client.post("/api/messages", json=body).json()["message_id"]
    deadline = time.monotonic() + 5
    while (poll := client.get(f"/api/messages/{mid}/result").json())["status"] != "done":
        assert time.monotonic() < deadline
        time.sleep(0.01)
    assert poll["result"]["verdict"] == "unsure" and poll["result"]["reason"] == FAILED_REASON
