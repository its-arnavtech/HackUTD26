"""Record and replay cache (L1, POC_MVP.md 7.8).

Every external call (Nemotron, Gemini, Nessie, RDAP, Hugging Face) goes through
`cached_call`:

    from app.integrations import cache

    def get_bills(account_id):
        request = {"method": "GET", "path": f"/accounts/{account_id}/bills"}
        return cache.cached_call("nessie", request, lambda: _http_get(...))

- `DEMO_MODE=live` calls `fn` and saves nothing.
- `record` calls `fn` and saves its response to
  `data/fixtures/<service>/<key>.json`, where `key` is a hash of the request.
- `replay` never calls `fn`: it serves the saved response, or raises
  `FixtureMissingError` if that exact request was never recorded.

Rules for callers:
- `request` must hold everything that changes the response (URL or path,
  model, messages, args) and nothing secret. Never put a key or auth header in
  it; known secret names are dropped anyway, and fixtures are committed.
- Only redacted text may appear in a request (AGENTS.md section 7).
- Leave volatile values (timestamps, request ids) out of `request`, or list
  their top-level names in `volatile` so they don't change the key.
- `fn` must return JSON-friendly data (dict, list, str, numbers) or a pydantic
  model. Pass `decode=` to rebuild a typed value on replay, e.g.
  `decode=GeminiOutput.model_validate`.
- Errors raised by `fn` propagate and are never recorded.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import is_dataclass, asdict
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from app.config import DATA_DIR
from app.contracts import DemoMode

FIXTURES_DIR = DATA_DIR / "fixtures"
FIXTURE_VERSION = 1

T = TypeVar("T")
log = logging.getLogger(__name__)

# Never hashed or saved, at any depth (compared case-insensitively).
SECRET_FIELDS = frozenset(
    {"api_key", "apikey", "key", "token", "access_token", "authorization", "headers", "password", "secret", "hf_token"}
)


class FixtureMissingError(LookupError):
    """Replay mode found no recorded response for this request."""

    def __init__(self, service: str, key: str, path: Path):
        self.service, self.key, self.path = service, key, path
        super().__init__(
            f"No recorded {service} response for this request (key {key}). "
            f"Record it with DEMO_MODE=record, or switch to DEMO_MODE=live. Looked for {path}"
        )


class FixtureCorruptError(ValueError):
    """A fixture file exists but can't be read."""


# ---------------------------------------------------------------------------
# Keys
# ---------------------------------------------------------------------------


def _jsonable(value: Any, drop_secrets: bool = False) -> Any:
    """Turn a request or response into plain JSON types. Requests also drop secret fields."""
    if isinstance(value, BaseModel):
        return _jsonable(value.model_dump(mode="json"), drop_secrets)
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value), drop_secrets)
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v, drop_secrets) for k, v in value.items() if not (drop_secrets and str(k).lower() in SECRET_FIELDS)}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v, drop_secrets) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_jsonable(v, drop_secrets) for v in value), key=lambda v: json.dumps(v, sort_keys=True))
    if isinstance(value, Enum):
        return _jsonable(value.value, drop_secrets)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return value.as_posix()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "get_secret_value"):  # SecretStr that slipped in
        return None
    raise TypeError(f"cache: can't store a value of type {type(value).__name__}; convert it to JSON types first")


def _canonical(service: str, request: Mapping[str, Any], volatile: Iterable[str] = ()) -> dict[str, Any]:
    skip = set(volatile)
    clean = _jsonable({k: v for k, v in request.items() if k not in skip}, drop_secrets=True)
    return {"service": service, "request": clean}


def request_key(service: str, request: Mapping[str, Any], volatile: Iterable[str] = ()) -> str:
    """Stable hash of a request: same service and request -> same key, whatever the dict order."""
    canonical = json.dumps(_canonical(service, request, volatile), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def fixture_path(service: str, key: str, fixtures_dir: Path | None = None) -> Path:
    if not service.replace("_", "").replace("-", "").isalnum():
        raise ValueError(f"cache: service name {service!r} must be letters, digits, '-' or '_'")
    return (fixtures_dir or FIXTURES_DIR) / service / f"{key}.json"


# ---------------------------------------------------------------------------
# Read and write
# ---------------------------------------------------------------------------


def _read(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FixtureCorruptError(f"cache: can't read fixture {path}: {exc}") from None
    if not isinstance(data, dict) or "response" not in data:
        raise FixtureCorruptError(f"cache: fixture {path} has no 'response'")
    return data


_path_locks: dict[Path, threading.Lock] = {}
_path_locks_guard = threading.Lock()


def _lock_for(path: Path) -> threading.Lock:
    with _path_locks_guard:
        return _path_locks.setdefault(path, threading.Lock())


def _replace(tmp: str, path: Path) -> None:
    # On Windows, os.replace fails with "Access is denied" while another process
    # (a reader, antivirus, an editor) briefly holds the target open. Retry a little.
    for attempt in range(10):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.02 * (attempt + 1))


def _write(path: Path, record: dict[str, Any]) -> None:
    """Atomic write: a reader never sees half a file, even with parallel requests."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    with _lock_for(path):
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
            _replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise


def _current_mode() -> DemoMode:
    from app.config import get_settings

    return get_settings().DEMO_MODE


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def cached_call(
    service: str,
    request: Mapping[str, Any],
    fn: Callable[[], T],
    *,
    mode: DemoMode | str | None = None,
    decode: Callable[[Any], T] | None = None,
    volatile: Iterable[str] = (),
    fixtures_dir: Path | None = None,
) -> T:
    """Run `fn` according to DEMO_MODE, recording or replaying its response.

    `mode` overrides `DEMO_MODE` for this call (tests, scripts). `decode` turns
    the stored JSON back into the caller's type on replay; without it replay
    returns plain JSON (dicts and lists), so a recorded pydantic model comes
    back as a dict unless you pass `decode`.
    """
    demo_mode = DemoMode(mode) if mode is not None else _current_mode()
    volatile = tuple(volatile)

    if demo_mode == DemoMode.live:
        return fn()

    key = request_key(service, request, volatile)
    path = fixture_path(service, key, fixtures_dir)

    if demo_mode == DemoMode.replay:
        if not path.exists():
            log.warning("cache miss in replay", extra={"fields": {"service": service, "key": key}})
            raise FixtureMissingError(service, key, path)
        stored = _read(path)["response"]
        log.info("cache replay", extra={"fields": {"service": service, "key": key}})
        return decode(stored) if decode else stored

    # record
    result = fn()
    _write(
        path,
        {
            "version": FIXTURE_VERSION,
            "service": service,
            "key": key,
            "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "request": _canonical(service, request, volatile)["request"],
            "response": _jsonable(result),
        },
    )
    log.info("cache recorded", extra={"fields": {"service": service, "key": key}})
    return result


def has_fixture(service: str, request: Mapping[str, Any], volatile: Iterable[str] = (), fixtures_dir: Path | None = None) -> bool:
    """True if replay mode would serve this request."""
    return fixture_path(service, request_key(service, request, volatile), fixtures_dir).exists()


def list_fixtures(service: str | None = None, fixtures_dir: Path | None = None) -> list[Path]:
    """Recorded fixture files, optionally for one service (for A19's replay check)."""
    root = fixtures_dir or FIXTURES_DIR
    pattern = f"{service}/*.json" if service else "*/*.json"
    return sorted(root.glob(pattern))
