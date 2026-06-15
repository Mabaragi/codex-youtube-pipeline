"""create youtube transcripts

Revision ID: 20260615_0001
Revises:
Create Date: 2026-06-15 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260615_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "youtube_transcripts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("video_id", sa.String(length=11), nullable=False),
        sa.Column("language", sa.String(length=128), nullable=False),
        sa.Column("language_code", sa.String(length=32), nullable=False),
        sa.Column("is_generated", sa.Boolean(), nullable=False),
        sa.Column("requested_languages", sa.JSON(), nullable=False),
        sa.Column("preserve_formatting", sa.Boolean(), nullable=False),
        sa.Column("storage_bucket", sa.String(length=255), nullable=False),
        sa.Column("storage_object_name", sa.Text(), nullable=False),
        sa.Column("storage_uri", sa.Text(), nullable=False),
        sa.Column("response_sha256", sa.String(length=64), nullable=False),
        sa.Column("segment_count", sa.Integer(), nullable=False),
        sa.Column("text_length", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "segment_count >= 0",
            name=op.f("ck_youtube_transcripts_segment_count_non_negative"),
        ),
        sa.CheckConstraint(
            "text_length >= 0",
            name=op.f("ck_youtube_transcripts_text_length_non_negative"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_youtube_transcripts")),
        sa.UniqueConstraint(
            "storage_object_name",
            name=op.f("uq_youtube_transcripts_storage_object_name"),
        ),
    )
    op.create_index(
        op.f("ix_youtube_transcripts_language_code"),
        "youtube_transcripts",
        ["language_code"],
        unique=False,
    )
    op.create_index(
        op.f("ix_youtube_transcripts_video_id"),
        "youtube_transcripts",
        ["video_id"],
        unique=False,
    )
    op.create_index(
        "ix_youtube_transcripts_video_id_language_code",
        "youtube_transcripts",
        ["video_id", "language_code"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_youtube_transcripts_video_id_language_code", table_name="youtube_transcripts")
    op.drop_index(op.f("ix_youtube_transcripts_video_id"), table_name="youtube_transcripts")
    op.drop_index(op.f("ix_youtube_transcripts_language_code"), table_name="youtube_transcripts")
    op.drop_table("youtube_transcripts")
