"""add transcript batch lock index

Revision ID: 20260619_0011
Revises: 20260619_0010
Create Date: 2026-06-19 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260619_0011"
down_revision: str | None = "20260619_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_pipeline_jobs_running_transcript_collect_batch",
        "pipeline_jobs",
        ["status"],
        unique=True,
        sqlite_where=sa.text("step = 'transcript_collect_batch' AND status = 'running'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_pipeline_jobs_running_transcript_collect_batch",
        table_name="pipeline_jobs",
    )
