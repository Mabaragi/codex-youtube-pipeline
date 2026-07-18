"""add durable publication profile cutovers

Revision ID: 20260718_0033
Revises: 20260718_0032
Create Date: 2026-07-18 09:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260718_0033"
down_revision: str | None = "20260718_0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "publish_profile_cutovers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("request_key", sa.String(length=64), nullable=False),
        sa.Column("open_key", sa.String(length=255), nullable=True),
        sa.Column("streamer_id", sa.Integer(), nullable=False),
        sa.Column("source_profile_id", sa.Integer(), nullable=False),
        sa.Column("target_profile_id", sa.Integer(), nullable=False),
        sa.Column("source_profile_revision_id", sa.Integer(), nullable=False),
        sa.Column("target_profile_revision_id", sa.Integer(), nullable=False),
        sa.Column("source_route_id", sa.Integer(), nullable=False),
        sa.Column("target_route_id", sa.Integer(), nullable=False),
        sa.Column("publish_mode", sa.String(length=16), nullable=False),
        sa.Column("environment", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("artifact_ids_json", sa.Text(), nullable=False),
        sa.Column("operator_reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("last_completed_step", sa.String(length=32), nullable=True),
        sa.Column("target_publication_id", sa.Integer(), nullable=True),
        sa.Column("source_publication_id", sa.Integer(), nullable=True),
        sa.Column("target_pointer_published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("streamer_assigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_pointer_published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_step", sa.String(length=32), nullable=True),
        sa.Column("last_error_code", sa.String(length=128), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
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
        sa.CheckConstraint(
            "status IN ('preparing','prepared','target_pointer_published',"
            "'streamer_assigned','source_ready','completed','failed')",
            name="publish_profile_cutovers_status_allowed",
        ),
        sa.CheckConstraint(
            "publish_mode IN ('prod','dev')",
            name="publish_profile_cutovers_mode_allowed",
        ),
        sa.ForeignKeyConstraint(["streamer_id"], ["streamers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["source_profile_id"], ["publish_profiles.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["target_profile_id"], ["publish_profiles.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_profile_revision_id"],
            ["publish_profile_revisions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_profile_revision_id"],
            ["publish_profile_revisions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_route_id"], ["publish_profile_routes.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["target_route_id"], ["publish_profile_routes.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["target_publication_id"], ["archive_publications.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_publication_id"], ["archive_publications.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "request_key",
            name="uq_publish_profile_cutovers_request_key",
        ),
        sa.UniqueConstraint(
            "open_key",
            name="uq_publish_profile_cutovers_open_key",
        ),
    )
    op.create_index(
        "ix_publish_profile_cutovers_streamer_status",
        "publish_profile_cutovers",
        ["streamer_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_publish_profile_cutovers_streamer_status",
        table_name="publish_profile_cutovers",
    )
    op.drop_table("publish_profile_cutovers")
