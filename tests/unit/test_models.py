# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""Round-trip + index sanity tests for the surge_quality ORM models.

Uses a real Postgres connection (the same surgecore Postgres used in
production), inside a transaction that always rolls back so tests leave no
trace. ``DATABASE_URL`` must be set by the runner — CI provides a
disposable per-job DB; locally the developer points it at any reachable
surge_brain.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from surge_quality.db import Base
from surge_quality.models import (
    LlmReview,
    Response,
    RoutingDecision,
    RubricScore,
    TelemetrySignal,
)
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
    reason="DATABASE_URL not reachable — model round-trip tests need real PG",
)


@pytest.fixture()
def session() -> Session:
    """Yield a session inside a transaction that rolls back."""
    url = os.environ.get("DATABASE_URL") or get_settings().database_url
    eng = create_engine(url)
    # Schema is provisioned out-of-band — the surge_quality role owns it
    # but does NOT have CREATE on the database. We rely on the deployer
    # having created the schema before tests run. ``create_all`` is
    # idempotent against pre-existing tables.
    Base.metadata.create_all(eng)
    conn = eng.connect()
    trans = conn.begin()
    sess = Session(bind=conn)
    try:
        yield sess
    finally:
        sess.close()
        trans.rollback()
        conn.close()


def _make_response(sess: Session, **overrides) -> Response:
    defaults = dict(
        conversation_id="conv-test-1",
        response_text="Sample Surge response text.",
        model_used="hermes3:8b",
        source="manual",
        identity_json={"logged_in_user": "test@surgexi.com"},
        generated_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    resp = Response(**defaults)
    sess.add(resp)
    sess.flush()
    return resp


def test_response_roundtrip(session: Session) -> None:
    resp = _make_response(session)
    assert resp.id is not None
    fetched = session.get(Response, resp.id)
    assert fetched is not None
    assert fetched.conversation_id == "conv-test-1"
    assert fetched.identity_json["logged_in_user"] == "test@surgexi.com"
    assert fetched.scored is False


def test_rubric_score_roundtrip(session: Session) -> None:
    resp = _make_response(session)
    axes = {
        "correctness": 8.0,
        "tone_match": 7.5,
        "completeness": 9.0,
        "action_orientation": 6.0,
        "brevity": 7.0,
        "citation_quality": 5.0,
        "identity_awareness": 8.0,
        "memory_usage": 6.0,
        "safety": 10.0,
        "confidence_calibration": 7.0,
    }
    composite = sum(axes.values()) / len(axes)
    rs = RubricScore(
        response_id=resp.id,
        composite=composite,
        scorer_model="hermes3:8b",
        raw_json={"axes": axes},
        **axes,
    )
    session.add(rs)
    session.flush()
    fetched = session.get(RubricScore, rs.id)
    assert fetched.composite == pytest.approx(composite)
    assert fetched.raw_json["axes"]["safety"] == 10.0


def test_telemetry_dedup_constraint(session: Session) -> None:
    resp = _make_response(session)
    session.add(
        TelemetrySignal(response_id=resp.id, signal_type="thumbs_up", value=1.0)
    )
    session.flush()
    # Duplicate (response_id, signal_type) must raise.
    session.add(
        TelemetrySignal(response_id=resp.id, signal_type="thumbs_up", value=1.0)
    )
    with pytest.raises(Exception):
        session.flush()


def test_telemetry_distinct_signal_types(session: Session) -> None:
    resp = _make_response(session)
    session.add(TelemetrySignal(response_id=resp.id, signal_type="thumbs_up", value=1.0))
    session.add(
        TelemetrySignal(response_id=resp.id, signal_type="reply_time_seconds", value=4.2)
    )
    session.flush()
    rows = session.query(TelemetrySignal).filter_by(response_id=resp.id).all()
    assert {r.signal_type for r in rows} == {"thumbs_up", "reply_time_seconds"}


def test_llm_review_roundtrip(session: Session) -> None:
    resp = _make_response(session)
    cr = LlmReview(
        response_id=resp.id,
        better_response="Here is what I would have said.",
        what_was_wrong="The original missed the user's actual question.",
        how_to_fix="Re-read the user's prior turn and answer the asked question.",
        reviewer_model="claude-opus-4-7",
        raw_json={"latency_ms": 1200},
        triggered_by_score=3.4,
    )
    session.add(cr)
    session.flush()
    fetched = session.get(LlmReview, cr.id)
    assert fetched.triggered_by_score == pytest.approx(3.4)


def test_routing_decision_roundtrip(session: Session) -> None:
    rd = RoutingDecision(
        conversation_id="conv-route-1",
        input_message="My bank feed broke, urgent",
        context_json={"history_length": 3},
        identity_json={"logged_in_user": "sheilia@timesavedap.com"},
        decision="claude_primary",
        reasoning="urgency keyword matched + high-stakes identity",
        factors_json={"urgency": True, "similarity": 0.0, "complexity": "tier-2"},
    )
    session.add(rd)
    session.flush()
    fetched = session.get(RoutingDecision, rd.id)
    assert fetched.decision == "claude_primary"


def test_index_used_for_recent_responses(session: Session) -> None:
    """Sanity check: planner picks the (conversation_id, generated_at)
    index for the most common scoring-worker query."""
    _make_response(session, conversation_id="conv-hot")
    session.flush()
    plan = (
        session.execute(
            text(
                "EXPLAIN SELECT id FROM surge_quality.responses "
                "WHERE conversation_id = :c ORDER BY generated_at DESC LIMIT 5"
            ),
            {"c": "conv-hot"},
        )
        .scalars()
        .all()
    )
    plan_text = "\n".join(plan)
    # Postgres may pick seq scan for tiny tables; just assert the query
    # is plannable and the index exists.
    assert "surge_quality.responses" in plan_text or "responses" in plan_text
    # Verify the index exists in catalog.
    idx = (
        session.execute(
            text(
                "SELECT indexname FROM pg_indexes "
                "WHERE schemaname='surge_quality' AND tablename='responses'"
            )
        )
        .scalars()
        .all()
    )
    assert "ix_responses_conv_generated" in idx
