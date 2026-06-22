"""add no transcript video task status

Revision ID: 20260622_0012
Revises: 20260619_0011
Create Date: 2026-06-22 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260622_0012"
down_revision: str | None = "20260619_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_STATUS_CHECK = (
    "status IN ('pending', 'running', 'succeeded', 'failed', "
    "'timed_out', 'skipped', 'canceled')"
)
_NEW_STATUS_CHECK = (
    "status IN ('pending', 'running', 'succeeded', 'failed', "
    "'timed_out', 'no_transcript', 'skipped', 'canceled')"
)


def upgrade() -> None:
    with op.batch_alter_table("video_tasks") as batch_op:
        batch_op.drop_constraint(op.f("video_tasks_status_allowed"), type_="check")
        batch_op.create_check_constraint(
            op.f("video_tasks_status_allowed"),
            _NEW_STATUS_CHECK,
        )
    op.execute(
        "UPDATE video_tasks "
        "SET status = 'no_transcript' "
        "WHERE status = 'failed' AND error_type = 'YouTubeTranscriptNotFound'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE video_tasks SET status = 'failed' WHERE status = 'no_transcript'"
    )
    with op.batch_alter_table("video_tasks") as batch_op:
        batch_op.drop_constraint(op.f("video_tasks_status_allowed"), type_="check")
        batch_op.create_check_constraint(
            op.f("video_tasks_status_allowed"),
            _OLD_STATUS_CHECK,
        )
