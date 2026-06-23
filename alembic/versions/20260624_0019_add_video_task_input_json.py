"""add video task input json

Revision ID: 20260624_0019
Revises: 20260623_0018
Create Date: 2026-06-24 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260624_0019"
down_revision: str | None = "20260623_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("video_tasks", sa.Column("input_json", sa.JSON(), nullable=True))
    op.create_index(
        "ix_video_tasks_pending_claim",
        "video_tasks",
        ["task_name", "status", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_video_tasks_pending_claim", table_name="video_tasks")
    op.drop_column("video_tasks", "input_json")
