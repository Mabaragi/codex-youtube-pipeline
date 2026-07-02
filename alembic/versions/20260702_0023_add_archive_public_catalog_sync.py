"""Add archive public catalog sync status."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260702_0023"
down_revision: str | Sequence[str] | None = "20260627_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "archive_video_artifacts",
        sa.Column("public_catalog_synced_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "archive_video_artifacts",
        sa.Column("public_catalog_sync_error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("archive_video_artifacts", "public_catalog_sync_error")
    op.drop_column("archive_video_artifacts", "public_catalog_synced_at")
