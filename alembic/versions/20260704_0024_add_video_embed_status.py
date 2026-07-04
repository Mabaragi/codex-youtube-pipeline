"""add video embed status

Revision ID: 20260704_0024
Revises: 20260702_0023
Create Date: 2026-07-04 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260704_0024"
down_revision: str | None = "20260702_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("videos") as batch_op:
        batch_op.add_column(sa.Column("is_embeddable", sa.Boolean(), nullable=True))
        batch_op.add_column(
            sa.Column("embed_status_checked_at", sa.DateTime(timezone=True), nullable=True),
        )
        batch_op.add_column(
            sa.Column("source_embed_status_api_call_id", sa.Integer(), nullable=True),
        )
        batch_op.create_foreign_key(
            "fk_videos_source_embed_status_api_call_id_external_api_calls",
            "external_api_calls",
            ["source_embed_status_api_call_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        "ix_videos_source_embed_status_api_call_id",
        "videos",
        ["source_embed_status_api_call_id"],
    )
    op.create_index("ix_videos_is_embeddable", "videos", ["is_embeddable"])


def downgrade() -> None:
    op.drop_index("ix_videos_is_embeddable", table_name="videos")
    op.drop_index("ix_videos_source_embed_status_api_call_id", table_name="videos")
    with op.batch_alter_table("videos") as batch_op:
        batch_op.drop_constraint(
            "fk_videos_source_embed_status_api_call_id_external_api_calls",
            type_="foreignkey",
        )
        batch_op.drop_column("source_embed_status_api_call_id")
        batch_op.drop_column("embed_status_checked_at")
        batch_op.drop_column("is_embeddable")
