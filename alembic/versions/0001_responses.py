"""create surge_quality schema + responses table

Revision ID: 0001
Revises:
Create Date: 2026-06-03

Per docs/PLAN.md §Postgres schema. Lives in the shared surge_brain DB
under the ``surge_quality`` schema (created idempotently by env.py).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "surge_quality"


def upgrade() -> None:
    # Schema is provisioned out-of-band by an admin role (see
    # deploy/sq_provision.sh in PR-9). The surge_quality role owns the
    # schema but does NOT have CREATE on the database, so we cannot
    # CREATE SCHEMA from inside a migration.
    op.create_table(
        "responses",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("conversation_id", sa.String(length=128), nullable=False),
        sa.Column("response_text", sa.Text(), nullable=False),
        sa.Column("model_used", sa.String(length=128), nullable=False),
        sa.Column(
            "source",
            sa.String(length=64),
            nullable=False,
            comment="origin label e.g. 'pulsepoint', 'shadow', 'manual'",
        ),
        sa.Column("identity_json", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("scored", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_responses_conv_generated",
        "responses",
        ["conversation_id", "generated_at"],
        schema=SCHEMA,
    )
    op.create_index("ix_responses_scored", "responses", ["scored"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_index("ix_responses_scored", table_name="responses", schema=SCHEMA)
    op.drop_index("ix_responses_conv_generated", table_name="responses", schema=SCHEMA)
    op.drop_table("responses", schema=SCHEMA)
    # Schema left intact — later migrations may have other tables in it.
