"""make youtube channel id unique

Revision ID: 20260616_0006
Revises: 20260616_0005
Create Date: 2026-06-16 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260616_0006"
down_revision: str | None = "20260616_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("channels") as batch_op:
        batch_op.create_unique_constraint(
            op.f("uq_channels_youtube_channel_id"),
            ["youtube_channel_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("channels") as batch_op:
        batch_op.drop_constraint(
            op.f("uq_channels_youtube_channel_id"),
            type_="unique",
        )
