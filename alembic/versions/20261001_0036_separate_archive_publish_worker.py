"""Persist publication intent and move unfinished archive work to the worker queue."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20261001_0036"
down_revision = "20260930_0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pipeline_automation_state",
        sa.Column("publishing_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "pipeline_automation_state",
        sa.Column("publishing_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "pipeline_automation_state",
        sa.Column("publishing_reason", sa.String(500), nullable=True),
    )
    op.execute(
        "UPDATE work_items SET execution_mode = 'worker' "
        "WHERE task_type = 'archive_publish' AND execution_mode = 'inline' "
        "AND status IN ('pending', 'failed', 'timed_out', 'blocked')"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE work_items SET execution_mode = 'inline' "
        "WHERE task_type = 'archive_publish' AND execution_mode = 'worker' "
        "AND status IN ('pending', 'failed', 'timed_out', 'blocked')"
    )
    op.drop_column("pipeline_automation_state", "publishing_reason")
    op.drop_column("pipeline_automation_state", "publishing_updated_at")
    op.drop_column("pipeline_automation_state", "publishing_enabled")
