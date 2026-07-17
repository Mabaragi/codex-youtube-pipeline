"""add persistent pipeline runtime drain state

Revision ID: 20260714_0030
Revises: 20260713_0029
Create Date: 2026-07-14 02:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260714_0030"
down_revision: str | None = "20260713_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("pipeline_automation_state") as batch_op:
        batch_op.add_column(
            sa.Column(
                "runtime_state",
                sa.String(length=16),
                nullable=False,
                server_default="active",
            )
        )
        batch_op.add_column(
            sa.Column("drain_requested_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("drain_reason", sa.String(length=255), nullable=True)
        )
        batch_op.create_check_constraint(
            "pipeline_automation_runtime_state_allowed",
            "runtime_state IN ('active', 'draining', 'stopped')",
        )


def downgrade() -> None:
    with op.batch_alter_table("pipeline_automation_state") as batch_op:
        batch_op.drop_constraint(
            "pipeline_automation_runtime_state_allowed",
            type_="check",
        )
        batch_op.drop_column("drain_reason")
        batch_op.drop_column("drain_requested_at")
        batch_op.drop_column("runtime_state")
