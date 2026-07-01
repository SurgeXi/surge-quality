# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""Routing API integration tests against real surgecore Postgres."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from surge_quality.db import Base
from surge_quality.main import create_app
from surge_quality.models import Response, RoutingDecision, RubricScore
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
    reason="DATABASE_URL not reachable — routing tests need real PG",
)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture()
def cleanup_routing():
    url = os.environ.get("DATABASE_URL") or get_settings().database_url
    eng = create_engine(url)
    Base.metadata.create_all(eng)
    sess = Session(bind=eng)
    created_ids: list[int] = []
    created_response_ids: list[int] = []
    try:
        yield sess, created_ids, created_response_ids
    finally:
        if created_ids:
            sess.query(RoutingDecision).filter(
                RoutingDecision.id.in_(created_ids)
            ).delete(synchronize_session=False)
        if created_response_ids:
            sess.query(Response).filter(
                Response.id.in_(created_response_ids)
            ).delete(synchronize_session=False)
        sess.commit()
        sess.close()
        eng.dispose()


def test_route_decision_innocuous_message(
    client: TestClient, cleanup_routing
) -> None:
    sess, created_ids, _ = cleanup_routing
    r = client.post(
        "/v1/quality/route-decision",
        json={
            "input_message": "what's the weather today?",
            "history_length": 0,
            "identity_context": {},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["decision"] == "surge"
    assert "advisory_note" in body
    assert "SOL" in body["advisory_note"]
    created_ids.append(body["decision_id"])


def test_route_decision_urgent_customer(
    client: TestClient, cleanup_routing
) -> None:
    sess, created_ids, _ = cleanup_routing
    r = client.post(
        "/v1/quality/route-decision",
        json={
            "input_message": "URGENT: my payroll is broken right now, please help",
            "conversation_id": "conv-urgent-1",
            "history_length": 2,
            "identity_context": {
                "logged_in_user": "sheilia@timesavedap.com",
                "session_surface": "pulsepoint-chat",
            },
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["decision"] == "claude_primary"
    created_ids.append(body["decision_id"])


def test_route_decision_persisted(client: TestClient, cleanup_routing) -> None:
    sess, created_ids, _ = cleanup_routing
    r = client.post(
        "/v1/quality/route-decision",
        json={
            "input_message": "hello there",
            "conversation_id": "conv-persist-1",
            "identity_context": {},
            "context": {"x": 1},
        },
    )
    assert r.status_code == 200
    decision_id = r.json()["decision_id"]
    created_ids.append(decision_id)
    row = sess.get(RoutingDecision, decision_id)
    assert row is not None
    assert row.input_message == "hello there"
    assert row.conversation_id == "conv-persist-1"
    assert row.context_json == {"x": 1}


def test_route_decision_high_similarity_to_real_low_score(
    client: TestClient, cleanup_routing
) -> None:
    """Seed a low-score response in the DB, then post a near-identical
    message and confirm the classifier routes to claude_primary."""
    sess, created_ids, created_response_ids = cleanup_routing
    resp = Response(
        conversation_id="conv-seed",
        response_text="my refund got stuck somewhere in the system",
        model_used="hermes3:8b",
        source="routing-test-seed",
        identity_json={},
    )
    sess.add(resp)
    sess.commit()
    sess.refresh(resp)
    created_response_ids.append(resp.id)

    score = RubricScore(
        response_id=resp.id,
        composite=2.0,
        scorer_model="hermes3:8b",
        raw_json={},
        correctness=2.0,
        tone_match=2.0,
        completeness=2.0,
        action_orientation=2.0,
        brevity=2.0,
        citation_quality=2.0,
        identity_awareness=2.0,
        memory_usage=2.0,
        safety=2.0,
        confidence_calibration=2.0,
    )
    sess.add(score)
    sess.commit()

    r = client.post(
        "/v1/quality/route-decision",
        json={
            "input_message": "my refund got stuck somewhere in the system",
            "identity_context": {"logged_in_user": "sheilia@timesavedap.com"},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    created_ids.append(body["decision_id"])
    # High Jaccard similarity (identical message) should fire the
    # claude_primary path.
    assert body["decision"] == "claude_primary"
    assert "similar" in body["reasoning"]
    assert body["factors"]["similarity_to_low_score"] > 0.7


def test_route_decision_empty_message_422(
    client: TestClient, cleanup_routing
) -> None:
    r = client.post("/v1/quality/route-decision", json={"input_message": ""})
    assert r.status_code == 422, r.text
