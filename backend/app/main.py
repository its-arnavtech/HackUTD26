"""FastAPI app factory and routes (POC_MVP.md section 7.1).

`create_app()` validates settings, configures structured logging, installs the
JSON error handlers and mounts the routes. The module-level `app` is what
`uvicorn app.main:app` serves.

Each route serves its mock from `app/mocks/` while `Settings.route_is_mocked()`
says so (`USE_MOCKS`, `MOCK_ROUTES`, `LIVE_ROUTES`). Otherwise every route runs
real code:

- inbox, messages, result, clicked and reset run on L3's state store and job
  runner, with `Pipeline.job` (redact, features, classify, Nemotron agent; L9)
  as the job. The demo inbox (`data/scenarios/inbox.json`) is loaded at startup
  and on reset. A preloaded message starts its check when its result is first
  polled, so the trail fills in live when it's opened. A posted message starts
  at once.
- confirm records the "Was this you?" answer (L11); privacy is L6's
  `privacy_log.view`.
- actions are simulated (nothing is sent) and logged; campaigns come from A12's
  store; metrics come from `eval/metrics.json` (A13, L7).
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, FastAPI, Request
from pydantic import BaseModel

from app import contracts as c
from app import mocks, privacy_log
from app.config import DATA_DIR, REPO_ROOT, ROUTES, Settings, get_settings, integration_modes, validate_settings
from app.auth.deps import DEMO_CUSTOMER_ID, Principal, PrincipalDep, authorize
from app.errors import ErrorResponse, NotFoundError, install_error_handlers
from app.logs import RequestContextMiddleware, bind_message_id, configure_logging
from app import pipeline as _pipeline_module
from app.pipeline import Pipeline, pipeline_job
from app.state import JobRunner, StateStore

if TYPE_CHECKING:
    from app.auth.context import AuthContext
    from app.sms import SmsService
    from app.whatsapp import WhatsAppService

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


def current_job(request: Request) -> Callable[..., c.AgentResult]:
    """The job the runner runs: the app's `Pipeline.job`, or a job set by replacing
    `app.main.pipeline_job` before `create_app()` (how the L6 and L11 tests inject one)."""
    return request.app.state.job_override or request.app.state.pipeline.job


JobDep = Annotated[Callable[..., c.AgentResult], Depends(current_job)]


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
            request.app.state.runner.submit(message_id, current_job(request))
            log.info("check started on first open")


# ---------------------------------------------------------------------------
# MOCK: replaced by L9. In-memory demo state that simulates pipeline progress.
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_polls: dict[str, int] = {}  # message_id -> result polls served so far
_result_key: dict[str, str] = {}  # message_id -> mock file for its result
_posted: list[c.InboxItem] = []  # messages added with POST /api/messages
_mock_owner: dict[str, str] = {}  # message_id -> user id (L13); seeded mocks belong to the demo customer

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
        _mock_owner.clear()


_reset_state()


def _inbox_items() -> list[c.InboxItem]:
    return [*mocks.load("inbox.json"), *_posted]


def _known(message_id: str, principal: Principal) -> None:
    """404 for an unknown message and for another user's (L13): the two look the same."""
    if message_id not in _result_key or _mock_owner.get(message_id, DEMO_CUSTOMER_ID) != principal.user_id:
        raise NotFoundError("Unknown message_id")


def _own(store: StateStore, message_id: str, principal: Principal) -> None:
    """Ownership check (L13): another user's message answers 404, exactly like an unknown one."""
    if store.owner_of(message_id) != principal.user_id:
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
    auth_enabled: bool = False
    integrations: dict[str, IntegrationStatus]
    mocked_routes: dict[str, bool]
    warnings: list[str]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

# Every route passes `authorize` (L13): deny by default, then CSRF, session and role checks when auth is on.
router = APIRouter(
    prefix="/api",
    dependencies=[Depends(authorize)],
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        501: {"model": ErrorResponse},
    },
)


@router.get("/health", response_model=HealthResponse)
def get_health(request: Request, settings: SettingsDep) -> HealthResponse:
    """Liveness plus how each integration and route behaves. Never shows a key."""
    return HealthResponse(
        status="ok",
        version=VERSION,
        demo_mode=settings.DEMO_MODE,
        use_mocks=settings.USE_MOCKS,
        auth_enabled=settings.AUTH_ENABLED,
        integrations={k: IntegrationStatus(**v) for k, v in integration_modes(settings).items()},  # type: ignore[arg-type]
        mocked_routes={r: settings.route_is_mocked(r) for r in ROUTES},
        warnings=[str(w) for w in request.app.state.settings_warnings],
    )


