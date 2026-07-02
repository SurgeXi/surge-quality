# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""settings smoke — no DB required."""

from __future__ import annotations

from surge_quality.settings import Settings


def test_defaults() -> None:
    s = Settings()
    assert s.service_name == "surge-quality"
    assert s.port == 9310
    assert s.db_schema == "surge_quality"
    assert s.hermes_model == "hermes3:8b"
    assert s.reviewer_model == "claude-opus-4-7"
    assert s.llm_review_threshold == 5.0


def test_env_override(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://x:y@localhost:5432/z")
    monkeypatch.setenv("SURGE_QUALITY_PORT", "9311")
    s = Settings()
    assert s.database_url == "postgresql://x:y@localhost:5432/z"
    assert s.port == 9311


def test_reviewer_api_key_legacy_alias(monkeypatch) -> None:
    """The shipped backend's ANTHROPIC_API_KEY remains a valid source for the
    generic reviewer_api_key so existing deployments keep working."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "legacy-key-value")
    s = Settings()
    assert s.reviewer_api_key == "legacy-key-value"


def test_reviewer_api_key_generic_name(monkeypatch) -> None:
    """The generic REVIEWER_API_KEY name is honored."""
    monkeypatch.setenv("REVIEWER_API_KEY", "generic-key-value")
    s = Settings()
    assert s.reviewer_api_key == "generic-key-value"
