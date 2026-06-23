"""add codex usage reasoning effort

Revision ID: 20260623_0017
Revises: 20260623_0016
Create Date: 2026-06-23 21:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260623_0017"
down_revision: str | None = "20260623_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "codex_run_usages",
        sa.Column("reasoning_effort", sa.String(length=32), nullable=True),
    )
    op.create_index(
        "ix_codex_run_usages_reasoning_effort",
        "codex_run_usages",
        ["reasoning_effort"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_codex_run_usages_reasoning_effort",
        table_name="codex_run_usages",
    )
    op.drop_column("codex_run_usages", "reasoning_effort")