@router.get("/inbox", response_model=list[c.InboxItem])
def get_inbox(settings: SettingsDep, store: StoreDep, principal: PrincipalDep) -> list[c.InboxItem]:
    """The caller's messages with their status."""
    if not settings.route_is_mocked("inbox"):
        return store.inbox(principal.user_id)
    items = []
    for item in _inbox_items():
        if _mock_owner.get(item.message_id, DEMO_CUSTOMER_ID) != principal.user_id:
            continue
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
    body: c.MessageIn, settings: SettingsDep, store: StoreDep, runner: RunnerDep, job: JobDep, principal: PrincipalDep
) -> c.PostMessageResponse:
    """Simulate a message arriving and start the pipeline in the background."""
    if not settings.route_is_mocked("post_message"):
        message_id = store.add_message(body, source=c.MessageSource.authored, owner_id=principal.user_id)
        runner.submit(message_id, job)
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
        _mock_owner[message_id] = principal.user_id
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
def get_result(
    message_id: str, request: Request, settings: SettingsDep, store: StoreDep, principal: PrincipalDep
) -> c.ResultPoll:
    """Poll every second. The trail grows as the agent works, until `done`.

    A preloaded message that was never checked starts its check on this first poll.
    """
    if not settings.route_is_mocked("result"):
        _own(store, message_id, principal)
        start_if_new(request, message_id)
        return store.poll(message_id)
    _known(message_id, principal)
    return _progress(message_id, advance=True)


@router.get("/messages/{message_id}/agent")
def get_agent_transcript(message_id: str, settings: SettingsDep, store: StoreDep, principal: PrincipalDep) -> dict:
    """L14 System view: each real Nemotron call for this message (model, latency, tools it chose, reasoning).
    Redacted data only. Empty when routes are mocked (no model runs)."""
    from app import transcript

    if not settings.route_is_mocked("result"):
        _own(store, message_id, principal)
    t = transcript.get(message_id)
    return (t.model_dump(mode="json") if t else {"message_id": message_id, "runs": []}) | {
        "model": settings.NEMOTRON_MODEL,
        "live": not settings.route_is_mocked("result"),
    }


@router.post("/messages/{message_id}/clicked", response_model=c.ClickedResponse)
def post_clicked(
    message_id: str, settings: SettingsDep, store: StoreDep, runner: RunnerDep, job: JobDep, principal: PrincipalDep
) -> c.ClickedResponse:
    """Customer says they clicked. Starts the recovery re-plan (the pipeline handles recovery mode, L11)."""
    if not settings.route_is_mocked("clicked"):
        _own(store, message_id, principal)
        runner.submit(message_id, job, mode=c.AgentMode.recovery)
        return c.ClickedResponse(message_id=message_id, status=c.JobStatus.queued)
    _known(message_id, principal)
    with _lock:
        _result_key[message_id] = "result_scenario_2.json"
        _polls[message_id] = 0
    return c.ClickedResponse(message_id=message_id, status=c.JobStatus.queued)


@router.post("/transactions/{ref}/confirm", response_model=c.ConfirmResponse)
def post_confirm(
    ref: str, body: c.ConfirmRequest, settings: SettingsDep, store: StoreDep, principal: PrincipalDep
) -> c.ConfirmResponse:
    """Answer to "Was this you?"."""
    if not settings.route_is_mocked("confirm"):
        return store.confirm_transaction(ref, body.was_me, owner_id=principal.user_id)
    return c.ConfirmResponse(ref=ref, was_me=body.was_me, recorded=True)


@router.post("/actions", response_model=c.ActionResponse)
def post_action(
    body: c.ActionRequest, settings: SettingsDep, store: StoreDep, principal: PrincipalDep
) -> c.ActionResponse:
    """Simulated block, report or alert. Only called after a customer tap; nothing is ever sent."""
    if not settings.route_is_mocked("actions"):
        _own(store, body.message_id, principal)
        with bind_message_id(body.message_id):
            log.info("action tapped (simulated)", extra={"fields": {"action": body.action.value}})
    return c.ActionResponse(
        message_id=body.message_id,
        action=body.action,
        note="Simulated for the demo. Nothing was sent.",
    )


@router.get("/privacy/{message_id}", response_model=c.PrivacyView)
def get_privacy(message_id: str, settings: SettingsDep, store: StoreDep, principal: PrincipalDep) -> c.PrivacyView:
    """What was redacted and exactly what each tool and model received (L6)."""
    if not settings.route_is_mocked("privacy"):
        _own(store, message_id, principal)
        return privacy_log.view(store, message_id)
    _known(message_id, principal)
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
def post_demo_reset(
    request: Request, settings: SettingsDep, store: StoreDep, principal: PrincipalDep
) -> c.DemoResetResponse:
    """Clears demo state and reloads the demo inbox. Admin only when auth is on."""
    if request.app.state.auth is not None:
        request.app.state.auth.store.audit.record("demo.reset", actor=principal.user_id)
    from app import transcript

    transcript.clear()
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


