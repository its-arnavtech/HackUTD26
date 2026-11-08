"""FastAPI app factory and routes (POC_MVP.md section 7.1).

`create_app()` validates settings, configures structured logging, installs the
JSON error handlers and mounts the routes. The module-level `app` is what
`uvicorn app.main:app` serves.

Each route serves its mock from `app/mocks/` while `Settings.route_is_mocked()`
says so (`USE_MOCKS`, `MOCK_ROUTES`, `LIVE_ROUTES`). Otherwise (L9):

- inbox, messages, result, clicked and reset run on L3's state store and job
  runner, with `Pipeline.job` (redact, features, classify, Nemotron agent) as
  the job. The demo inbox (`data/scenarios/inbox.json`) is loaded at startup and
  on reset. A preloaded message starts its check when its result is first
  polled, so the trail fills in live when it's opened. A posted message starts
  at once.
- actions are simulated (nothing is sent) and logged; campaigns come from A12's
  store; metrics come from `eval/metrics.json` (A13, L7).
- confirm (L11) and privacy (L6) raise `NotImplementedYetError` until their
  issue lands.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Request
from pydantic import BaseModel

from app import contracts as c
from app import mocks
from app.config import DATA_DIR, REPO_ROOT, ROUTES, Settings, get_settings, integration_modes, validate_settings
from app.errors import ErrorResponse, NotFoundError, NotImplementedYetError, install_error_handlers
from app.logs import RequestContextMiddleware, bind_message_id, configure_logging
from app.pipeline import Pipeline
from app.state import JobRunner, StateStore

INBOX_SEED = DATA_DIR / "scenarios" / "inbox.json"
METRICS_PATH = REPO_ROOT / "eval" / "metrics.json"
# Routes that run the message pipeline when they aren't mocked.
PIPELINE_ROUTES = ("post_message", "result", "clicked")

VERSION = "0.1.0"
log = logging.getLogger("app.main")


def current_settings(request: Request) -> Settings:
    """The settings this app was created with (dependency for routes)."""
    return request.app.state.settings


def current_store(request: Request) -> StateStore:
    return request.app.state.store


def current_runner(request: Request) -> JobRunner:
    return request.app.state.runner


def current_pipeline(request: Request) -> Pipeline:
    return request.app.state.pipeline


SettingsDep = Annotated[Settings, Depends(current_settings)]
StoreDep = Annotated[StateStore, Depends(current_store)]
RunnerDep = Annotated[JobRunner, Depends(current_runner)]
PipelineDep = Annotated[Pipeline, Depends(current_pipeline)]


# ---------------------------------------------------------------------------
# Demo inbox (L9)
# ---------------------------------------------------------------------------


def seed_inbox(store: StateStore, path: Path = INBOX_SEED) -> int:
    """Load the demo inbox into the store (status `queued`, not checked yet). Returns how many were added."""
    seed = json.loads(path.read_text(encoding="utf-8"))
    added = 0
    for entry in seed["messages"]:
        if "scenario" in entry:
            scenario = json.loads((path.parent / f"scenario_{entry['scenario']}.json").read_text(encoding="utf-8"))
            message = c.MessageIn.model_validate(scenario["message"])
        else:
            message = c.MessageIn.model_validate(entry["message"])
        if store.has_message(entry["message_id"]):
            continue
        store.add_message(message, c.MessageSource(entry.get("source", "scenario")), message_id=entry["message_id"])
        added += 1
    log.info("demo inbox loaded", extra={"fields": {"added": added}})
    return added


def start_if_new(request: Request, message_id: str) -> None:
    """Start a message's first check, exactly once, even with several pollers (404 if unknown)."""
    store: StateStore = request.app.state.store
    with request.app.state.start_lock:
        if store.get_message(message_id).run == 0:  # never checked; submit() starts run 1 before we let go
            request.app.state.runner.submit(message_id, request.app.state.pipeline.job)
            log.info("check started on first open")


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


def _require_mock(settings: Settings, route: str, issue: str = "L9") -> None:
    """Serve the mock for `route`, or say which issue wires the real version."""
    if not settings.route_is_mocked(route):
        raise NotImplementedYetError(issue, f"the real {route} route")


def _inbox_items() -> list[c.InboxItem]:
    return [*mocks.load("inbox.json"), *_posted]


