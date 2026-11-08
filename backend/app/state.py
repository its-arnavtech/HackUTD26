"""State store and background job runner (L3).

**Store.** SQLite holding messages, each message's current run (status, mode,
result) and its trail entries. It runs as an in-memory database: DATA_SPEC
section 5 keeps message text in memory for the session only, so nothing here
touches disk. `POST /api/demo/reset` clears it.

**Runs.** Every pipeline run of a message (the first check, then a recovery
re-plan after `/clicked`) gets a new run number. The poll route shows the
latest run only. Writes from an older run that is still finishing are dropped,
so a slow check can't overwrite the recovery result. `POST /api/demo/reset`
also bumps a demo generation. A reseeded message can reuse the same id and run
number; a job still in flight keeps the generation it started in, and its
result, trail and privacy writes are dropped once that generation is over.

**Runner.** `JobRunner.submit()` marks the message `queued`, then a worker
thread marks it `running`, calls the job, and stores the result (`done`). The
job gets a `TrailWriter` (the agent's `on_trail`), so the trail fills in while
it works and the UI's one-second poll shows it live. If the job raises, the
message still ends `done`, with an honest "we couldn't finish" result, and the
error is logged (never shown to the customer).

    store = StateStore()
    runner = JobRunner(store)
    mid = store.add_message(MessageIn(...), source=MessageSource.authored)
    runner.submit(mid, lambda message_id, msg, on_trail: run_pipeline(message_id, msg, on_trail))
    store.poll(mid)  # -> ResultPoll

**Privacy log (L6).** Each run also gets a `privacy_log.PrivacyLog`, bound
while the job runs, so tool calls and the pipeline record what every model
and tool received. Those records are kept for all runs (see `add_privacy`).
"""

from __future__ import annotations