def _sms_service(settings: Settings) -> SmsService:
    from app.integrations.twilio import TwilioClient
    from app.sms import SmsService

    assert settings.TWILIO_AUTH_TOKEN is not None and settings.PHONE_HASH_SALT is not None
    client = TwilioClient(
        settings.TWILIO_ACCOUNT_SID,
        settings.TWILIO_AUTH_TOKEN.get_secret_value(),
        settings.TWILIO_FROM_NUMBER,
        settings.DEMO_MODE,
    )
    return SmsService(
        client=client,
        public_base_url=settings.PUBLIC_BASE_URL,
        phone_salt=settings.PHONE_HASH_SALT.get_secret_value(),
        allowed=settings.sms_allowed_numbers,
    )


def _whatsapp_service(settings: Settings) -> WhatsAppService:
    from app.integrations.whatsapp import WhatsAppClient
    from app.whatsapp import WhatsAppService

    assert settings.WHATSAPP_ACCESS_TOKEN and settings.WHATSAPP_APP_SECRET and settings.WHATSAPP_VERIFY_TOKEN
    assert settings.PHONE_HASH_SALT is not None
    client = WhatsAppClient(
        settings.WHATSAPP_ACCESS_TOKEN.get_secret_value(),
        settings.WHATSAPP_PHONE_NUMBER_ID,
        settings.WHATSAPP_GRAPH_VERSION,
        settings.DEMO_MODE,
    )
    return WhatsAppService(
        client=client,
        app_secret=settings.WHATSAPP_APP_SECRET.get_secret_value(),
        verify_token=settings.WHATSAPP_VERIFY_TOKEN.get_secret_value(),
        public_base_url=settings.PUBLIC_BASE_URL,
        phone_salt=settings.PHONE_HASH_SALT.get_secret_value(),
        allowed=frozenset(p.strip() for p in settings.WHATSAPP_ALLOWED_NUMBERS.split(",") if p.strip()),
    )


def create_app(
    settings: Settings | None = None,
    *,
    pipeline: Pipeline | None = None,
    list_campaigns: Callable[[], list[c.Campaign]] | None = None,
    metrics_path: Path | None = None,
    auth_context: AuthContext | None = None,
    sms_service: SmsService | None = None,
    whatsapp_service: WhatsAppService | None = None,
) -> FastAPI:
    """Build the app. Raises `SettingsError` with a clear message if settings are invalid.

    `pipeline`, `list_campaigns`, `metrics_path` and `auth_context` default to the real ones; tests pass fakes.
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
        if app.state.auth is not None:
            app.state.auth.close()

    app = FastAPI(title="SentinelAI", version=VERSION, lifespan=lifespan)
    app.state.settings = settings
    app.state.settings_warnings = warnings
    app.state.store = store
    app.state.runner = runner
    app.state.pipeline = pipeline
    # A replaced module-level `pipeline_job` (tests) wins over the pipeline's own job.
    app.state.job_override = pipeline_job if pipeline_job is not _pipeline_module.pipeline_job else None
    app.state.start_lock = threading.Lock()
    app.state.list_campaigns = list_campaigns or _list_campaigns
    app.state.metrics_path = metrics_path or METRICS_PATH
    if not settings.route_is_mocked("inbox"):
        seed_inbox(store)
    app.state.auth = None
    install_error_handlers(app)
    app.add_middleware(RequestContextMiddleware)
    app.include_router(router)
    if settings.AUTH_ENABLED:  # L13: sign-in routes and real sessions; off means one fixed demo customer
        from app.auth.context import AuthContext
        from app.auth.routes import router as auth_router

        app.state.auth = auth_context or AuthContext(settings)
        app.include_router(auth_router)
    app.state.sms = None
    if settings.sms_enabled:  # L14: text it, get a reply
        app.state.sms = sms_service or _sms_service(settings)
        from app.sms import router as sms_router

        app.include_router(sms_router)
    app.state.whatsapp = None
    if settings.whatsapp_enabled:  # L14: the free way to message SentinelAI from a phone
        app.state.whatsapp = whatsapp_service or _whatsapp_service(settings)
        from app.whatsapp import router as whatsapp_router

        app.include_router(whatsapp_router)

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
