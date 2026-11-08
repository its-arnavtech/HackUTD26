"""Structured logging that carries `message_id` (L2).

Usage:

    import logging
    from app.logs import bind_message_id

    log = logging.getLogger(__name__)

    with bind_message_id("msg_0001"):
        log.info("tool finished", extra={"fields": {"tool": "check_link", "ms": 412}})

Every record logged inside `bind_message_id` (or during a request whose path
names a message) carries that `message_id`. The id lives in a `ContextVar`:
FastAPI's thread pool copies it automatically, but a background runner (L3)
must start work with `contextvars.copy_context().run(...)` or call
`bind_message_id` itself.

`extra={"fields": {...}}` adds structured fields to the line. Never log a key,
a raw (unredacted) message or account data: log ids, counts and timings.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

_message_id: ContextVar[str | None] = ContextVar("message_id", default=None)

# Paths that name a message: /api/messages/{id}/..., /api/privacy/{id}
_MESSAGE_PATH = re.compile(r"^/api/(?:messages|privacy)/([^/]+)")

_STD_ATTRS = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "fields"}


def current_message_id() -> str | None:
    return _message_id.get()


def set_message_id(message_id: str | None) -> None:
    """Set the message id for the rest of the current context (prefer `bind_message_id`)."""
    _message_id.set(message_id)


@contextmanager
def bind_message_id(message_id: str | None) -> Iterator[None]:
    """Every log line inside this block carries `message_id`."""
    token = _message_id.set(message_id)
    try:
        yield
    finally:
        _message_id.reset(token)


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "message_id"):
            record.message_id = _message_id.get()
        return True


def _install_record_factory() -> None:
    """Stamp `message_id` on every record when it's created, so every handler sees it."""
    previous = logging.getLogRecordFactory()
    if getattr(previous, "_sentinel", False):
        return

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = previous(*args, **kwargs)
        record.message_id = _message_id.get()
        return record

    factory._sentinel = True  # type: ignore[attr-defined]
    logging.setLogRecordFactory(factory)


_install_record_factory()


def _fields(record: logging.LogRecord) -> dict[str, Any]:
    fields = dict(getattr(record, "fields", None) or {})
    # Also accept plain `extra={...}` keys.
    for key, value in vars(record).items():
        if key not in _STD_ATTRS and key != "message_id" and not key.startswith("_"):
            fields.setdefault(key, value)
    return fields


class JsonFormatter(logging.Formatter):
    """One JSON object per line: ts, level, logger, msg, message_id, then fields."""

    def format(self, record: logging.LogRecord) -> str:
        line: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
            "message_id": getattr(record, "message_id", None),
        }
        line.update(_fields(record))
        if record.exc_info:
            line["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(line, default=str, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """Readable lines for local work: `18:40:01 INFO app.agent [msg_0001] tool finished tool=check_link`."""

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        mid = getattr(record, "message_id", None)
        extras = " ".join(f"{k}={v}" for k, v in _fields(record).items())
        line = f"{ts} {record.levelname:<5} {record.name} [{mid or '-'}] {record.getMessage()}"
        if extras:
            line += f" {extras}"
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


_HANDLER_NAME = "sentinel"


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    """Install one stdout handler on the root logger. Safe to call more than once."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        if handler.get_name() == _HANDLER_NAME:
            root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stdout)
    handler.set_name(_HANDLER_NAME)
    handler.setFormatter(JsonFormatter() if fmt == "json" else TextFormatter())
    handler.addFilter(_ContextFilter())
    root.addHandler(handler)
    root.setLevel(level.upper())
    # Keep chatty libraries quiet; never log request headers (they can carry keys).
    for noisy in ("httpx", "httpcore", "openai", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


class RequestContextMiddleware:
    """Binds `message_id` from the path for the whole request and logs one line per request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.log = logging.getLogger("app.request")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope.get("path", "")
        match = _MESSAGE_PATH.match(path)
        status = {"code": 500}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)

        start = time.perf_counter()
        with bind_message_id(match.group(1) if match else None):
            try:
                await self.app(scope, receive, send_wrapper)
            finally:
                if path != "/api/health":
                    self.log.info(
                        "request",
                        extra={
                            "fields": {
                                "method": scope.get("method"),
                                "path": path,
                                "status": status["code"],
                                "ms": round((time.perf_counter() - start) * 1000, 1),
                            }
                        },
                    )