def _known(message_id: str) -> None:
    if message_id not in _result_key:
        raise NotFoundError("Unknown message_id")


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
# Health
# ---------------------------------------------------------------------------


class IntegrationStatus(BaseModel):
    mode: str
    configured: bool


class HealthResponse(BaseModel):
    status: str
    version: str
    demo_mode: c.DemoMode
    use_mocks: bool
    integrations: dict[str, IntegrationStatus]
    mocked_routes: dict[str, bool]
    warnings: list[str]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api", responses={404: {"model": ErrorResponse}, 501: {"model": ErrorResponse}})


@router.get("/health", response_model=HealthResponse)
def get_health(request: Request, settings: SettingsDep) -> HealthResponse:
    """Liveness plus how each integration and route behaves. Never shows a key."""
    return HealthResponse(
        status="ok",
        version=VERSION,
        demo_mode=settings.DEMO_MODE,
        use_mocks=settings.USE_MOCKS,
        integrations={k: IntegrationStatus(**v) for k, v in integration_modes(settings).items()},  # type: ignore[arg-type]
        mocked_routes={r: settings.route_is_mocked(r) for r in ROUTES},
        warnings=[str(w) for w in request.app.state.settings_warnings],
    )


@router.get("/inbox", response_model=list[c.InboxItem])
def get_inbox(settings: SettingsDep, store: StoreDep) -> list[c.InboxItem]:
    """Messages in the demo inbox with their status."""
    if not settings.route_is_mocked("inbox"):
        return store.inbox()
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


@router.post("/messages", response_model=c.PostMessageResponse)
def post_message(
    body: c.MessageIn, settings: SettingsDep, store: StoreDep, runner: RunnerDep, pipeline: PipelineDep
) -> c.PostMessageResponse:
    """Simulate a message arriving and start the pipeline in the background."""
    if not settings.route_is_mocked("post_message"):
        message_id = store.add_message(body, source=c.MessageSource.authored)
        runner.submit(message_id, pipeline.job)
        return c.PostMessageResponse(message_id=message_id)
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
    log.info("message received", extra={"fields": {"new_message_id": message_id}})
    return c.PostMessageResponse(message_id=message_id)


@router.get("/messages/{message_id}/result", response_model=c.ResultPoll)
def get_result(message_id: str, request: Request, settings: SettingsDep, store: StoreDep) -> c.ResultPoll:
    """Poll every second. The trail grows as the agent works, until `done`.

    A preloaded message that was never checked starts its check on this first poll.
    """
    if not settings.route_is_mocked("result"):
        start_if_new(request, message_id)
        return store.poll(message_id)
    _known(message_id)
    return _progress(message_id, advance=True)


@router.post("/messages/{message_id}/clicked", response_model=c.ClickedResponse)
def post_clicked(
    message_id: str, settings: SettingsDep, store: StoreDep, runner: RunnerDep, pipeline: PipelineDep
) -> c.ClickedResponse:
    """Customer says they clicked. Starts the recovery re-plan (the pipeline handles recovery mode, L11)."""
    if not settings.route_is_mocked("clicked"):
        if not store.has_message(message_id):
            raise NotFoundError("Unknown message_id")
        runner.submit(message_id, pipeline.job, mode=c.AgentMode.recovery)
        return c.ClickedResponse(message_id=message_id, status=c.JobStatus.queued)
    _known(message_id)
    with _lock:
        _result_key[message_id] = "result_scenario_2.json"
        _polls[message_id] = 0
    return c.ClickedResponse(message_id=message_id, status=c.JobStatus.queued)


@router.post("/transactions/{ref}/confirm", response_model=c.ConfirmResponse)
def post_confirm(ref: str, body: c.ConfirmRequest, settings: SettingsDep) -> c.ConfirmResponse:
    """Answer to "Was this you?"."""
    _require_mock(settings, "confirm", "L11")
    return c.ConfirmResponse(ref=ref, was_me=body.was_me, recorded=True)


@router.post("/actions", response_model=c.ActionResponse)
def post_action(body: c.ActionRequest, settings: SettingsDep, store: StoreDep) -> c.ActionResponse:
    """Simulated block, report or alert. Only called after a customer tap; nothing is ever sent."""
    if not settings.route_is_mocked("actions"):
        if not store.has_message(body.message_id):
            raise NotFoundError("Unknown message_id")
        with bind_message_id(body.message_id):
            log.info("action tapped (simulated)", extra={"fields": {"action": body.action.value}})
    return c.ActionResponse(
        message_id=body.message_id,
        action=body.action,
        note="Simulated for the demo. Nothing was sent.",
    )


