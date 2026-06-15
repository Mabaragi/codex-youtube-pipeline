"""create streamers and channels

Revision ID: 20260615_0002
Revises: 20260615_0001
Create Date: 2026-06-15 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260615_0002"
down_revision: str | None = "20260615_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "streamers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_streamers")),
    )
    op.create_table(
        "channels",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("streamer_id", sa.Integer(), nullable=False),
        sa.Column("handle", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("youtube_channel_id", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(
            ["streamer_id"],
            ["streamers.id"],
            name=op.f("fk_channels_streamer_id_streamers"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_channels")),
    )
    op.create_index(op.f("ix_channels_streamer_id"), "channels", ["streamer_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_channels_streamer_id"), table_name="channels")
    op.drop_table("channels")
    op.drop_table("streamers")
