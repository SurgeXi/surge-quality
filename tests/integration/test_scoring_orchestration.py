# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""Integration test: full score_response orchestration against a mocked Hermes.

Uses the real Postgres-backed Session (via the same fixture pattern as
test_models.py) so we exercise the actual DB write path.
"""

from __future__ import annotations

import json
import os

import httpx
import pytest
import respx
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from surge_quality.db import Base
from surge_quality.models import Response, RubricScore
from surge_quality.scoring.hermes_client import HermesClient
from surge_quality.scoring.service import score_response
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
    reason="DATABASE_URL not reachable — orchestration test needs real PG",
)


@pytest.fixture()
def engine_and_session():
    """Yield a session that commits to the real DB, then we explicitly clean
    the rows we created. Service calls ``db.commit()`` so an outer-rollback
    pattern is not viable for this test."""
    url = os.environ.get("DATABASE_URL") or get_settings().database_url
    eng = create_engine(url)
    Base.metadata.create_all(eng)
    sess = Session(bind=eng)
    created_response_ids: list[int] = []
    try:
        yield eng, sess, created_response_ids
    finally:
        # Cleanup: hard-delete the rows our test created. CASCADE removes
        # the rubric_score row too.
        if created_response_ids:
            sess.query(Response).filter(
                Response.id.in_(created_response_ids)
            ).delete(synchronize_session=False)
            sess.commit()
        sess.close()
        eng.dispose()


@pytest.mark.asyncio
async def test_score_response_end_to_end(engine_and_session) -> None:
    _eng, session, created = engine_and_session
    resp = Response(
        conversation_id="conv-itest",
        response_text="I checked your bank feed; the Plaid token expired on 2026-06-01. "
        "I will refresh it now and confirm once the next sync succeeds.",
        model_used="hermes3:8b",
        source="integration-test",
        identity_json={"logged_in_user": "sheilia@timesavedap.com"},
    )
    session.add(resp)
    session.commit()
    session.refresh(resp)
    created.append(resp.id)

    payload = {
        "correctness": 8.0,
        "tone_match": 8.5,
        "completeness": 9.0,
        "action_orientation": 9.0,
        "brevity": 8.0,
        "citation_quality": 7.0,
        "identity_awareness": 8.0,
        "memory_usage": 6.0,
        "safety": 10.0,
        "confidence_calibration": 7.5,
        "justification": "concrete, action-oriented, named the source",
    }
    with respx.mock(base_url="http://hermes-mock") as mock:
        mock.post("/api/generate").mock(
            return_value=httpx.Response(
                200, json={"response": json.dumps(payload), "done": True}
            )
        )
        hermes = HermesClient(
            "http://hermes-mock", "hermes3:8b", timeout_seconds=5, backoff_seconds=0
        )
        result = await score_response(
            session,
            resp.id,
            customer_message="why is my bank feed broken?",
            hermes=hermes,
        )

    assert result.persisted_row_id is not None
    row = session.query(RubricScore).filter_by(response_id=resp.id).one()
    assert row.composite > 0
    assert row.scorer_model == "hermes3:8b"
    assert row.raw_json["justification"].startswith("concrete")
    session.refresh(resp)
    assert resp.scored is True
