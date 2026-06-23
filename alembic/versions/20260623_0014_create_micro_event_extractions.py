"""create micro event extractions

Revision ID: 20260623_0014
Revises: 20260622_0013
Create Date: 2026-06-23 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260623_0014"
down_revision: str | None = "20260622_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "micro_event_extraction_windows",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("video_task_id", sa.Integer(), nullable=False),
        sa.Column("video_id", sa.Integer(), nullable=False),
        sa.Column("transcript_id", sa.Integer(), nullable=False),
        sa.Column("window_index", sa.Integer(), nullable=False),
        sa.Column("start_cue_id", sa.String(length=64), nullable=False),
        sa.Column("end_cue_id", sa.String(length=64), nullable=False),
        sa.Column("cue_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("carry_out_unfinished", sa.Boolean(), nullable=False),
        sa.Column("codex_thread_id", sa.String(length=255), nullable=True),
        sa.Column("codex_turn_id", sa.String(length=255), nullable=True),
        sa.Column("raw_response_text", sa.Text(), nullable=True),
        sa.Column("parsed_response_json", sa.JSON(), nullable=True),
        sa.Column("validation_error", sa.Text(), nullable=True),
        sa.Column("source_job_id", sa.Integer(), nullable=True),
        sa.Column("source_job_attempt_id", sa.Integer(), nullable=True),
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
        sa.CheckConstraint("window_index >= 1", name=op.f("micro_event_windows_index_min")),
        sa.CheckConstraint("cue_count >= 1", name=op.f("micro_event_windows_cue_count_min")),
        sa.CheckConstraint(
            "status IN ('succeeded', 'failed')",
            name=op.f("micro_event_windows_status_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["source_job_attempt_id"],
            ["pipeline_job_attempts.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["source_job_id"], ["pipeline_jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["transcript_id"], ["youtube_transcripts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["video_task_id"], ["video_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_micro_event_extraction_windows")),
        sa.UniqueConstraint(
            "video_task_id",
            "window_index",
            name=op.f("uq_micro_event_windows_task_index"),
        ),
    )
    op.create_index(
        op.f("ix_micro_event_extraction_windows_source_job_attempt_id"),
        "micro_event_extraction_windows",
        ["source_job_attempt_id"],
    )
    op.create_index(
        "ix_micro_event_windows_source_job_id",
        "micro_event_extraction_windows",
        ["source_job_id"],
    )
    op.create_index(
        "ix_micro_event_windows_transcript_id",
        "micro_event_extraction_windows",
        ["transcript_id"],
    )
    op.create_index(
        "ix_micro_event_windows_video_id",
        "micro_event_extraction_windows",
        ["video_id"],
    )
    op.create_index(
        "ix_micro_event_windows_video_task",
        "micro_event_extraction_windows",
        ["video_task_id", "window_index"],
    )

    op.create_table(
        "micro_event_candidates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("window_id", sa.Integer(), nullable=False),
        sa.Column("video_task_id", sa.Integer(), nullable=False),
        sa.Column("transcript_id", sa.Integer(), nullable=False),
        sa.Column("candidate_index", sa.Integer(), nullable=False),
        sa.Column("activity", sa.String(length=32), nullable=False),
        sa.Column("event", sa.Text(), nullable=False),
        sa.Column("start_cue_id", sa.String(length=64), nullable=False),
        sa.Column("end_cue_id", sa.String(length=64), nullable=False),
        sa.Column("evidence_cue_ids", sa.JSON(), nullable=False),
        sa.Column("boundary_before", sa.Boolean(), nullable=False),
        sa.Column("boundary_after", sa.Boolean(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
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
            "candidate_index >= 1",
            name=op.f("micro_event_candidates_index_min"),
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name=op.f("micro_event_candidates_confidence_range"),
        ),
        sa.ForeignKeyConstraint(["transcript_id"], ["youtube_transcripts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["video_task_id"], ["video_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["window_id"],
            ["micro_event_extraction_windows.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_micro_event_candidates")),
        sa.UniqueConstraint(
            "window_id",
            "candidate_index",
            name=op.f("uq_micro_event_candidates_window_index"),
        ),
    )
    op.create_index(
        "ix_micro_event_candidates_transcript_id",
        "micro_event_candidates",
        ["transcript_id"],
    )
    op.create_index(
        "ix_micro_event_candidates_video_task",
        "micro_event_candidates",
        ["video_task_id"],
    )
    op.create_index(
        "ix_micro_event_candidates_window_id",
        "micro_event_candidates",
        ["window_id"],
    )

    op.create_table(
        "asr_correction_candidates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("window_id", sa.Integer(), nullable=False),
        sa.Column("video_task_id", sa.Integer(), nullable=False),
        sa.Column("transcript_id", sa.Integer(), nullable=False),
        sa.Column("candidate_index", sa.Integer(), nullable=False),
        sa.Column("original", sa.Text(), nullable=False),
        sa.Column("suggested", sa.Text(), nullable=False),
        sa.Column("correction_type", sa.String(length=32), nullable=False),
        sa.Column("apply_scope", sa.String(length=32), nullable=False),
        sa.Column("evidence_cue_ids", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
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
            "candidate_index >= 1",
            name=op.f("asr_correction_candidates_index_min"),
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name=op.f("asr_correction_candidates_confidence_range"),
        ),
        sa.ForeignKeyConstraint(["transcript_id"], ["youtube_transcripts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["video_task_id"], ["video_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["window_id"],
            ["micro_event_extraction_windows.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_asr_correction_candidates")),
        sa.UniqueConstraint(
            "window_id",
            "candidate_index",
            name=op.f("uq_asr_correction_candidates_window_index"),
        ),
    )
    op.create_index(
        "ix_asr_correction_candidates_transcript_id",
        "asr_correction_candidates",
        ["transcript_id"],
    )
    op.create_index(
        "ix_asr_correction_candidates_video_task",
        "asr_correction_candidates",
        ["video_task_id"],
    )
    op.create_index(
        "ix_asr_correction_candidates_window_id",
        "asr_correction_candidates",
        ["window_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_asr_correction_candidates_window_id",
        table_name="asr_correction_candidates",
    )
    op.drop_index(
        "ix_asr_correction_candidates_video_task",
        table_name="asr_correction_candidates",
    )
    op.drop_index(
        "ix_asr_correction_candidates_transcript_id",
        table_name="asr_correction_candidates",
    )
    op.drop_table("asr_correction_candidates")
    op.drop_index(
        "ix_micro_event_candidates_window_id",
        table_name="micro_event_candidates",
    )
    op.drop_index(
        "ix_micro_event_candidates_video_task",
        table_name="micro_event_candidates",
    )
    op.drop_index(
        "ix_micro_event_candidates_transcript_id",
        table_name="micro_event_candidates",
    )
    op.drop_table("micro_event_candidates")
    op.drop_index(
        "ix_micro_event_windows_video_task",
        table_name="micro_event_extraction_windows",
    )
    op.drop_index(
        "ix_micro_event_windows_video_id",
        table_name="micro_event_extraction_windows",
    )
    op.drop_index(
        "ix_micro_event_windows_transcript_id",
        table_name="micro_event_extraction_windows",
    )
    op.drop_index(
        "ix_micro_event_windows_source_job_id",
        table_name="micro_event_extraction_windows",
    )
    op.drop_index(
        op.f("ix_micro_event_extraction_windows_source_job_attempt_id"),
        table_name="micro_event_extraction_windows",
    )
    op.drop_table("micro_event_extraction_windows")