import contextvars
import json
import logging
import sqlite3
import threading
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from app import contracts as c
from app import privacy_log
from app.auth.deps import DEMO_CUSTOMER_ID
from app.errors import ConflictError, NotFoundError
from app.logs import bind_message_id

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE messages (
    seq          INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id   TEXT    NOT NULL UNIQUE,
    sender       TEXT    NOT NULL,
    text         TEXT    NOT NULL,
    received_at  TEXT    NOT NULL,
    owner_id     TEXT    NOT NULL,
    source       TEXT    NOT NULL,
    status       TEXT    NOT NULL,
    mode         TEXT    NOT NULL,
    run          INTEGER NOT NULL DEFAULT 0,
    generation   INTEGER NOT NULL DEFAULT 0,
    result       TEXT,
    was_this_you TEXT    NOT NULL DEFAULT '[]',
    error        TEXT,
    created_at   TEXT    NOT NULL,
    updated_at   TEXT    NOT NULL
);
CREATE TABLE trail (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id  TEXT    NOT NULL REFERENCES messages(message_id) ON DELETE CASCADE,
    run         INTEGER NOT NULL,
    step        INTEGER NOT NULL,
    entry       TEXT    NOT NULL
);
CREATE INDEX trail_by_run ON trail (message_id, run, id);
CREATE TABLE privacy (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id  TEXT    NOT NULL REFERENCES messages(message_id) ON DELETE CASCADE,
    run         INTEGER NOT NULL,
    recipient   TEXT    NOT NULL,
    entry       TEXT    NOT NULL
);
CREATE INDEX privacy_by_message ON privacy (message_id, id);
CREATE TABLE redaction (
    message_id  TEXT    NOT NULL REFERENCES messages(message_id) ON DELETE CASCADE,
    run         INTEGER NOT NULL,
    redacted    TEXT    NOT NULL,
    PRIMARY KEY (message_id, run)
);
CREATE TABLE confirmations (
    message_id TEXT NOT NULL REFERENCES messages(message_id) ON DELETE CASCADE,
    run        INTEGER NOT NULL,
    ref        TEXT NOT NULL,
    was_me     INTEGER NOT NULL,
    PRIMARY KEY (message_id, run, ref)
);
"""

# Shown when a run crashes. Honest wording (POC_MVP 4.4): say what happened, don't reassure.
FAILED_REASON = "We couldn't finish checking this message. Until we can, don't tap its links or reply to it."


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


# Set by JobRunner for the worker that owns a run. Direct store calls (tests, routes
# that are not a pipeline job) leave it unset and are checked by run number only.
_write_generation: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "sentinel_write_generation", default=None
)


class StartedRun(int):
    """Run number plus the demo generation captured when the run began."""

    generation: int

    def __new__(cls, run: int, generation: int) -> "StartedRun":
        obj = super().__new__(cls, run)
        obj.generation = generation
        return obj


@contextmanager
def bound_generation(generation: int) -> Iterator[None]:
    """Bind the generation a worker may write. Other generations are rejected."""
    token = _write_generation.set(generation)
    try:
        yield
    finally:
        _write_generation.reset(token)


def failed_result(plan: list[c.ToolName] | None = None) -> c.AgentResult:
    return c.AgentResult(
        plan=plan or [],
        verdict=c.Verdict.unsure,
        confidence_words=c.ConfidenceWords.not_sure,
        reason=FAILED_REASON,
    )


@dataclass(frozen=True)
class StoredMessage:
    """A message as the pipeline needs it. `text` is the raw message: redact before anything else sees it."""

    message_id: str
    sender: str
    text: str
    received_at: datetime
    source: c.MessageSource
    status: c.JobStatus
    mode: c.AgentMode
    run: int

    def as_message_in(self) -> c.MessageIn:
        return c.MessageIn(text=self.text, sender=self.sender, received_at=self.received_at)


class StateStore:
    """Thread-safe in-memory SQLite store for messages, runs, results and trails."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._epoch = 0  # bumped by reset(); in-flight jobs keep the value they started with
        self._db = sqlite3.connect(":memory:", check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(_SCHEMA)

    # -- helpers ----------------------------------------------------------

    def _one(self, message_id: str) -> sqlite3.Row:
        row = self._db.execute("SELECT * FROM messages WHERE message_id = ?", (message_id,)).fetchone()
        if row is None:
            raise NotFoundError("Unknown message_id")
        return row

    def _tx(self):
        """`with self._tx():` runs the block in one transaction under the store lock."""
        store = self

        class _Tx:
            def __enter__(self_inner):
                store._lock.acquire()
                store._db.execute("BEGIN IMMEDIATE")

            def __exit__(self_inner, exc_type, *_):
                try:
                    store._db.execute("ROLLBACK" if exc_type else "COMMIT")
                finally:
                    store._lock.release()

        return _Tx()

    # -- messages -----------------------------------------------------------

    def add_message(
        self,
        message: c.MessageIn,
        source: c.MessageSource = c.MessageSource.authored,
        message_id: str | None = None,
        owner_id: str = DEMO_CUSTOMER_ID,
    ) -> str:
        """Store a new message (status `queued`, no run yet) and return its id (`msg_0001`, ...).

        `owner_id` is the user it belongs to (L13). With auth off every message
        belongs to the demo customer.
        """
        now = _now()
        with self._tx():
            if message_id is None:
                next_seq = self._db.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM messages").fetchone()[0]
                message_id = f"msg_{next_seq:04d}"
                while self._db.execute("SELECT 1 FROM messages WHERE message_id = ?", (message_id,)).fetchone():
                    next_seq += 1
                    message_id = f"msg_{next_seq:04d}"
            elif self._db.execute("SELECT 1 FROM messages WHERE message_id = ?", (message_id,)).fetchone():
                raise ConflictError(f"message_id {message_id} already exists")
            self._db.execute(
                "INSERT INTO messages (message_id, sender, text, received_at, owner_id, source, status, mode, generation,"
                " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    message_id,
                    message.sender,
                    message.text,
                    message.received_at.isoformat(),
                    owner_id,
                    c.MessageSource(source).value,
                    c.JobStatus.queued.value,
                    c.AgentMode.check.value,
                    self._epoch,
                    now,
                    now,
                ),
            )
        return message_id

    def get_message(self, message_id: str) -> StoredMessage:
        with self._lock:
            row = self._one(message_id)
        return StoredMessage(
            message_id=row["message_id"],
            sender=row["sender"],
            text=row["text"],
            received_at=datetime.fromisoformat(row["received_at"]),
            source=c.MessageSource(row["source"]),
            status=c.JobStatus(row["status"]),
            mode=c.AgentMode(row["mode"]),
            run=row["run"],
        )

    def has_message(self, message_id: str) -> bool:
        with self._lock:
            return self._db.execute("SELECT 1 FROM messages WHERE message_id = ?", (message_id,)).fetchone() is not None

    def owner_of(self, message_id: str) -> str:
        """The user a message belongs to (404 if unknown)."""
        with self._lock:
            return self._one(message_id)["owner_id"]

    def inbox(self, owner_id: str | None = None) -> list[c.InboxItem]:
        """Every message (or only `owner_id`'s), newest received first, with its latest verdict once done."""
        with self._lock:
            if owner_id is None:
                rows = self._db.execute("SELECT * FROM messages ORDER BY seq DESC").fetchall()
            else:
                rows = self._db.execute("SELECT * FROM messages WHERE owner_id = ? ORDER BY seq DESC", (owner_id,)).fetchall()
        rows = sorted(rows, key=lambda r: datetime.fromisoformat(r["received_at"]), reverse=True)  # stable: ties keep newest-added first
        items = []
        for row in rows:
            result = c.AgentResult.model_validate_json(row["result"]) if row["result"] else None
            items.append(
                c.InboxItem(
                    message_id=row["message_id"],
                    sender=row["sender"],
                    text=row["text"],
                    received_at=datetime.fromisoformat(row["received_at"]),
                    status=c.JobStatus(row["status"]),
                    verdict=result.verdict if result else None,
                    confidence_words=result.confidence_words if result else None,
                    source=c.MessageSource(row["source"]),
                )
            )
        return items

    # -- runs -----------------------------------------------------------------

    def start_run(self, message_id: str, mode: c.AgentMode = c.AgentMode.check) -> StartedRun:
        """Begin a new run: status `queued`, empty trail and result. Returns the run number.

        The returned int also carries `.generation`, the demo epoch this run may write.
        """
        with self._tx():
            row = self._one(message_id)
            started = StartedRun(int(row["run"]) + 1, self._epoch)
            self._db.execute(
                "UPDATE messages SET run = ?, generation = ?, mode = ?, status = ?, result = NULL,"
                " was_this_you = '[]', error = NULL, updated_at = ? WHERE message_id = ?",
                (int(started), started.generation, c.AgentMode(mode).value, c.JobStatus.queued.value, _now(), message_id),
            )
        return started

    def _current(self, message_id: str, run: int) -> bool:
        """True when `run` is still the message's run in the worker's demo generation."""
        row = self._one(message_id)
        if int(row["run"]) != int(run):
            return False
        return self._generation_matches(row)

    def _generation_matches(self, row: sqlite3.Row) -> bool:
        """Privacy keeps superseded runs. It only rejects a demo reset's new generation.

        Callers outside a job leave the generation unset, so existing direct writes stay valid.
        """
        generation = _write_generation.get()
        return generation is None or int(row["generation"]) == generation

    def set_running(self, message_id: str, run: int) -> bool:
        return self._update(message_id, run, status=c.JobStatus.running.value)

    def append_trail(self, message_id: str, run: int, entry: c.TrailEntry) -> bool:
        """Add one trail entry to `run`. Returns False (and drops it) if a newer run has started."""
        with self._tx():
            if not self._current(message_id, run):
                return False
            self._db.execute(
                "INSERT INTO trail (message_id, run, step, entry) VALUES (?, ?, ?, ?)",
                (message_id, run, entry.step, entry.model_dump_json()),
            )
            self._db.execute("UPDATE messages SET updated_at = ? WHERE message_id = ?", (_now(), message_id))
        return True

    def set_was_this_you(self, message_id: str, run: int, items: list[c.WasThisYouItem]) -> bool:
        """App-side details for flagged refs (L11). Shown only to the customer, never sent to a model."""
        return self._update(message_id, run, was_this_you=json.dumps([i.model_dump(mode="json") for i in items]))

    def finish(self, message_id: str, run: int, result: c.AgentResult, error: str | None = None) -> bool:
        """Store the final result and mark the run `done`."""
        return self._update(
            message_id, run, status=c.JobStatus.done.value, result=result.model_dump_json(), error=error
        )

    def _update(self, message_id: str, run: int, **fields: Any) -> bool:
        with self._tx():
            if not self._current(message_id, run):
                return False
            fields["updated_at"] = _now()
            cols = ", ".join(f"{k} = ?" for k in fields)
            self._db.execute(f"UPDATE messages SET {cols} WHERE message_id = ?", (*fields.values(), message_id))
        return True

    # -- reads for the API -----------------------------------------------------

    def trail(self, message_id: str, run: int | None = None) -> list[c.TrailEntry]:
        with self._lock:
            run = self._one(message_id)["run"] if run is None else run
            rows = self._db.execute(
                "SELECT entry FROM trail WHERE message_id = ? AND run = ? ORDER BY id", (message_id, run)
            ).fetchall()
        return [c.TrailEntry.model_validate_json(r["entry"]) for r in rows]

    def poll(self, message_id: str) -> c.ResultPoll:
        """What `GET /api/messages/{id}/result` returns: status, mode, the trail so far, and the result once done."""
        with self._lock:
            row = self._one(message_id)
            trail = self.trail(message_id, row["run"])
        return c.ResultPoll(
            message_id=message_id,
            status=c.JobStatus(row["status"]),
            mode=c.AgentMode(row["mode"]),
            trail=trail,
            result=c.AgentResult.model_validate_json(row["result"]) if row["result"] else None,
            was_this_you_items=[c.WasThisYouItem.model_validate(i) for i in json.loads(row["was_this_you"])],
        )

    # -- customer confirmations (L11) -----------------------------------------
    def confirm_transaction(self, ref: str, was_me: bool, owner_id: str | None = None) -> c.ConfirmResponse:
        """Record a tap only for an item shown in a completed, current recovery run (of `owner_id`'s messages, if given)."""
        with self._tx():
            rows = self._db.execute(
                "SELECT message_id, run, was_this_you, owner_id FROM messages WHERE mode = ? AND status = ? ORDER BY seq DESC",
                (c.AgentMode.recovery.value, c.JobStatus.done.value),
            ).fetchall()
            if owner_id is not None:
                rows = [r for r in rows if r["owner_id"] == owner_id]
            for row in rows:
                if any(item["ref"] == ref for item in json.loads(row["was_this_you"])):
                    self._db.execute(
                        "INSERT OR REPLACE INTO confirmations (message_id, run, ref, was_me) VALUES (?, ?, ?, ?)",
                        (row["message_id"], row["run"], ref, int(was_me)),
                    )
                    return c.ConfirmResponse(ref=ref, was_me=was_me, recorded=True)
        raise NotFoundError("This activity is not part of a completed recovery check")

    # -- privacy log (L6) ------------------------------------------------------
    #
    # Unlike the trail, privacy records are kept for every run, including a run
    # that a newer one superseded: the data really was sent, so the audit log
    # shows it. `app.privacy_log` writes these and builds the API view.

    def add_privacy(self, message_id: str, run: int, recipient: c.PrivacyRecipient) -> int:
        with self._tx():
            if not self._generation_matches(self._one(message_id)):
                return 0
            cur = self._db.execute(
                "INSERT INTO privacy (message_id, run, recipient, entry) VALUES (?, ?, ?, ?)",
                (message_id, run, recipient.recipient, recipient.model_dump_json()),
            )
        return int(cur.lastrowid)

    def update_privacy(self, entry_id: int, recipient: c.PrivacyRecipient) -> None:
        with self._tx():
            row = self._db.execute("SELECT message_id, run FROM privacy WHERE id = ?", (entry_id,)).fetchone()
            # id can be reused after reset clears sqlite_sequence, so a new generation must not be overwritten
            if row is None or not self._generation_matches(self._one(row["message_id"])):
                return
            self._db.execute("UPDATE privacy SET entry = ? WHERE id = ?", (recipient.model_dump_json(), entry_id))

    def last_privacy(self, message_id: str, run: int, recipient: str) -> tuple[int, Optional[c.PrivacyRecipient]]:
        """The latest record for `recipient` in `run`, as (id, record), or (0, None)."""
        with self._lock:
            row = self._db.execute(
                "SELECT id, entry FROM privacy WHERE message_id = ? AND run = ? AND recipient = ? ORDER BY id DESC LIMIT 1",
                (message_id, run, recipient),
            ).fetchone()
        return (row["id"], c.PrivacyRecipient.model_validate_json(row["entry"])) if row else (0, None)

    def privacy(self, message_id: str) -> list[c.PrivacyRecipient]:
        """Every recipient record for the message, all runs, in the order they were recorded."""
        with self._lock:
            self._one(message_id)
            rows = self._db.execute("SELECT entry FROM privacy WHERE message_id = ? ORDER BY id", (message_id,)).fetchall()
        return [c.PrivacyRecipient.model_validate_json(r["entry"]) for r in rows]

    def set_redaction(self, message_id: str, run: int, redacted: c.RedactedMessage) -> None:
        """The redaction step's output for `run`. Kept in memory only; the API shows just its report."""
        with self._tx():
            if not self._generation_matches(self._one(message_id)):
                return
            self._db.execute(
                "INSERT OR REPLACE INTO redaction (message_id, run, redacted) VALUES (?, ?, ?)",
                (message_id, run, redacted.model_dump_json()),
            )

    def redaction(self, message_id: str) -> Optional[c.RedactedMessage]:
        """The latest run's redaction output, if the pipeline recorded one."""
        with self._lock:
            row = self._db.execute(
                "SELECT redacted FROM redaction WHERE message_id = ? ORDER BY run DESC LIMIT 1", (message_id,)
            ).fetchone()
        return c.RedactedMessage.model_validate_json(row["redacted"]) if row else None

    def error(self, message_id: str) -> Optional[str]:
        """The last run's internal error, for logs and tests only (never sent to the UI)."""
        with self._lock:
            return self._one(message_id)["error"]

    def reset(self) -> None:
        with self._tx():
            self._epoch += 1
            self._db.execute("DELETE FROM trail")
            self._db.execute("DELETE FROM privacy")
            self._db.execute("DELETE FROM redaction")
            self._db.execute("DELETE FROM messages")
            self._db.execute("DELETE FROM sqlite_sequence")

    def close(self) -> None:
        with self._lock:
            self._db.close()


