# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""Scoring API: POST + GET /v1/quality/score-response.

PR-5 update: after a successful score, optionally schedule a the LLM reviewer
review when the composite falls below the configured threshold.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from surge_quality.api.auth import require_service_token
from surge_quality.db import get_db
from surge_quality.models import Response, RubricScore
from surge_quality.reviewer.worker import maybe_trigger_review
from surge_quality.scoring.service import ResponseNotFound, score_response
from surge_quality.settings import get_settings

router = APIRouter(prefix="/v1/quality", tags=["scoring"])


# --- request / response schemas --------------------------------------------


class ScoreResponseIn(BaseModel):
    """Body for POST /v1/quality/score-response."""

    response_id: int | None = Field(default=None, description="existing Response.id")
    conversation_id: str | None = Field(default=None)
    response_text: str | None = Field(default=None)
    model_used: str | None = Field(default=None)
    source: str = Field(default="api")
    identity_json: dict[str, Any] = Field(default_factory=dict)
    customer_message: str | None = Field(
        default=None, description="optional preceding customer turn (improves scoring)"
    )
    force: bool = Field(default=False, description="re-score even if already scored")


class RubricOut(BaseModel):
    response_id: int
    rubric_score_id: int
    composite: float
    axes: dict[str, float]
    justification: str
    scorer_model: str
    scored_at: datetime
    review_scheduled: bool = False


# --- endpoints --------------------------------------------------------------


@router.post(
    "/score-response",
    response_model=RubricOut,
    dependencies=[Depends(require_service_token)],
)
async def post_score_response(
    body: ScoreResponseIn,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> RubricOut:
    if body.response_id is None:
        if not (body.response_text and body.model_used and body.conversation_id):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="response_id OR (response_text+model_used+conversation_id) required",
            )
        resp = Response(
            conversation_id=body.conversation_id,
            response_text=body.response_text,
            model_used=body.model_used,
            source=body.source,
            identity_json=body.identity_json or {},
        )
        db.add(resp)
        db.commit()
        db.refresh(resp)
        response_id = resp.id
    else:
        response_id = body.response_id

    try:
        result = await score_response(
            db, response_id, customer_message=body.customer_message, force=body.force
        )
    except ResponseNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    row = db.query(RubricScore).filter_by(id=result.persisted_row_id).one()

    # If composite is below threshold AND a key is configured, schedule the
    # LLM reviewer as a background task. We use FastAPI's BackgroundTasks
    # rather than asyncio.create_task because it ties the lifecycle to the
    # request (cleaner for tests + observability).
    settings = get_settings()
    review_scheduled = False
    if (
        row.composite < settings.llm_review_threshold
        and settings.anthropic_api_key
    ):
        background_tasks.add_task(
            maybe_trigger_review,
            response_id,
            row.composite,
            customer_message=body.customer_message,
        )
        review_scheduled = True

    return RubricOut(
        response_id=response_id,
        rubric_score_id=row.id,
        composite=row.composite,
        axes={a: getattr(row, a) for a in result.parsed.axes},
        justification=result.parsed.justification,
        scorer_model=row.scorer_model,
        scored_at=row.scored_at,
        review_scheduled=review_scheduled,
    )


@router.get(
    "/score-response/{response_id}",
    response_model=RubricOut,
    dependencies=[Depends(require_service_token)],
)
def get_score_response(response_id: int, db: Session = Depends(get_db)) -> RubricOut:
    row = db.query(RubricScore).filter_by(response_id=response_id).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=f"no score for response_id={response_id}")
    parsed = row.raw_json or {}
    return RubricOut(
        response_id=response_id,
        rubric_score_id=row.id,
        composite=row.composite,
        axes={
            a: getattr(row, a)
            for a in (
                "correctness",
                "tone_match",
                "completeness",
                "action_orientation",
                "brevity",
                "citation_quality",
                "identity_awareness",
                "memory_usage",
                "safety",
                "confidence_calibration",
            )
        },
        justification=str(parsed.get("justification", "")) or "(no justification recorded)",
        scorer_model=row.scorer_model,
        scored_at=row.scored_at,
        review_scheduled=False,
    )
