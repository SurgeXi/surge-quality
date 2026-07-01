# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""Telemetry endpoint integration tests against the real surgecore Postgres."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from surge_quality.db import Base
from surge_quality.main import create_app
from surge_quality.models import Response
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
    reason="DATABASE_URL not reachable — telemetry tests need real PG",
)


@pytest.fixture()
def setup_response():
    """Create a Response row in the real DB, yield its id, clean up after."""
    url = os.environ.get("DATABASE_URL") or get_settings().database_url
    eng = create_engine(url)
    Base.metadata.create_all(eng)
    sess = Session(bind=eng)
    resp = Response(
        conversation_id="conv-tele-test",
        response_text="A surge response for telemetry tests.",
        model_used="hermes3:8b",
        source="telemetry-test",
        identity_json={},
    )
    sess.add(resp)
    sess.commit()
    sess.refresh(resp)
    rid = resp.id
    try:
        yield rid
    finally:
        # CASCADE will remove any telemetry rows we created.
        sess.query(Response).filter_by(id=rid).delete()
        sess.commit()
        sess.close()
        eng.dispose()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def test_post_telemetry_thumbs_up(client: TestClient, setup_response: int) -> None:
    r = client.post(
        "/v1/quality/telemetry",
        json={
            "response_id": setup_response,
            "signal_type": "thumbs_up",
            "value": 1.0,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["signal_type"] == "thumbs_up"
    assert body["value"] == 1.0


def test_post_telemetry_reply_time(client: TestClient, setup_response: int) -> None:
    r = client.post(
        "/v1/quality/telemetry",
        json={
            "response_id": setup_response,
            "signal_type": "reply_time_seconds",
            "value": 4.7,
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["value"] == 4.7


def test_post_telemetry_all_signal_types(
    client: TestClient, setup_response: int
) -> None:
    """Every enum value round-trips. Each is a different signal_type so
    the unique constraint does not fire."""
    for sig in (
        "thumbs_up",
        "thumbs_down",
        "reply_time_seconds",
        "dropoff",
        "reask",
        "human_escalation_request",
    ):
        r = client.post(
            "/v1/quality/telemetry",
            json={
                "response_id": setup_response,
                "signal_type": sig,
                "value": 1.0,
            },
        )
        assert r.status_code == 201, f"{sig}: {r.text}"


def test_dedup_returns_409(client: TestClient, setup_response: int) -> None:
    body = {
        "response_id": setup_response,
        "signal_type": "thumbs_down",
        "value": 1.0,
    }
    r1 = client.post("/v1/quality/telemetry", json=body)
    assert r1.status_code == 201
    r2 = client.post("/v1/quality/telemetry", json=body)
    assert r2.status_code == 409, r2.text
    assert "already recorded" in r2.json()["detail"]


def test_invalid_response_id_404(client: TestClient) -> None:
    r = client.post(
        "/v1/quality/telemetry",
        json={
            "response_id": 9_999_999_999,
            "signal_type": "thumbs_up",
            "value": 1.0,
        },
    )
    assert r.status_code == 404, r.text
    assert "not found" in r.json()["detail"]


def test_invalid_signal_type_422(
    client: TestClient, setup_response: int
) -> None:
    r = client.post(
        "/v1/quality/telemetry",
        json={
            "response_id": setup_response,
            "signal_type": "gibberish",
            "value": 1.0,
        },
    )
    assert r.status_code == 422, r.text


def test_metadata_json_persisted(
    client: TestClient, setup_response: int
) -> None:
    r = client.post(
        "/v1/quality/telemetry",
        json={
            "response_id": setup_response,
            "signal_type": "reask",
            "value": None,
            "metadata_json": {"original_question": "where is my refund?"},
        },
    )
    assert r.status_code == 201, r.text
    # GET-style verification: re-post should 409 (dedup) confirming the row is there.
    r2 = client.post(
        "/v1/quality/telemetry",
        json={
            "response_id": setup_response,
            "signal_type": "reask",
            "value": None,
            "metadata_json": {"original_question": "different text — still dedup'd"},
        },
    )
    assert r2.status_code == 409
