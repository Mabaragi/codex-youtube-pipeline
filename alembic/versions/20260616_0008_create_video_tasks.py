"""create video tasks

Revision ID: 20260616_0008
Revises: 20260616_0007
Create Date: 2026-06-16 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260616_0008"
down_revision: str | None = "20260616_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "video_tasks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("video_id", sa.Integer(), nullable=False),
        sa.Column("task_name", sa.String(length=64), nullable=False),
        sa.Column("task_version", sa.String(length=64), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("worker_id", sa.String(length=255), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("job_attempt_id", sa.Integer(), nullable=True),
        sa.Column("output_transcript_id", sa.Integer(), nullable=True),
        sa.Column("output_json", sa.JSON(), nullable=True),
        sa.Column("error_type", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed', "
            "'timed_out', 'skipped', 'canceled')",
            name=op.f("video_tasks_status_allowed"),
        ),
        sa.CheckConstraint(
            "timeout_seconds >= 1",
            name=op.f("video_tasks_timeout_seconds_min"),
        ),
        sa.ForeignKeyConstraint(
            ["job_attempt_id"],
            ["pipeline_job_attempts.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["job_id"], ["pipeline_jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["output_transcript_id"],
            ["youtube_transcripts.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "video_id",
            "task_name",
            "task_version",
            "input_hash",
            name=op.f("uq_video_tasks_video_task_version_hash"),
        ),
    )
    op.create_index(op.f("ix_video_tasks_input_hash"), "video_tasks", ["input_hash"])
    op.create_index(op.f("ix_video_tasks_job_attempt_id"), "video_tasks", ["job_attempt_id"])
    op.create_index(op.f("ix_video_tasks_job_id"), "video_tasks", ["job_id"])
    op.create_index(
        op.f("ix_video_tasks_output_transcript_id"),
        "video_tasks",
        ["output_transcript_id"],
    )
    op.create_index(op.f("ix_video_tasks_status"), "video_tasks", ["status"])
    op.create_index("ix_video_tasks_task_status", "video_tasks", ["task_name", "status"])
    op.create_index(op.f("ix_video_tasks_video_id"), "video_tasks", ["video_id"])
    op.create_index("ix_video_tasks_video_task", "video_tasks", ["video_id", "task_name"])


def downgrade() -> None:
    op.drop_index("ix_video_tasks_video_task", table_name="video_tasks")
    op.drop_index(op.f("ix_video_tasks_video_id"), table_name="video_tasks")
    op.drop_index("ix_video_tasks_task_status", table_name="video_tasks")
    op.drop_index(op.f("ix_video_tasks_status"), table_name="video_tasks")
    op.drop_index(op.f("ix_video_tasks_output_transcript_id"), table_name="video_tasks")
    op.drop_index(op.f("ix_video_tasks_job_id"), table_name="video_tasks")
    op.drop_index(op.f("ix_video_tasks_job_attempt_id"), table_name="video_tasks")
    op.drop_index(op.f("ix_video_tasks_input_hash"), table_name="video_tasks")
    op.drop_table("video_tasks")
