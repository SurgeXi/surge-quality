"""Routing API: POST /v1/quality/route-decision.

READ-ONLY contract: returns advice + persists the decision row for audit.
Does NOT trigger any model swap. The consumer (Brain, PulsePoint backend)
is responsible for asking SOL to dispatch a ``pulsepoint_set_model``
capability if it wants to act on the advice.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from surge_quality.api.auth import require_service_token
from surge_quality.db import get_db
from surge_quality.models import Response, RoutingDecision, RubricScore
from surge_quality.routing.classifier import classify
from surge_quality.routing.similarity import max_similarity_to_corpus
from surge_quality.settings import get_settings

router = APIRouter(prefix="/v1/quality", tags=["routing"])

LOW_SCORE_CORPUS_LIMIT = 50


class RouteDecisionIn(BaseModel):
    """Body for POST /v1/quality/route-decision."""

    input_message: str = Field(..., min_length=1)
    conversation_id: str | None = Field(default=None)
    history_length: int = Field(default=0, ge=0)
    identity_context: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="opaque caller-provided context (logged for audit)",
    )


class RouteDecisionOut(BaseModel):
    decision: str
    reasoning: str
    factors: dict[str, Any]
    decision_id: int
    decided_at: datetime
    advisory_note: str = (
        "READ-ONLY recommendation. Any model swap must go through SOL "
        "dispatch (capability: pulsepoint_set_model)."
    )


def _load_low_score_corpus(db: Session) -> list[str]:
    """Recent low-scoring Surge responses, used as the similarity corpus."""
    settings = get_settings()
    threshold = settings.claude_review_threshold
    rows = (
        db.query(Response.response_text)
        .join(RubricScore, RubricScore.response_id == Response.id)
        .filter(RubricScore.composite < threshold)
        .order_by(RubricScore.scored_at.desc())
        .limit(LOW_SCORE_CORPUS_LIMIT)
        .all()
    )
    return [r[0] for r in rows]


@router.post(
    "/route-decision",
    response_model=RouteDecisionOut,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_service_token)],
)
def post_route_decision(
    body: RouteDecisionIn, db: Session = Depends(get_db)
) -> RouteDecisionOut:
    settings = get_settings()

    corpus = _load_low_score_corpus(db)
    similarity = max_similarity_to_corpus(body.input_message, corpus)

    result = classify(
        body.input_message,
        identity_context=body.identity_context or None,
        history_length=body.history_length,
        max_similarity_low_score=similarity,
        similarity_threshold=settings.similarity_threshold,
    )

    row = RoutingDecision(
        conversation_id=body.conversation_id,
        input_message=body.input_message,
        context_json=body.context or {},
        identity_json=body.identity_context or {},
        decision=result.decision,
        reasoning=result.reasoning,
        factors_json=result.factors,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    return RouteDecisionOut(
        decision=result.decision,
        reasoning=result.reasoning,
        factors=result.factors,
        decision_id=row.id,
        decided_at=row.decided_at,
    )
