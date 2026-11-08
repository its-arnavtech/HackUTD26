"""Settings read from the environment and the repo-root `.env` (L2).

- `load_settings()` reads settings and turns pydantic's errors into one clear
  `SettingsError` (bad `DEMO_MODE`, a port that isn't a number, an unknown
  route name in `MOCK_ROUTES`, ...).
- `check_settings()` lists problems that depend on the mode: a missing key is an
  error only when something will actually call that service, otherwise a warning.
- `integration_modes()` says how each outside service will behave (`/api/health`).
- `Settings.route_is_mocked()` switches mocks per route.

Never log or print a key: the secret fields use `SecretStr`, and nothing here
puts a secret's value in a message.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.contracts import DemoMode

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
DATA_DIR = REPO_ROOT / "data"
EVAL_DIR = REPO_ROOT / "eval"

# Route names used by MOCK_ROUTES and LIVE_ROUTES (one per route in POC_MVP.md 7.1).
ROUTES: tuple[str, ...] = (
    "inbox",
    "post_message",
    "result",
    "clicked",
    "confirm",
    "actions",
    "privacy",
    "campaigns",
    "metrics",
    "demo_reset",
)

IntegrationMode = Literal["mock", "live", "record", "replay", "disabled"]


class SettingsError(RuntimeError):
    """Settings are invalid. The message lists every problem and how to fix it."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # NVIDIA Nemotron (OpenAI-compatible API)
    NVIDIA_API_KEY: SecretStr | None = None
    NEMOTRON_BASE_URL: str = "https://integrate.api.nvidia.com/v1"
    NEMOTRON_MODEL: str = "nvidia/nemotron-3.5-bolt-e4b"
    NEMOTRON_EMBED_MODEL: str = ""

    # DeepSeek: offline dataset generation only (A21). Never sees a customer message.
    DEEPSEEK_API_KEY: SecretStr | None = None
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    DEEPSEEK_MODEL: str = ""

    # Google Gemini with Search grounding
    GEMINI_API_KEY: SecretStr | None = None
    GEMINI_MODEL: str = ""

    # Capital One Nessie
    NESSIE_API_KEY: SecretStr | None = None
    NESSIE_BASE_URL: str = "http://api.nessieisreal.com"

    # Hugging Face
    HF_TOKEN: SecretStr | None = None

    # Runtime
    DEMO_MODE: DemoMode = DemoMode.live
    USE_MOCKS: bool = True
    # Comma-separated route names (see ROUTES). MOCK_ROUTES stay mocked even when
    # USE_MOCKS=false; LIVE_ROUTES use the real code even when USE_MOCKS=true.
    MOCK_ROUTES: str = ""
    LIVE_ROUTES: str = ""
    PHONE_HASH_SALT: SecretStr | None = None
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    LOG_FORMAT: Literal["json", "text"] = "json"
    API_PORT: int = 8000
    WEB_PORT: int = 5173

    @field_validator("NVIDIA_API_KEY", "DEEPSEEK_API_KEY", "GEMINI_API_KEY", "NESSIE_API_KEY", "HF_TOKEN", "PHONE_HASH_SALT", mode="before")
    @classmethod
    def _blank_secret_is_none(cls, value: object) -> object:
        # `NVIDIA_API_KEY=` in .env means "not set", not an empty key.
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("LOG_LEVEL", "LOG_FORMAT", mode="before")
    @classmethod
    def _normalise_case(cls, value: object) -> object:
        if isinstance(value, str):
            return value.upper() if value.lower() in {"debug", "info", "warning", "error"} else value.lower()
        return value

    @field_validator("MOCK_ROUTES", "LIVE_ROUTES")
    @classmethod
    def _known_routes(cls, value: str) -> str:
        unknown = [name for name in _split(value) if name not in ROUTES]
        if unknown:
            raise ValueError(f"unknown route name(s) {', '.join(unknown)}; use any of: {', '.join(ROUTES)}")
        return value

    @property
    def mock_routes(self) -> frozenset[str]:
        return frozenset(_split(self.MOCK_ROUTES))

    @property
    def live_routes(self) -> frozenset[str]:
        return frozenset(_split(self.LIVE_ROUTES))

    def route_is_mocked(self, route: str) -> bool:
        """True if `route` serves its mock. MOCK_ROUTES wins over LIVE_ROUTES, which wins over USE_MOCKS."""
        if route not in ROUTES:
            raise KeyError(f"unknown route {route!r}")
        if route in self.mock_routes:
            return True
        if route in self.live_routes:
            return False
        return self.USE_MOCKS

    @property
    def any_route_live(self) -> bool:
        return any(not self.route_is_mocked(r) for r in ROUTES)


def _split(value: str) -> list[str]:
    return [part.strip().lower() for part in value.split(",") if part.strip()]


# ---------------------------------------------------------------------------
# Loading and validation
# ---------------------------------------------------------------------------

_FIELD_HINTS = {
    "DEMO_MODE": "use live, record or replay",
    "USE_MOCKS": "use true or false",
    "API_PORT": "use a port number such as 8000",
    "WEB_PORT": "use a port number such as 5173",
    "LOG_LEVEL": "use DEBUG, INFO, WARNING or ERROR",
    "LOG_FORMAT": "use json or text",
}