class TrailWriter:
    """The `on_trail` callback handed to the pipeline for one run.

    Call it with a full `TrailEntry`, or use `add()` to number steps and stamp
    the time automatically:

        on_trail.add(c.TrailKind.tool, tool=c.ToolName.check_link, why="...", finding="...", ms=412)
    """

    def __init__(self, store: StateStore, message_id: str, run: int) -> None:
        self.store, self.message_id, self.run = store, message_id, run
        self._step = 0
        self._lock = threading.Lock()

    def __call__(self, entry: c.TrailEntry) -> None:
        with self._lock:
            self._step = max(self._step, entry.step)
        self.store.append_trail(self.message_id, self.run, entry)

    def add(
        self,
        kind: c.TrailKind,
        *,
        tool: c.ToolName | None = None,
        why: str | None = None,
        finding: str | None = None,
        ms: int | None = None,
    ) -> c.TrailEntry:
        with self._lock:
            self._step += 1
            step = self._step
        entry = c.TrailEntry(step=step, kind=kind, tool=tool, why=why, finding=finding, ms=ms, at=datetime.now(timezone.utc))
        self.store.append_trail(self.message_id, self.run, entry)
        return entry


# A job runs one message: (message_id, message, on_trail) -> AgentResult.
Job = Callable[[str, StoredMessage, TrailWriter], c.AgentResult]


