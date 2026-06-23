"""micro event v3 schema

Revision ID: 20260623_0016
Revises: 20260623_0015
Create Date: 2026-06-23 00:16:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260623_0016"
down_revision: str | None = "20260623_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "micro_event_candidates",
        sa.Column("program_mode", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "micro_event_candidates",
        sa.Column("content_kind", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "micro_event_candidates",
        sa.Column("topics", sa.JSON(), nullable=True),
    )
    op.add_column(
        "micro_event_candidates",
        sa.Column("relation_to_previous", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "micro_event_candidates",
        sa.Column("continues_to_next", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "micro_event_candidates",
        sa.Column("support_level", sa.String(length=32), nullable=True),
    )

    op.create_table(
        "micro_event_excluded_ranges",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("window_id", sa.Integer(), nullable=False),
        sa.Column("video_task_id", sa.Integer(), nullable=False),
        sa.Column("transcript_id", sa.Integer(), nullable=False),
        sa.Column("range_index", sa.Integer(), nullable=False),
        sa.Column("start_cue_id", sa.String(length=64), nullable=False),
        sa.Column("end_cue_id", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=False),
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
            "range_index >= 1",
            name=op.f("micro_event_excluded_ranges_index_min"),
        ),
        sa.ForeignKeyConstraint(
            ["transcript_id"],
            ["youtube_transcripts.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["video_task_id"],
            ["video_tasks.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["window_id"],
            ["micro_event_extraction_windows.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_micro_event_excluded_ranges")),
        sa.UniqueConstraint(
            "window_id",
            "range_index",
            name=op.f("uq_micro_event_excluded_ranges_window_index"),
        ),
    )
    op.create_index(
        "ix_micro_event_excluded_ranges_transcript_id",
        "micro_event_excluded_ranges",
        ["transcript_id"],
    )
    op.create_index(
        "ix_micro_event_excluded_ranges_video_task",
        "micro_event_excluded_ranges",
        ["video_task_id"],
    )
    op.create_index(
        "ix_micro_event_excluded_ranges_window_id",
        "micro_event_excluded_ranges",
        ["window_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_micro_event_excluded_ranges_window_id",
        table_name="micro_event_excluded_ranges",
    )
    op.drop_index(
        "ix_micro_event_excluded_ranges_video_task",
        table_name="micro_event_excluded_ranges",
    )
    op.drop_index(
        "ix_micro_event_excluded_ranges_transcript_id",
        table_name="micro_event_excluded_ranges",
    )
    op.drop_table("micro_event_excluded_ranges")

    op.drop_column("micro_event_candidates", "support_level")
    op.drop_column("micro_event_candidates", "continues_to_next")
    op.drop_column("micro_event_candidates", "relation_to_previous")
    op.drop_column("micro_event_candidates", "topics")
    op.drop_column("micro_event_candidates", "content_kind")
    op.drop_column("micro_event_candidates", "program_mode")
