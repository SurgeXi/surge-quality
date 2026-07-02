# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""Reviewer service: take a low-scoring Response, ask the LLM reviewer, persist the result.

Triggered from the scoring service when ``composite < settings.llm_review_threshold``.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from surge_quality.models import LlmReview, Response, RubricScore, TelemetrySignal
from surge_quality.reviewer.llm_reviewer import LlmReviewer
from surge_quality.reviewer.parser import ParsedReview, parse_review_json
from surge_quality.reviewer.prompts import SYSTEM_PROMPT, render_user_prompt
from surge_quality.settings import get_settings

logger = logging.getLogger(__name__)


AXES = (
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


class ReviewerNotConfigured(RuntimeError):
    """Raised when the reviewer API key is empty so the reviewer cannot run."""


async def review_response(
    db: Session,
    response_id: int,
    *,
    customer_message: str | None = None,
    client: LlmReviewer | None = None,
) -> ParsedReview:
    """Produce a LLM review for the named response and persist it.

    If a review already exists for that response_id, return the parsed
    persisted record without re-calling the LLM reviewer.
    """

    settings = get_settings()
    if client is None:
        if not settings.reviewer_api_key:
            raise ReviewerNotConfigured(
                "reviewer API key not set — LLM reviewer is disabled. "
                "Install /etc/surge-quality/provider.env on the host and "
                "restart the service."
            )
        client = LlmReviewer(
            api_key=settings.reviewer_api_key,
            model=settings.reviewer_model,
        )

    existing = db.query(LlmReview).filter_by(response_id=response_id).one_or_none()
    if existing is not None:
        return ParsedReview(
            better_response=existing.better_response,
            what_was_wrong=existing.what_was_wrong,
            how_to_fix=existing.how_to_fix,
            raw=existing.raw_json,
        )

    resp = db.get(Response, response_id)
    if resp is None:
        raise LookupError(f"no response with id={response_id}")
    rubric = db.query(RubricScore).filter_by(response_id=response_id).one_or_none()
    if rubric is None:
        raise LookupError(
            f"response_id={response_id} has no rubric score yet — "
            "cannot review without scoring context"
        )
    telemetry_rows = (
        db.query(TelemetrySignal).filter_by(response_id=response_id).all()
    )
    telemetry_payload = [
        {
            "signal_type": s.signal_type,
            "value": s.value,
            "metadata": s.metadata_json,
        }
        for s in telemetry_rows
    ]
    axes = {a: getattr(rubric, a) for a in AXES}
    user_prompt = render_user_prompt(
        customer_message=customer_message or "(no customer message captured)",
        surge_response=resp.response_text,
        rubric_axes=axes,
        rubric_composite=rubric.composite,
        telemetry_signals=telemetry_payload,
        identity_context=resp.identity_json or None,
    )

    raw = await client.review(SYSTEM_PROMPT, user_prompt)
    parsed = parse_review_json(raw)

    db.add(
        LlmReview(
            response_id=response_id,
            better_response=parsed.better_response,
            what_was_wrong=parsed.what_was_wrong,
            how_to_fix=parsed.how_to_fix,
            reviewer_model=client.model,
            raw_json=parsed.raw or {},
            triggered_by_score=rubric.composite,
        )
    )
    db.commit()
    return parsed
