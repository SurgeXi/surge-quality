# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""LLM reviewer feedback table — teacher feedback for low-scoring turns.

Creates the physical ``claude_reviews`` table. The table name is a stable
schema identifier retained verbatim so deployed databases created by this
revision continue to match; the ORM class that maps it reads as the generic
``LlmReview``.

Revision ID: 0004
Revises: 0003
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "surge_quality"


def upgrade() -> None:
    op.create_table(
        "claude_reviews",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "response_id",
            sa.BigInteger(),
            sa.ForeignKey(f"{SCHEMA}.responses.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("better_response", sa.Text(), nullable=False),
        sa.Column("what_was_wrong", sa.Text(), nullable=False),
        sa.Column("how_to_fix", sa.Text(), nullable=False),
        sa.Column("reviewer_model", sa.String(length=128), nullable=False),
        sa.Column("raw_json", JSONB(), nullable=False),
        sa.Column(
            "reviewed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("triggered_by_score", sa.Float(), nullable=False),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("claude_reviews", schema=SCHEMA)
