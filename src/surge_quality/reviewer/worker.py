"""Async background trigger that runs the Claude reviewer when a rubric score
crosses the low-threshold defined in settings.claude_review_threshold.

The current execution model is BackgroundTasks-style: a coroutine that
the API layer awaits-or-schedules via ``asyncio.create_task``. PR-7+ may
swap this for a Celery / RQ task queue once real volume warrants the
operational cost.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from sqlalchemy.orm import Session

from surge_quality.db import SessionLocal
from surge_quality.reviewer.service import (
    ReviewerNotConfigured,
    review_response,
)
from surge_quality.settings import get_settings

logger = logging.getLogger(__name__)


async def maybe_trigger_review(
    response_id: int,
    composite_score: float,
    *,
    customer_message: str | None = None,
    session_factory: Callable[[], Session] | None = None,
) -> bool:
    """Run the Claude reviewer iff the score is below the threshold.

    Returns True when a review was attempted (regardless of success);
    False when the score did not warrant a review.
    """
    settings = get_settings()
    threshold = settings.claude_review_threshold
    if composite_score >= threshold:
        return False
    if not settings.anthropic_api_key:
        logger.warning(
            "low score %.2f on response_id=%s but ANTHROPIC_API_KEY is unset; "
            "skipping reviewer. Provision /etc/surge-quality/claude.env on the host.",
            composite_score,
            response_id,
        )
        return False

    factory = session_factory or SessionLocal
    db = factory()
    try:
        try:
            await review_response(db, response_id, customer_message=customer_message)
            return True
        except ReviewerNotConfigured:
            logger.warning(
                "reviewer not configured at trigger time response_id=%s", response_id
            )
            return False
        except Exception:  # noqa: BLE001
            logger.exception("claude reviewer failed response_id=%s", response_id)
            return True  # attempted, but failed — caller should not retry on a hot path
    finally:
        db.close()


def schedule_review(
    response_id: int,
    composite_score: float,
    *,
    customer_message: str | None = None,
) -> None:
    """Fire-and-forget: schedule maybe_trigger_review on the running loop."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop — caller is synchronous; we cannot schedule.
        logger.warning(
            "schedule_review called without a running event loop "
            "(response_id=%s) — skipping",
            response_id,
        )
        return
    loop.create_task(
        maybe_trigger_review(
            response_id,
            composite_score,
            customer_message=customer_message,
        )
    )
