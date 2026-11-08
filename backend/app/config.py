"""Settings read from the environment and the repo-root `.env`.

L2 adds startup validation with clear messages for missing keys. Never log or
print a key: the secret fields use `SecretStr`.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.contracts import DemoMode

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
DATA_DIR = REPO_ROOT / "data"
EVAL_DIR = REPO_ROOT / "eval"


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
    PHONE_HASH_SALT: SecretStr | None = None
    API_PORT: int = 8000
    WEB_PORT: int = 5173


@lru_cache
def get_settings() -> Settings:
    return Settings()
