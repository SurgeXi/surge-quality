"""rubric_scores table — 10 axes + composite

Revision ID: 0002
Revises: 0001
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "surge_quality"

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


def upgrade() -> None:
    cols = [
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "response_id",
            sa.BigInteger(),
            sa.ForeignKey(f"{SCHEMA}.responses.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
    ]
    cols.extend(sa.Column(axis, sa.Float(), nullable=False) for axis in AXES)
    cols.extend(
        [
            sa.Column(
                "composite",
                sa.Float(),
                nullable=False,
                comment="mean of 10 axes",
            ),
            sa.Column("scorer_model", sa.String(length=128), nullable=False),
            sa.Column("raw_json", JSONB(), nullable=False),
            sa.Column(
                "scored_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        ]
    )

    op.create_table("rubric_scores", *cols, schema=SCHEMA)
    op.create_index("ix_rubric_composite", "rubric_scores", ["composite"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_index("ix_rubric_composite", table_name="rubric_scores", schema=SCHEMA)
    op.drop_table("rubric_scores", schema=SCHEMA)