class JobRunner:
    """Runs jobs on worker threads and records queued -> running -> done in the store."""

    def __init__(self, store: StateStore, max_workers: int = 4) -> None:
        self.store = store
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="sentinel-job")

    def submit(self, message_id: str, job: Job, mode: c.AgentMode = c.AgentMode.check) -> Future[None]:
        """Start a new run of `message_id` in the background and return at once."""
        started = self.store.start_run(message_id, mode)
        run, generation = int(started), started.generation
        with bind_message_id(message_id):
            log.info("job queued", extra={"fields": {"run": run, "generation": generation, "mode": c.AgentMode(mode).value}})
        ctx = contextvars.copy_context()  # keep request context (and anything bound) in the worker
        return self._pool.submit(ctx.run, self._run, message_id, run, generation, job)

    def _run(self, message_id: str, run: int, generation: int, job: Job) -> None:
        with bind_message_id(message_id):
            try:
                with bound_generation(generation):
                    self._run_inner(message_id, run, job)
            except NotFoundError:
                # The demo was reset while this job ran: its message is gone, nothing to record.
                log.info("job dropped: message no longer exists", extra={"fields": {"run": run, "generation": generation}})

    def _run_inner(self, message_id: str, run: int, job: Job) -> None:
        if not self.store.set_running(message_id, run):
            log.info("job superseded before start", extra={"fields": {"run": run}})
            return
        log.info("job running", extra={"fields": {"run": run}})
        try:
            message = self.store.get_message(message_id)
            # The run's privacy log (L6): the registry and pipeline record into it while the job runs.
            with privacy_log.bind(privacy_log.PrivacyLog(self.store, message_id, run)):
                result = job(message_id, message, TrailWriter(self.store, message_id, run))
            if not isinstance(result, c.AgentResult):
                raise TypeError(f"job returned {type(result).__name__}, expected AgentResult")
            if message.mode == c.AgentMode.recovery and result.was_this_you:
                # Resolve locally after the agent ends. Names and exact banking
                # details never enter a Nemotron message or its privacy record.
                from app.tools.nessie_tools import resolve_ref

                items = [resolve_ref(ref) for ref in result.was_this_you]
                self.store.set_was_this_you(message_id, run, items)
            if not self.store.finish(message_id, run, result):
                log.info("job dropped: run is no longer current", extra={"fields": {"run": run}})
                return
            log.info("job done", extra={"fields": {"run": run, "verdict": result.verdict.value}})
        except NotFoundError:
            raise
        except Exception as exc:  # the run must always end `done`, or the UI polls forever
            log.exception("job failed", extra={"fields": {"run": run, "error_type": type(exc).__name__}})
            self.store.finish(message_id, run, failed_result(), error=f"{type(exc).__name__}: {exc}")

    def shutdown(self, wait: bool = True) -> None:
        self._pool.shutdown(wait=wait, cancel_futures=not wait)
