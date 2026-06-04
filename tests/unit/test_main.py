"""Health endpoints smoke — no DB required for /healthz."""

from __future__ import annotations

from fastapi.testclient import TestClient

from surge_quality.main import create_app


def test_healthz() -> None:
    client = TestClient(create_app())
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "surge-quality"
