"""SQLAlchemy ORM models for surge-quality.

The five tables match the Alembic migrations 0001-0005 row-for-row. Keeping
them in a single module keeps the package surface small for this stage of
the build; future PRs may split per-table when behaviour grows.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from surge_quality.db import Base

# --- Responses --------------------------------------------------------------


class Response(Base):
    """One Surge response captured for scoring + telemetry."""

    __tablename__ = "responses"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    response_text: Mapped[str] = mapped_column(Text, nullable=False)
    model_used: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="origin label e.g. 'pulsepoint', 'shadow', 'manual'",
    )
    identity_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    scored: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    rubric: Mapped["RubricScore | None"] = relationship(
        "RubricScore", back_populates="response", uselist=False, cascade="all, delete-orphan"
    )
    telemetry: Mapped[list["TelemetrySignal"]] = relationship(
        "TelemetrySignal", back_populates="response", cascade="all, delete-orphan"
    )
    llm_review: Mapped["LlmReview | None"] = relationship(
        "LlmReview", back_populates="response", uselist=False, cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_responses_conv_generated", "conversation_id", "generated_at"),
        Index("ix_responses_scored", "scored"),
    )


# --- Rubric scores ----------------------------------------------------------


class RubricScore(Base):
    """Ten-axis rubric output from the Hermes scorer."""

    __tablename__ = "rubric_scores"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    response_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("responses.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    # 10 axes (0-10 each)
    correctness: Mapped[float] = mapped_column(Float, nullable=False)
    tone_match: Mapped[float] = mapped_column(Float, nullable=False)
    completeness: Mapped[float] = mapped_column(Float, nullable=False)
    action_orientation: Mapped[float] = mapped_column(Float, nullable=False)
    brevity: Mapped[float] = mapped_column(Float, nullable=False)
    citation_quality: Mapped[float] = mapped_column(Float, nullable=False)
    identity_awareness: Mapped[float] = mapped_column(Float, nullable=False)
    memory_usage: Mapped[float] = mapped_column(Float, nullable=False)
    safety: Mapped[float] = mapped_column(Float, nullable=False)
    confidence_calibration: Mapped[float] = mapped_column(Float, nullable=False)

    composite: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        comment="mean of 10 axes; pre-computed for cheap dashboard queries",
    )
    scorer_model: Mapped[str] = mapped_column(String(128), nullable=False)
    raw_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, comment="raw scorer JSON for audit / re-parse"
    )
    scored_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    response: Mapped[Response] = relationship("Response", back_populates="rubric")

    __table_args__ = (Index("ix_rubric_composite", "composite"),)


# --- Telemetry signals ------------------------------------------------------


class TelemetrySignal(Base):
    """One row per customer telemetry signal attached to a response."""

    __tablename__ = "telemetry_signals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    response_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("responses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    signal_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment=(
            "one of thumbs_up | thumbs_down | reply_time_seconds | dropoff | "
            "reask | human_escalation_request"
        ),
    )
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    response: Mapped[Response] = relationship("Response", back_populates="telemetry")

    __table_args__ = (
        # Boolean signals dedup'd at the application layer using this
        # constraint as the unique key.
        UniqueConstraint("response_id", "signal_type", name="uq_response_signal"),
        Index("ix_telemetry_response_type", "response_id", "signal_type"),
    )


# --- LLM reviews ---------------------------------------------------------


class LlmReview(Base):
    """the LLM reviewer's teacher feedback for a low-scoring turn."""

    __tablename__ = "claude_reviews"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    response_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("responses.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    better_response: Mapped[str] = mapped_column(Text, nullable=False)
    what_was_wrong: Mapped[str] = mapped_column(Text, nullable=False)
    how_to_fix: Mapped[str] = mapped_column(Text, nullable=False)
    reviewer_model: Mapped[str] = mapped_column(String(128), nullable=False)
    raw_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    triggered_by_score: Mapped[float] = mapped_column(Float, nullable=False)

    response: Mapped[Response] = relationship("Response", back_populates="llm_review")


# --- Routing decisions ------------------------------------------------------


class RoutingDecision(Base):
    """One row per routing-advice call. Read-only — surge-quality does not
    execute the swap; the consumer asks SOL via ``pulsepoint_set_model``."""

    __tablename__ = "routing_decisions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    input_message: Mapped[str] = mapped_column(Text, nullable=False)
    context_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    identity_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    decision: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="one of surge | surge_with_claude_review | claude_primary",
    )
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    factors_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}", comment="per-factor inputs that produced decision"
    )
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_routing_decided_at", "decided_at"),
        Index("ix_routing_decision", "decision"),
    )
