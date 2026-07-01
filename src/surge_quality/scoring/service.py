# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""Scoring service orchestration.

``score_response`` is the top-level call used by the API and (later) the
async worker. Steps:

1. Load the Response row by id.
2. Render the rubric prompt with optional customer message context.
3. Call Hermes, get parsed JSON.
4. Persist the RubricScore row + flip ``responses.scored = true``.
5. Return the persisted score.

If the response is already scored, the existing row is returned (no
re-score) — the API caller can force a re-score by deleting the prior row.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from surge_quality.models import Response, RubricScore
from surge_quality.scoring.hermes_client import HermesClient, HermesError
from surge_quality.scoring.parser import ParsedRubric, parse_rubric_json
from surge_quality.scoring.rubric import SYSTEM_PROMPT, render_prompt
from surge_quality.settings import get_settings

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ScoreResult:
    """Returned to the API layer."""

    response_id: int
    parsed: ParsedRubric
    persisted_row_id: int


class ResponseNotFound(LookupError):
    """Raised when score_response can't find the response_id."""


async def score_response(
    db: Session,
    response_id: int,
    *,
    customer_message: str | None = None,
    hermes: HermesClient | None = None,
    force: bool = False,
) -> ScoreResult:
    """Score a single Response. Sync persistence inside an async function
    because SQLAlchemy 2.0 sync session is the existing surge_quality
    convention; the Hermes call is the actual async I/O."""

    settings = get_settings()
    if hermes is None:
        hermes = HermesClient(
            base_url=settings.hermes_base_url,
            model=settings.hermes_model,
            timeout_seconds=settings.hermes_timeout_seconds,
        )

    resp = db.get(Response, response_id)
    if resp is None:
        raise ResponseNotFound(f"no response with id={response_id}")

    if resp.scored and not force:
        existing = db.query(RubricScore).filter_by(response_id=response_id).one()
        parsed = parse_rubric_json(existing.raw_json)
        return ScoreResult(response_id=response_id, parsed=parsed, persisted_row_id=existing.id)

    cust_msg = customer_message or "(none — score the response in isolation)"
    prompt = render_prompt(
        customer_message=cust_msg,
        surge_response=resp.response_text,
        identity_context=resp.identity_json or None,
    )
    try:
        raw = await hermes.generate_json(prompt, system=SYSTEM_PROMPT)
    except HermesError:
        logger.exception("hermes failed for response_id=%s", response_id)
        raise

    parsed = parse_rubric_json(raw)

    # On force re-score, delete the prior row first.
    if resp.scored and force:
        db.query(RubricScore).filter_by(response_id=response_id).delete()

    row = RubricScore(
        response_id=response_id,
        composite=parsed.composite,
        scorer_model=hermes.model,
        raw_json=parsed.raw,
        **parsed.axes,
    )
    db.add(row)
    resp.scored = True
    db.commit()
    db.refresh(row)

    return ScoreResult(response_id=response_id, parsed=parsed, persisted_row_id=row.id)
