"""telemetry_signals table — customer-facing signals per response

Revision ID: 0003
Revises: 0002
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "surge_quality"


def upgrade() -> None:
    op.create_table(
        "telemetry_signals",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "response_id",
            sa.BigInteger(),
            sa.ForeignKey(f"{SCHEMA}.responses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "signal_type",
            sa.String(length=64),
            nullable=False,
            comment=(
                "one of thumbs_up | thumbs_down | reply_time_seconds | "
                "dropoff | reask | human_escalation_request"
            ),
        ),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column(
            "metadata_json",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "response_id", "signal_type", name="uq_response_signal"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_telemetry_response_type",
        "telemetry_signals",
        ["response_id", "signal_type"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_telemetry_response_type", table_name="telemetry_signals", schema=SCHEMA
    )
    op.drop_table("telemetry_signals", schema=SCHEMA)