@router.get("/privacy/{message_id}", response_model=c.PrivacyView)
def get_privacy(message_id: str, settings: SettingsDep) -> c.PrivacyView:
    """What was redacted and exactly what each tool and model received (L6)."""
    _require_mock(settings, "privacy", "L6")
    _known(message_id)
    return mocks.load("privacy.json").model_copy(update={"message_id": message_id})


@router.get("/campaigns", response_model=list[c.Campaign])
def get_campaigns(request: Request, settings: SettingsDep) -> list[c.Campaign]:
    """Campaigns with counts, first seen, template and a redacted example (A12's fingerprint store)."""
    if not settings.route_is_mocked("campaigns"):
        return request.app.state.list_campaigns()
    return mocks.load("campaigns.json")


@router.get("/metrics", response_model=c.Metrics)
def get_metrics(request: Request, settings: SettingsDep) -> c.Metrics:
    """Contents of `eval/metrics.json` for the accuracy page (A13, L7)."""
    if not settings.route_is_mocked("metrics"):
        path: Path = request.app.state.metrics_path
        if not path.exists():
            raise NotFoundError("Metrics aren't generated yet: run `python -m scripts.evaluate` from backend/")
        return c.Metrics.model_validate_json(path.read_text(encoding="utf-8"))
    return mocks.load("metrics.json")


@router.post("/demo/reset", response_model=c.DemoResetResponse)
def post_demo_reset(settings: SettingsDep, store: StoreDep) -> c.DemoResetResponse:
    """Clears demo state and reloads the demo inbox."""
    if not settings.route_is_mocked("demo_reset"):
        store.reset()
        seed_inbox(store)
        return c.DemoResetResponse(ok=True, inbox_count=len(store.inbox()))
    _reset_state()
    return c.DemoResetResponse(ok=True, inbox_count=len(_inbox_items()))


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def _list_campaigns() -> list[c.Campaign]:
    from app.tools.campaign import list_campaigns

    return list_campaigns()


def create_app(
    settings: Settings | None = None,
    *,
    pipeline: Pipeline | None = None,
    list_campaigns: Callable[[], list[c.Campaign]] | None = None,
    metrics_path: Path | None = None,
) -> FastAPI:
    """Build the app. Raises `SettingsError` with a clear message if settings are invalid.

    `pipeline`, `list_campaigns` and `metrics_path` default to the real ones; tests pass fakes.
    """
    settings = settings or get_settings()
    configure_logging(settings.LOG_LEVEL, settings.LOG_FORMAT)
    warnings = validate_settings(settings)

    store = StateStore()
    runner = JobRunner(store)
    pipeline = pipeline or Pipeline()
    pipeline_live = any(not settings.route_is_mocked(r) for r in PIPELINE_ROUTES)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if pipeline_live:  # the baseline classifier takes ~36 s to train: do it before the first check
            threading.Thread(target=pipeline.warm, name="sentinel-warm", daemon=True).start()
        yield
        runner.shutdown(wait=False)
        store.close()

    app = FastAPI(title="SentinelAI", version=VERSION, lifespan=lifespan)
    app.state.settings = settings
    app.state.settings_warnings = warnings
    app.state.store = store
    app.state.runner = runner
    app.state.pipeline = pipeline
    app.state.start_lock = threading.Lock()
    app.state.list_campaigns = list_campaigns or _list_campaigns
    app.state.metrics_path = metrics_path or METRICS_PATH
    if not settings.route_is_mocked("inbox"):
        seed_inbox(store)
    install_error_handlers(app)
    app.add_middleware(RequestContextMiddleware)
    app.include_router(router)

    modes = {k: v["mode"] for k, v in integration_modes(settings).items()}
    mocked = sorted(r for r in ROUTES if settings.route_is_mocked(r))
    log.info(
        "SentinelAI starting",
        extra={"fields": {"demo_mode": settings.DEMO_MODE.value, "integrations": modes, "mocked_routes": mocked}},
    )
    for warning in warnings:
        log.warning("setting: %s", warning)
    return app


app = create_app()
