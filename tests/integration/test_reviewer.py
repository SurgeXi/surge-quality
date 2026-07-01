# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""Reviewer integration test: mocked Anthropic client + real Postgres."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from surge_quality.db import Base
from surge_quality.models import LlmReview, Response, RubricScore
from surge_quality.reviewer.service import review_response
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
    reason="DATABASE_URL not reachable — reviewer integration test needs real PG",
)


@dataclass
class FakeAnthropicClient:
    """Test double for AnthropicClient — returns a canned JSON body."""

    model: str
    payload: dict

    async def review(self, system_prompt: str, user_prompt: str, **_) -> str:
        return json.dumps(self.payload)


@pytest.fixture()
def fixture_response_with_score():
    url = os.environ.get("DATABASE_URL") or get_settings().database_url
    eng = create_engine(url)
    Base.metadata.create_all(eng)
    sess = Session(bind=eng)
    resp = Response(
        conversation_id="conv-review-itest",
        response_text="Vague, deflecting answer that ignored the user's actual question.",
        model_used="hermes3:8b",
        source="reviewer-test",
        identity_json={"logged_in_user": "sheilia@timesavedap.com"},
    )
    sess.add(resp)
    sess.commit()
    sess.refresh(resp)
    axes = {
        "correctness": 3.0,
        "tone_match": 4.0,
        "completeness": 2.0,
        "action_orientation": 1.0,
        "brevity": 6.0,
        "citation_quality": 0.0,
        "identity_awareness": 3.0,
        "memory_usage": 2.0,
        "safety": 10.0,
        "confidence_calibration": 3.0,
    }
    composite = sum(axes.values()) / len(axes)
    score = RubricScore(
        response_id=resp.id,
        composite=composite,
        scorer_model="hermes3:8b",
        raw_json={"axes": axes, "justification": "weak across the board"},
        **axes,
    )
    sess.add(score)
    sess.commit()
    try:
        yield sess, resp.id
    finally:
        sess.query(Response).filter_by(id=resp.id).delete()
        sess.commit()
        sess.close()
        eng.dispose()


@pytest.mark.asyncio
async def test_review_response_persists(fixture_response_with_score) -> None:
    sess, response_id = fixture_response_with_score
    fake = FakeAnthropicClient(
        model="claude-opus-4-7-test",
        payload={
            "better_response": "Here is the answer the customer asked for.",
            "what_was_wrong": "The response deflected and did not engage with the actual question.",
            "how_to_fix": "Re-read the user's last turn and answer the literal question first.",
        },
    )
    parsed = await review_response(
        sess,
        response_id,
        customer_message="why is my bank feed broken?",
        client=fake,
    )
    assert "Here is the answer" in parsed.better_response

    row = sess.query(LlmReview).filter_by(response_id=response_id).one()
    assert row.better_response.startswith("Here is the answer")
    assert row.what_was_wrong.startswith("The response deflected")
    assert row.triggered_by_score < 5.0
    assert row.reviewer_model == "claude-opus-4-7-test"


@pytest.mark.asyncio
async def test_review_response_dedup(fixture_response_with_score) -> None:
    """Second call returns the already-persisted review without re-calling Claude."""
    sess, response_id = fixture_response_with_score
    fake = FakeAnthropicClient(
        model="claude-opus-4-7-test",
        payload={
            "better_response": "first call body",
            "what_was_wrong": "first",
            "how_to_fix": "first",
        },
    )
    await review_response(sess, response_id, client=fake)

    # Swap to a second client that would return different text — second call
    # should return the FIRST review, proving dedup.
    fake2 = FakeAnthropicClient(
        model="should-not-be-used",
        payload={"better_response": "second", "what_was_wrong": "x", "how_to_fix": "y"},
    )
    parsed = await review_response(sess, response_id, client=fake2)
    assert parsed.better_response == "first call body"
