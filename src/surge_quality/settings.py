"""surge-quality runtime settings, env-driven via pydantic-settings.

Source of truth for env values in production is
``/etc/surge-quality/*.env`` (600-perm, root-owned) loaded by the systemd
unit via ``EnvironmentFile=`` in PR-9. For local dev, a ``.env`` file at
the repo root is also accepted.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings.

    Naming convention: all surge-quality env vars are prefixed with
    ``SURGE_QUALITY_``. We accept a small number of standard names
    (``DATABASE_URL``, ``ANTHROPIC_API_KEY``) unprefixed for ergonomic
    parity with upstream tooling.
    """

    model_config = SettingsConfigDict(
        env_prefix="SURGE_QUALITY_",
        env_file=(".env",),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- service identity -------------------------------------------------
    service_name: str = "surge-quality"
    env: Literal["dev", "staging", "production"] = "dev"
    log_level: str = "INFO"

    # --- HTTP ------------------------------------------------------------
    host: str = "0.0.0.0"
    port: int = 9310

    # --- Postgres --------------------------------------------------------
    # Conventional unprefixed name; surge-quality user, surge_quality schema
    # on the shared surge_brain Postgres (per docs/PLAN.md §Postgres schema).
    database_url: str = Field(
        default="postgresql://surge_quality:CHANGE_ME@127.0.0.1:5432/surge_brain",
        validation_alias="DATABASE_URL",
    )
    db_schema: str = "surge_quality"
    db_pool_size: int = 5
    db_max_overflow: int = 10

    # --- Auth (Phase A static service token; SOL JWT in Phase B) ---------
    service_token: str = Field(
        default="",
        description=(
            "Static service token compared against the X-Surge-Quality-Token "
            "header. Provisioned in /etc/surge-quality/service-tokens.env. "
            "Empty string disables auth (dev only)."
        ),
    )

    # --- Hermes scoring backend (PR-3) -----------------------------------
    hermes_base_url: str = "http://surge-ai:11434"
    hermes_model: str = "hermes3:8b"
    hermes_timeout_seconds: float = 30.0

    # --- Claude reviewer (PR-5) ------------------------------------------
    anthropic_api_key: str = Field(default="", validation_alias="ANTHROPIC_API_KEY")
    anthropic_model: str = "claude-opus-4-7"
    # Score below this threshold (0-10 combined) triggers Claude review.
    claude_review_threshold: float = 5.0

    # --- Routing (PR-6) --------------------------------------------------
    similarity_threshold: float = 0.70


@lru_cache
def get_settings() -> Settings:
    """Cached singleton so we read env once per process."""
    return Settings()