def load_settings() -> Settings:
    """Read settings, raising one `SettingsError` that names every bad variable."""
    try:
        return Settings()
    except ValidationError as exc:
        lines = []
        for err in exc.errors():
            field = ".".join(str(p) for p in err.get("loc", ())) or "settings"
            hint = _FIELD_HINTS.get(field, err.get("msg", "invalid value"))
            if field in ("MOCK_ROUTES", "LIVE_ROUTES"):
                hint = str(err.get("msg", "")).removeprefix("Value error, ")
            # Never echo the bad value: it could be a key pasted into the wrong variable.
            lines.append(f"  - {field}: {hint}")
        raise SettingsError(
            "Invalid settings in .env or the environment:\n" + "\n".join(lines) + "\nSee .env.example for every variable."
        ) from None


@lru_cache
def get_settings() -> Settings:
    return load_settings()


@dataclass(frozen=True)
class SettingsIssue:
    level: Literal["error", "warning"]
    variable: str
    message: str

    def __str__(self) -> str:
        return f"{self.variable}: {self.message}"


def check_settings(s: Settings) -> list[SettingsIssue]:
    """Problems that depend on the mode. Errors stop startup; warnings are logged.

    Nothing calls an outside service while every route is mocked or in replay
    mode, so missing keys are only warnings then. Once a route runs real code in
    `live` or `record` mode, the Nemotron key is required (the agent can't run
    without it) and the other keys are warnings, because their tools return an
    error as data and the agent carries on (POC_MVP.md 7.4).
    """
    issues: list[SettingsIssue] = []
    calls_out = s.any_route_live and s.DEMO_MODE != DemoMode.replay

    def missing(var: str, why: str, required: bool) -> None:
        if getattr(s, var) is None:
            level: Literal["error", "warning"] = "error" if (required and calls_out) else "warning"
            issues.append(SettingsIssue(level, var, f"not set; {why}. Add it to .env (see .env.example)."))

    missing("NVIDIA_API_KEY", "the Nemotron agent can't run in live or record mode", required=True)
    missing("NESSIE_API_KEY", "the Nessie tools return an error instead of account activity", required=False)
    missing("GEMINI_API_KEY", "public_scam_reports is skipped until it's set (expected Sunday morning)", required=False)
    missing("PHONE_HASH_SALT", "redaction (A3) uses it to hash personal phone numbers", required=False)

    if calls_out and not s.NEMOTRON_MODEL.strip():
        issues.append(SettingsIssue("error", "NEMOTRON_MODEL", "empty; set the model ID (confirm it with GET /v1/models)."))
    if s.GEMINI_API_KEY is not None and not s.GEMINI_MODEL.strip():
        issues.append(SettingsIssue("warning", "GEMINI_MODEL", "empty while GEMINI_API_KEY is set; grounded search needs a model ID."))
    if s.API_PORT == s.WEB_PORT:
        issues.append(SettingsIssue("error", "API_PORT", f"same as WEB_PORT ({s.WEB_PORT}); give each its own port."))
    return issues


def validate_settings(s: Settings) -> list[SettingsIssue]:
    """Raise `SettingsError` if any issue is an error; return the warnings."""
    issues = check_settings(s)
    errors = [i for i in issues if i.level == "error"]
    if errors:
        raise SettingsError(
            "SentinelAI can't start with these settings:\n"
            + "\n".join(f"  - {i}" for i in errors)
            + f"\n(DEMO_MODE={s.DEMO_MODE.value}, USE_MOCKS={str(s.USE_MOCKS).lower()}; "
            "set USE_MOCKS=true or DEMO_MODE=replay to run without keys.)"
        )
    return [i for i in issues if i.level == "warning"]


# ---------------------------------------------------------------------------
# Integration modes (for /api/health and the startup log)
# ---------------------------------------------------------------------------

# integration name -> settings field holding its key (None: no key needed)
INTEGRATIONS: dict[str, str | None] = {
    "nemotron": "NVIDIA_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "nessie": "NESSIE_API_KEY",
    "rdap": None,
    "huggingface": "HF_TOKEN",
}


def integration_modes(s: Settings) -> dict[str, dict[str, object]]:
    """How each outside service behaves right now. Never includes a key's value.

    - `mock`: every route is mocked, so nothing calls it
    - `replay`: served from `data/fixtures/` only (no key needed)
    - `live` / `record`: real calls (record also saves fixtures)
    - `disabled`: real calls are needed but its key isn't set
    """
    modes: dict[str, dict[str, object]] = {}
    for name, key_field in INTEGRATIONS.items():
        configured = key_field is None or getattr(s, key_field) is not None
        mode: IntegrationMode
        if not s.any_route_live:
            mode = "mock"
        elif s.DEMO_MODE == DemoMode.replay:
            mode = "replay"
        elif not configured:
            mode = "disabled"
        else:
            mode = s.DEMO_MODE.value  # type: ignore[assignment]
        modes[name] = {"mode": mode, "configured": configured}
    return modes
