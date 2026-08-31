"""Runtime configuration. Environment first, sane defaults second."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path(os.environ.get("PHANTOM_DATA_DIR", ROOT / "data"))
    db_url: str = os.environ.get("PHANTOM_DB_URL", "")

    secret_key: str = os.environ.get("PHANTOM_SECRET_KEY", "")

    worker_poll_seconds: float = float(os.environ.get("PHANTOM_POLL_SECONDS", "1.0"))
    default_profiles_per_launch: int = _int("PHANTOM_DEFAULT_LIMIT", 200)
    daily_profile_cap: int = _int("PHANTOM_DAILY_CAP", 1500)
    min_delay_seconds: float = float(os.environ.get("PHANTOM_MIN_DELAY", "4"))
    max_delay_seconds: float = float(os.environ.get("PHANTOM_MAX_DELAY", "11"))
    max_execution_minutes: int = _int("PHANTOM_MAX_EXEC_MINUTES", 60)
    headless: bool = _bool("PHANTOM_HEADLESS", True)

    keep_html: bool = _bool("PHANTOM_KEEP_HTML", False)

    host: str = os.environ.get("PHANTOM_HOST", "127.0.0.1")
    port: int = _int("PHANTOM_PORT", 8000)

    api_token: str = os.environ.get("PHANTOM_API_TOKEN", "")
    allowed_origins: str = os.environ.get("PHANTOM_ALLOWED_ORIGINS", "")

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def is_loopback(self) -> bool:
        return self.host in {"127.0.0.1", "localhost", "::1"}

    @property
    def resolved_db_url(self) -> str:
        if self.db_url:
            return self.db_url
        return f"sqlite:///{self.data_dir / 'phantom.db'}"

    @property
    def screenshots_dir(self) -> Path:
        return self.data_dir / "pictures"

    @property
    def html_cache_dir(self) -> Path:
        return self.data_dir / "html-cache"


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
