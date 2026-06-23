"""create codex run usages

Revision ID: 20260623_0015
Revises: 20260623_0014
Create Date: 2026-06-23 14:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260623_0015"
down_revision: str | None = "20260623_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "codex_run_usages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source", sa.String(length=128), nullable=False),
        sa.Column("operation", sa.String(length=128), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("thread_id", sa.String(length=255), nullable=True),
        sa.Column("turn_id", sa.String(length=255), nullable=True),
        sa.Column("usage_json", sa.JSON(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("cached_input_tokens", sa.Integer(), nullable=True),
        sa.Column("reasoning_output_tokens", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("error_type", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("video_id", sa.Integer(), nullable=True),
        sa.Column("video_task_id", sa.Integer(), nullable=True),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("job_attempt_id", sa.Integer(), nullable=True),
        sa.Column("transcript_id", sa.Integer(), nullable=True),
        sa.Column("window_index", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "cached_input_tokens IS NULL OR cached_input_tokens >= 0",
            name=op.f("codex_run_usages_cached_input_tokens_min"),
        ),
        sa.CheckConstraint(
            "duration_ms >= 0",
            name=op.f("codex_run_usages_duration_min"),
        ),
        sa.CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0",
            name=op.f("codex_run_usages_input_tokens_min"),
        ),
        sa.CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0",
            name=op.f("codex_run_usages_output_tokens_min"),
        ),
        sa.CheckConstraint(
            "reasoning_output_tokens IS NULL OR reasoning_output_tokens >= 0",
            name=op.f("codex_run_usages_reasoning_output_tokens_min"),
        ),
        sa.CheckConstraint(
            "status IN ('succeeded', 'failed')",
            name=op.f("codex_run_usages_status_allowed"),
        ),
        sa.CheckConstraint(
            "total_tokens IS NULL OR total_tokens >= 0",
            name=op.f("codex_run_usages_total_tokens_min"),
        ),
        sa.ForeignKeyConstraint(
            ["job_attempt_id"],
            ["pipeline_job_attempts.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["job_id"], ["pipeline_jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["transcript_id"],
            ["youtube_transcripts.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["video_task_id"], ["video_tasks.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_codex_run_usages")),
    )
    op.create_index(
        "ix_codex_run_usages_created_at",
        "codex_run_usages",
        ["created_at", "id"],
    )
    op.create_index(
        "ix_codex_run_usages_job_id",
        "codex_run_usages",
        ["job_id"],
    )
    op.create_index(
        "ix_codex_run_usages_model",
        "codex_run_usages",
        ["model"],
    )
    op.create_index(
        "ix_codex_run_usages_source",
        "codex_run_usages",
        ["source"],
    )
    op.create_index(
        "ix_codex_run_usages_status",
        "codex_run_usages",
        ["status"],
    )
    op.create_index(
        "ix_codex_run_usages_video_task_id",
        "codex_run_usages",
        ["video_task_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_codex_run_usages_video_task_id", table_name="codex_run_usages")
    op.drop_index("ix_codex_run_usages_status", table_name="codex_run_usages")
    op.drop_index("ix_codex_run_usages_source", table_name="codex_run_usages")
    op.drop_index("ix_codex_run_usages_model", table_name="codex_run_usages")
    op.drop_index("ix_codex_run_usages_job_id", table_name="codex_run_usages")
    op.drop_index("ix_codex_run_usages_created_at", table_name="codex_run_usages")
    op.drop_table("codex_run_usages")
