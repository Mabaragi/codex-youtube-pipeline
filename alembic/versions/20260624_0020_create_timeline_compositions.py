"""create timeline compositions

Revision ID: 20260624_0020
Revises: 20260624_0019
Create Date: 2026-06-24 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260624_0020"
down_revision: str | None = "20260624_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "timeline_compositions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("video_task_id", sa.Integer(), nullable=False),
        sa.Column("video_id", sa.Integer(), nullable=False),
        sa.Column("source_micro_event_task_id", sa.Integer(), nullable=False),
        sa.Column("source_micro_event_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("copy_style", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("reasoning_effort", sa.String(length=32), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("display_title", sa.Text(), nullable=False),
        sa.Column("display_summary", sa.Text(), nullable=False),
        sa.Column("main_topics", sa.JSON(), nullable=False),
        sa.Column("output_json", sa.JSON(), nullable=False),
        sa.Column("validation_warnings", sa.JSON(), nullable=False),
        sa.Column("source_job_id", sa.Integer(), nullable=True),
        sa.Column("source_job_attempt_id", sa.Integer(), nullable=True),
        sa.Column("codex_thread_id", sa.String(length=255), nullable=True),
        sa.Column("codex_turn_id", sa.String(length=255), nullable=True),
        sa.Column("raw_response_text", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["video_task_id"], ["video_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_micro_event_task_id"],
            ["video_tasks.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["source_job_id"], ["pipeline_jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["source_job_attempt_id"],
            ["pipeline_job_attempts.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("video_task_id", name="uq_timeline_compositions_video_task"),
    )
    op.create_index(
        "ix_timeline_compositions_video_id",
        "timeline_compositions",
        ["video_id"],
        unique=False,
    )
    op.create_index(
        "ix_timeline_compositions_source_micro_event_task",
        "timeline_compositions",
        ["source_micro_event_task_id"],
        unique=False,
    )
    op.create_index(
        "ix_timeline_compositions_source_job",
        "timeline_compositions",
        ["source_job_id"],
        unique=False,
    )

    op.create_table(
        "timeline_blocks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("composition_id", sa.Integer(), nullable=False),
        sa.Column("block_id", sa.String(length=64), nullable=False),
        sa.Column("block_index", sa.Integer(), nullable=False),
        sa.Column("block_type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("display_title", sa.Text(), nullable=False),
        sa.Column("display_summary", sa.Text(), nullable=False),
        sa.Column("episode_ids", sa.JSON(), nullable=False),
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
        sa.CheckConstraint("block_index >= 1", name="timeline_blocks_index_min"),
        sa.ForeignKeyConstraint(
            ["composition_id"],
            ["timeline_compositions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("composition_id", "block_id", name="uq_timeline_blocks_key"),
    )
    op.create_index(
        "ix_timeline_blocks_composition",
        "timeline_blocks",
        ["composition_id", "block_index"],
        unique=False,
    )

    op.create_table(
        "timeline_episodes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("composition_id", sa.Integer(), nullable=False),
        sa.Column("episode_id", sa.String(length=64), nullable=False),
        sa.Column("episode_index", sa.Integer(), nullable=False),
        sa.Column("parent_block_id", sa.String(length=64), nullable=False),
        sa.Column("start_micro_event_candidate_id", sa.Integer(), nullable=True),
        sa.Column("end_micro_event_candidate_id", sa.Integer(), nullable=True),
        sa.Column("program_mode", sa.String(length=32), nullable=False),
        sa.Column("primary_content_kind", sa.String(length=32), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("display_title", sa.Text(), nullable=False),
        sa.Column("display_summary", sa.Text(), nullable=False),
        sa.Column("topics", sa.JSON(), nullable=False),
        sa.Column("viewer_tags", sa.JSON(), nullable=False),
        sa.Column("highlight_micro_event_candidate_ids", sa.JSON(), nullable=False),
        sa.Column("visibility", sa.String(length=32), nullable=False),
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
        sa.CheckConstraint("episode_index >= 1", name="timeline_episodes_index_min"),
        sa.ForeignKeyConstraint(
            ["composition_id"],
            ["timeline_compositions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["start_micro_event_candidate_id"],
            ["micro_event_candidates.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["end_micro_event_candidate_id"],
            ["micro_event_candidates.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("composition_id", "episode_id", name="uq_timeline_episodes_key"),
    )
    op.create_index(
        "ix_timeline_episodes_composition",
        "timeline_episodes",
        ["composition_id", "episode_index"],
        unique=False,
    )

    op.create_table(
        "timeline_topic_clusters",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("composition_id", sa.Integer(), nullable=False),
        sa.Column("topic_id", sa.String(length=64), nullable=False),
        sa.Column("topic_index", sa.Integer(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("display_label", sa.Text(), nullable=False),
        sa.Column("episode_ids", sa.JSON(), nullable=False),
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
        sa.CheckConstraint("topic_index >= 1", name="timeline_topics_index_min"),
        sa.ForeignKeyConstraint(
            ["composition_id"],
            ["timeline_compositions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("composition_id", "topic_id", name="uq_timeline_topics_key"),
    )
    op.create_index(
        "ix_timeline_topics_composition",
        "timeline_topic_clusters",
        ["composition_id", "topic_index"],
        unique=False,
    )

    op.create_table(
        "timeline_review_flags",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("composition_id", sa.Integer(), nullable=False),
        sa.Column("flag_index", sa.Integer(), nullable=False),
        sa.Column("start_micro_event_candidate_id", sa.Integer(), nullable=True),
        sa.Column("end_micro_event_candidate_id", sa.Integer(), nullable=True),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
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
        sa.CheckConstraint("flag_index >= 1", name="timeline_review_flags_index_min"),
        sa.ForeignKeyConstraint(
            ["composition_id"],
            ["timeline_compositions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["start_micro_event_candidate_id"],
            ["micro_event_candidates.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["end_micro_event_candidate_id"],
            ["micro_event_candidates.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_timeline_review_flags_composition",
        "timeline_review_flags",
        ["composition_id", "flag_index"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_timeline_review_flags_composition", table_name="timeline_review_flags")
    op.drop_table("timeline_review_flags")
    op.drop_index("ix_timeline_topics_composition", table_name="timeline_topic_clusters")
    op.drop_table("timeline_topic_clusters")
    op.drop_index("ix_timeline_episodes_composition", table_name="timeline_episodes")
    op.drop_table("timeline_episodes")
    op.drop_index("ix_timeline_blocks_composition", table_name="timeline_blocks")
    op.drop_table("timeline_blocks")
    op.drop_index("ix_timeline_compositions_source_job", table_name="timeline_compositions")
    op.drop_index(
        "ix_timeline_compositions_source_micro_event_task",
        table_name="timeline_compositions",
    )
    op.drop_index("ix_timeline_compositions_video_id", table_name="timeline_compositions")
    op.drop_table("timeline_compositions")
