"""create prompt versions

Revision ID: 20260627_0021
Revises: 20260624_0020
Create Date: 2026-06-27 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260627_0021"
down_revision: str | None = "20260624_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "prompt_versions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("prompt_key", sa.String(length=128), nullable=False),
        sa.Column("version_label", sa.String(length=128), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("body_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'PUBLISHED', 'ARCHIVED')",
            name=op.f("prompt_versions_status_allowed"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prompt_versions")),
        sa.UniqueConstraint(
            "prompt_key",
            "version_label",
            name=op.f("uq_prompt_versions_key_label"),
        ),
    )
    op.create_index(
        op.f("ix_prompt_versions_key_status"),
        "prompt_versions",
        ["prompt_key", "status"],
        unique=False,
    )
    op.create_table(
        "prompt_active_versions",
        sa.Column("prompt_key", sa.String(length=128), nullable=False),
        sa.Column("version_id", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["prompt_versions.id"],
            name=op.f("fk_prompt_active_versions_version_id_prompt_versions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("prompt_key", name=op.f("pk_prompt_active_versions")),
    )


def downgrade() -> None:
    op.drop_table("prompt_active_versions")
    op.drop_index(op.f("ix_prompt_versions_key_status"), table_name="prompt_versions")
    op.drop_table("prompt_versions")
