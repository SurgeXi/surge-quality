"""routing_decisions table — read-only routing advice ledger

Revision ID: 0005
Revises: 0004
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "surge_quality"


def upgrade() -> None:
    op.create_table(
        "routing_decisions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("conversation_id", sa.String(length=128), nullable=True),
        sa.Column("input_message", sa.Text(), nullable=False),
        sa.Column(
            "context_json",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "identity_json",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "decision",
            sa.String(length=64),
            nullable=False,
            comment="one of surge | surge_with_claude_review | claude_primary",
        ),
        sa.Column("reasoning", sa.Text(), nullable=False),
        sa.Column(
            "factors_json",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_routing_conv_decided",
        "routing_decisions",
        ["conversation_id", "decided_at"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_routing_decided_at", "routing_decisions", ["decided_at"], schema=SCHEMA
    )
    op.create_index(
        "ix_routing_decision", "routing_decisions", ["decision"], schema=SCHEMA
    )


def downgrade() -> None:
    op.drop_index("ix_routing_decision", table_name="routing_decisions", schema=SCHEMA)
    op.drop_index("ix_routing_decided_at", table_name="routing_decisions", schema=SCHEMA)
    op.drop_index("ix_routing_conv_decided", table_name="routing_decisions", schema=SCHEMA)
    op.drop_table("routing_decisions", schema=SCHEMA)
