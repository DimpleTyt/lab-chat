"""Application settings loaded from the environment / .env file."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def _str(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip()


def _bool(name: str, default: str = "0") -> bool:
    return _str(name, default).lower() in {"1", "true", "yes", "on"}


def _path(name: str, default: str) -> Path:
    raw = _str(name, default) or default
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return path


@dataclass(frozen=True)
class Settings:
    deepseek_api_key: str
    deepseek_base_url: str
    model_main: str
    model_reasoner: str
    app_secret: str
    cookie_secure: bool
    db_path: Path
    thinking: bool = False
    root: Path = ROOT

    @property
    def mock_llm(self) -> bool:
        """No key means a deterministic offline mode (used by smoke tests)."""
        return not self.deepseek_api_key

    @property
    def llm_model(self) -> str:
        """Model reported to the UI in SSE meta events."""
        return "mock" if self.mock_llm else self.model_main


settings = Settings(
    deepseek_api_key=_str("DEEPSEEK_API_KEY"),
    deepseek_base_url=(_str("DEEPSEEK_BASE_URL", "https://api.deepseek.com") or "https://api.deepseek.com").rstrip("/"),
    model_main=_str("MODEL_MAIN", "deepseek-chat") or "deepseek-chat",
    model_reasoner=_str("MODEL_REASONER"),
    app_secret=_str("APP_SECRET", "change-me") or "change-me",
    cookie_secure=_bool("COOKIE_SECURE", "0"),
    db_path=_path("DB_PATH", "data/app.db"),
    thinking=_bool("THINKING", "0"),
)
