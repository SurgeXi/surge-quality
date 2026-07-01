# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""Telemetry capture endpoint.

PulsePoint widget POSTs customer signals to this endpoint when the user:
- thumbs-up/thumbs-down on a Surge turn
- replies (the time between Surge's turn and the reply is the reply_time signal)
- drops off (the conversation ends within N seconds of Surge's turn)
- re-asks (rephrases the same question — Surge missed intent)
- requests human escalation

Booleans (``thumbs_up``, ``thumbs_down``, ``dropoff``, ``reask``,
``human_escalation_request``) are deduplicated per ``(response_id, signal_type)``
via the unique constraint from PR-2. ``reply_time_seconds`` is numeric
and may legitimately appear once per response — same dedup rule applies.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from surge_quality.api.auth import require_service_token
from surge_quality.db import get_db
from surge_quality.models import Response, TelemetrySignal

router = APIRouter(prefix="/v1/quality", tags=["telemetry"])


class SignalType(str, Enum):
    """Closed enum of accepted signals. Anything else returns 422."""

    THUMBS_UP = "thumbs_up"
    THUMBS_DOWN = "thumbs_down"
    REPLY_TIME_SECONDS = "reply_time_seconds"
    DROPOFF = "dropoff"
    REASK = "reask"
    HUMAN_ESCALATION_REQUEST = "human_escalation_request"


class TelemetryIn(BaseModel):
    """Body for POST /v1/quality/telemetry."""

    response_id: int = Field(..., description="FK to surge_quality.responses.id")
    signal_type: SignalType
    value: float | None = Field(
        default=None,
        description=(
            "numeric for reply_time_seconds; 1.0 (truthy) for boolean signals "
            "where the caller wants to record an explicit truthy value"
        ),
    )
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class TelemetryOut(BaseModel):
    id: int
    response_id: int
    signal_type: SignalType
    value: float | None
    captured_at: datetime


@router.post(
    "/telemetry",
    response_model=TelemetryOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_service_token)],
)
def post_telemetry(body: TelemetryIn, db: Session = Depends(get_db)) -> TelemetryOut:
    # Validate response_id exists.
    resp = db.get(Response, body.response_id)
    if resp is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"response_id={body.response_id} not found",
        )

    signal = TelemetrySignal(
        response_id=body.response_id,
        signal_type=body.signal_type.value,
        value=body.value,
        metadata_json=body.metadata_json or {},
    )
    db.add(signal)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        # Unique constraint (response_id, signal_type) — dedup.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"telemetry signal {body.signal_type.value} already recorded for "
                f"response_id={body.response_id}"
            ),
        ) from exc
    db.refresh(signal)
    return TelemetryOut(
        id=signal.id,
        response_id=signal.response_id,
        signal_type=SignalType(signal.signal_type),
        value=signal.value,
        captured_at=signal.captured_at,
    )
