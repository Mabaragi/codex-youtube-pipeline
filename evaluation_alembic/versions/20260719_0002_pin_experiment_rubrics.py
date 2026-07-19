"""pin evaluation rubric versions

Revision ID: 20260719_0002
Revises: 20260718_0001
Create Date: 2026-07-19 18:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260719_0002"
down_revision: str | Sequence[str] | None = "20260718_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "evaluation_experiments",
        sa.Column(
            "micro_rubric_version",
            sa.String(length=32),
            server_default=sa.text("'micro-v2'"),
            nullable=False,
        ),
    )
    op.add_column(
        "evaluation_experiments",
        sa.Column(
            "timeline_rubric_version",
            sa.String(length=32),
            server_default=sa.text("'timeline-v1'"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("evaluation_experiments", "timeline_rubric_version")
    op.drop_column("evaluation_experiments", "micro_rubric_version")
