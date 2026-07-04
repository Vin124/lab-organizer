"""Env-based config. No secrets in code — everything from the environment."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)


def _flag(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    lab_root: Path
    anthropic_api_key: str | None
    auth_token: str | None
    read_only: bool
    max_children: int
    bind_host: str
    bind_port: int
    rate_limit: int       # requests / 60s / client IP; 0 = disabled
    path_privacy: bool    # return paths relative to lab_root (hide absolute server paths)

    @property
    def ai_enabled(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def auth_enabled(self) -> bool:
        return bool(self.auth_token)


@lru_cache(maxsize=1)
def get_config() -> Config:
    raw_auth = os.environ.get("AUTH_TOKEN")
    if raw_auth == "":
        logger.warning("AUTH_TOKEN is set but empty — authentication is DISABLED.")
    return Config(
        lab_root=Path(os.environ.get("LAB_ROOT", "/home")).expanduser().resolve(),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
        auth_token=raw_auth or None,
        read_only=_flag("READ_ONLY"),
        max_children=int(os.environ.get("MAX_CHILDREN", "500")),
        bind_host=os.environ.get("BIND_HOST", "127.0.0.1"),
        bind_port=int(os.environ.get("BIND_PORT", "8000")),
        rate_limit=int(os.environ.get("RATE_LIMIT", "0") or "0"),
        path_privacy=_flag("PATH_PRIVACY"),
    )
