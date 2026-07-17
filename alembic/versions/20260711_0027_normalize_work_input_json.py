"""normalize work item input json

Revision ID: 20260711_0027
Revises: 20260711_0026
Create Date: 2026-07-11 07:45:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260711_0027"
down_revision: str | None = "20260711_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    null_json_predicate = (
        "json_type(input_json) = 'null'"
        if connection.dialect.name == "sqlite"
        else "CAST(input_json AS TEXT) = 'null'"
    )
    connection.execute(
        sa.text(
            "UPDATE work_items SET input_json = '{}' "
            f"WHERE input_json IS NULL OR {null_json_predicate}"
        )
    )


def downgrade() -> None:
    pass
