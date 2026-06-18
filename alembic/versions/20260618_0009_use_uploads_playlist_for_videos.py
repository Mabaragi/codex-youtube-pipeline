"""use uploads playlist for videos

Revision ID: 20260618_0009
Revises: 20260616_0008
Create Date: 2026-06-18 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260618_0009"
down_revision: str | None = "20260616_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("channels") as batch_op:
        batch_op.add_column(sa.Column("uploads_playlist_id", sa.String(length=255), nullable=True))
        batch_op.create_unique_constraint(
            op.f("uq_channels_uploads_playlist_id"),
            ["uploads_playlist_id"],
        )

    with op.batch_alter_table("videos") as batch_op:
        batch_op.drop_index(op.f("ix_videos_source_search_api_call_id"))
        batch_op.drop_constraint(op.f("videos_view_count_non_negative"), type_="check")
        batch_op.drop_constraint(op.f("videos_like_count_non_negative"), type_="check")
        batch_op.drop_constraint(op.f("videos_comment_count_non_negative"), type_="check")
        batch_op.alter_column(
            "source_search_api_call_id",
            new_column_name="source_listing_api_call_id",
            existing_type=sa.Integer(),
            existing_nullable=True,
        )
        batch_op.drop_column("privacy_status")
        batch_op.drop_column("upload_status")
        batch_op.drop_column("live_broadcast_content")
        batch_op.drop_column("view_count")
        batch_op.drop_column("like_count")
        batch_op.drop_column("comment_count")
    op.create_index(
        op.f("ix_videos_source_listing_api_call_id"),
        "videos",
        ["source_listing_api_call_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_videos_source_listing_api_call_id"), table_name="videos")
    with op.batch_alter_table("videos") as batch_op:
        batch_op.add_column(sa.Column("comment_count", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("like_count", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("view_count", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("live_broadcast_content", sa.String(length=64), nullable=True)
        )
        batch_op.add_column(sa.Column("upload_status", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("privacy_status", sa.String(length=64), nullable=True))
        batch_op.alter_column(
            "source_listing_api_call_id",
            new_column_name="source_search_api_call_id",
            existing_type=sa.Integer(),
            existing_nullable=True,
        )
        batch_op.create_check_constraint(
            op.f("videos_view_count_non_negative"),
            "view_count IS NULL OR view_count >= 0",
        )
        batch_op.create_check_constraint(
            op.f("videos_like_count_non_negative"),
            "like_count IS NULL OR like_count >= 0",
        )
        batch_op.create_check_constraint(
            op.f("videos_comment_count_non_negative"),
            "comment_count IS NULL OR comment_count >= 0",
        )
    op.create_index(
        op.f("ix_videos_source_search_api_call_id"),
        "videos",
        ["source_search_api_call_id"],
        unique=False,
    )

    with op.batch_alter_table("channels") as batch_op:
        batch_op.drop_constraint(op.f("uq_channels_uploads_playlist_id"), type_="unique")
        batch_op.drop_column("uploads_playlist_id")
