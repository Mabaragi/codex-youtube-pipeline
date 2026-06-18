"""create operation_events table

Revision ID: 20260619_0010
Revises: 20260618_0009
Create Date: 2026-06-19 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260619_0010"
down_revision: str | None = "20260618_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "operation_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("message", sa.String(length=500), nullable=False),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=128), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("job_attempt_id", sa.Integer(), nullable=True),
        sa.Column("video_task_id", sa.Integer(), nullable=True),
        sa.Column("channel_id", sa.Integer(), nullable=True),
        sa.Column("video_id", sa.Integer(), nullable=True),
        sa.Column("external_api_call_id", sa.Integer(), nullable=True),
        sa.Column("subject_type", sa.String(length=64), nullable=True),
        sa.Column("subject_id", sa.Integer(), nullable=True),
        sa.Column("external_key", sa.String(length=255), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("error_type", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "severity IN ('info', 'warning', 'error')",
            name="ck_operation_events_severity",
        ),
        sa.CheckConstraint(
            "actor_type IN ('manual_api', 'retry_executor', 'system')",
            name="ck_operation_events_actor_type",
        ),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["external_api_call_id"],
            ["external_api_calls.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["job_attempt_id"],
            ["pipeline_job_attempts.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["job_id"], ["pipeline_jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["video_task_id"], ["video_tasks.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_operation_events_correlation_id", "operation_events", ["correlation_id"])
    op.create_index("ix_operation_events_event_type", "operation_events", ["event_type"])
    op.create_index("ix_operation_events_job_id", "operation_events", ["job_id"])
    op.create_index("ix_operation_events_occurred_at", "operation_events", ["occurred_at"])
    op.create_index("ix_operation_events_severity", "operation_events", ["severity"])
    op.create_index(
        "ix_operation_events_subject",
        "operation_events",
        ["subject_type", "subject_id"],
    )
    op.create_index("ix_operation_events_video_task_id", "operation_events", ["video_task_id"])


def downgrade() -> None:
    op.drop_index("ix_operation_events_video_task_id", table_name="operation_events")
    op.drop_index("ix_operation_events_subject", table_name="operation_events")
    op.drop_index("ix_operation_events_severity", table_name="operation_events")
    op.drop_index("ix_operation_events_occurred_at", table_name="operation_events")
    op.drop_index("ix_operation_events_job_id", table_name="operation_events")
    op.drop_index("ix_operation_events_event_type", table_name="operation_events")
    op.drop_index("ix_operation_events_correlation_id", table_name="operation_events")
    op.drop_table("operation_events")
