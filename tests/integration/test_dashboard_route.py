"""Integration test for /v1/quality/dashboard against a real surge_brain DB.

Gated on DATABASE_URL reachability so the suite is still green on a
laptop with no Postgres handy.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from surge_quality.main import create_app
from surge_quality.settings import get_settings


def _db_available() -> bool:
    url = os.environ.get("DATABASE_URL") or get_settings().database_url
    try:
        eng = create_engine(url, pool_pre_ping=True)
        with eng.connect() as c:
            c.execute(text("SELECT 1")).scalar_one()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _db_available(),
    reason="DATABASE_URL not reachable — dashboard integration test needs PG",
)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def test_dashboard_html_renders_200(client: TestClient) -> None:
    """The HTML route returns 200 and a body that looks like the dashboard.

    No fixture data required — the dashboard is well-defined on an empty
    schema (the empty-state strings render). This is the key invariant
    for the PR-10 smoke test, so we lock it down here.
    """
    r = client.get("/v1/quality/dashboard")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/html")
    body = r.text
    assert "surge-quality" in body
    assert "operator dashboard" in body
    # Three section headings must be present regardless of data.
    assert "Per-day Surge share" in body
    assert "Topic-area breakdown" in body
    assert "Low-score replay" in body


def test_dashboard_metrics_json_shape(client: TestClient) -> None:
    r = client.get("/v1/quality/dashboard/metrics")
    assert r.status_code == 200, r.text
    body = r.json()
    for key in (
        "generated_at",
        "today",
        "window_days",
        "llm_review_threshold",
        "daily",
        "topics",
        "low_scores",
    ):
        assert key in body
    assert body["window_days"] == 14
    assert isinstance(body["daily"], list)
    # Always 14 day buckets (one per day in the window), even if empty.
    assert len(body["daily"]) == 14


def test_dashboard_metrics_daily_shape(client: TestClient) -> None:
    r = client.get("/v1/quality/dashboard/metrics")
    assert r.status_code == 200
    day = r.json()["daily"][0]
    for key in ("day", "surge_share_pct", "llm_share_pct", "avg_combined", "n_responses"):
        assert key in day
