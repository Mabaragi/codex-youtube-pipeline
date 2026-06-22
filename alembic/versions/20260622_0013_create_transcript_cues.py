"""create transcript cues

Revision ID: 20260622_0013
Revises: 20260622_0012
Create Date: 2026-06-22 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260622_0013"
down_revision: str | None = "20260622_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "transcript_cues",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("transcript_id", sa.Integer(), nullable=False),
        sa.Column("cue_id", sa.String(length=64), nullable=False),
        sa.Column("cue_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("end_ms", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("source_segment_index", sa.Integer(), nullable=False),
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
        sa.CheckConstraint("cue_index >= 1", name=op.f("transcript_cues_cue_index_min")),
        sa.CheckConstraint(
            "start_ms >= 0",
            name=op.f("transcript_cues_start_ms_non_negative"),
        ),
        sa.CheckConstraint("end_ms >= start_ms", name=op.f("transcript_cues_end_ms_valid")),
        sa.CheckConstraint(
            "duration_ms >= 0",
            name=op.f("transcript_cues_duration_ms_non_negative"),
        ),
        sa.CheckConstraint(
            "source_segment_index >= 0",
            name=op.f("transcript_cues_source_segment_index_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["source_job_attempt_id"],
            ["pipeline_job_attempts.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["source_job_id"], ["pipeline_jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["transcript_id"],
            ["youtube_transcripts.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transcript_cues")),
        sa.UniqueConstraint("cue_id", name=op.f("uq_transcript_cues_cue_id")),
        sa.UniqueConstraint(
            "transcript_id",
            "cue_index",
            name=op.f("uq_transcript_cues_transcript_index"),
        ),
    )
    op.create_index(
        op.f("ix_transcript_cues_source_job_attempt_id"),
        "transcript_cues",
        ["source_job_attempt_id"],
    )
    op.create_index(
        "ix_transcript_cues_source_job_id",
        "transcript_cues",
        ["source_job_id"],
    )
    op.create_index(
        op.f("ix_transcript_cues_transcript_id"),
        "transcript_cues",
        ["transcript_id"],
    )
    op.create_index(
        "ix_transcript_cues_transcript_index",
        "transcript_cues",
        ["transcript_id", "cue_index"],
    )


def downgrade() -> None:
    op.drop_index("ix_transcript_cues_transcript_index", table_name="transcript_cues")
    op.drop_index(op.f("ix_transcript_cues_transcript_id"), table_name="transcript_cues")
    op.drop_index("ix_transcript_cues_source_job_id", table_name="transcript_cues")
    op.drop_index(
        op.f("ix_transcript_cues_source_job_attempt_id"),
        table_name="transcript_cues",
    )
    op.drop_table("transcript_cues")
