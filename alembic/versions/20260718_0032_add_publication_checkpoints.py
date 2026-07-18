"""add canonical artifacts and multi-destination publication checkpoints

Revision ID: 20260718_0032
Revises: 20260718_0031
Create Date: 2026-07-18 04:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260718_0032"
down_revision: str | None = "20260718_0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("archive_video_artifacts") as batch_op:
        batch_op.add_column(sa.Column("build_key", sa.String(length=255), nullable=True))
        batch_op.add_column(
            sa.Column(
                "artifact_status",
                sa.String(length=32),
                server_default="pending",
                nullable=False,
            )
        )
        batch_op.add_column(sa.Column("artifact_store_ref", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("artifact_key", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("unavailable_code", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("unavailable_detail", sa.Text(), nullable=True))
        batch_op.create_check_constraint(
            "archive_video_artifacts_artifact_status_allowed",
            "artifact_status IN ('pending','ready','failed','unavailable')",
        )
        batch_op.create_unique_constraint(
            "uq_archive_video_artifacts_build_key",
            ["build_key"],
        )

    _create_object_delivery_table()
    _create_catalog_delivery_table()
    _create_publication_tables()


def downgrade() -> None:
    op.drop_table("archive_publication_deliveries")
    op.drop_table("archive_publication_artifacts")
    op.drop_index("ix_archive_publications_route_id", table_name="archive_publications")
    op.drop_table("archive_publications")
    op.drop_index(
        "ix_archive_artifact_catalog_deliveries_artifact_id",
        table_name="archive_artifact_catalog_deliveries",
    )
    op.drop_table("archive_artifact_catalog_deliveries")
    op.drop_index(
        "ix_archive_artifact_object_deliveries_artifact_id",
        table_name="archive_artifact_object_deliveries",
    )
    op.drop_table("archive_artifact_object_deliveries")
    with op.batch_alter_table("archive_video_artifacts") as batch_op:
        batch_op.drop_constraint("uq_archive_video_artifacts_build_key", type_="unique")
        batch_op.drop_constraint(
            "archive_video_artifacts_artifact_status_allowed",
            type_="check",
        )
        batch_op.drop_column("unavailable_detail")
        batch_op.drop_column("unavailable_code")
        batch_op.drop_column("artifact_key")
        batch_op.drop_column("artifact_store_ref")
        batch_op.drop_column("artifact_status")
        batch_op.drop_column("build_key")


def _create_object_delivery_table() -> None:
    op.create_table(
        "archive_artifact_object_deliveries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("artifact_id", sa.Integer(), nullable=False),
        sa.Column("profile_revision_id", sa.Integer(), nullable=False),
        sa.Column("route_id", sa.Integer(), nullable=False),
        sa.Column("object_binding_id", sa.Integer(), nullable=False),
        sa.Column("destination_id", sa.Integer(), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("public_url", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_work_item_id", sa.Integer(), nullable=True),
        sa.Column("last_work_attempt_id", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("succeeded_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('pending','running','succeeded','failed','unavailable')",
            name="archive_object_delivery_status_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id"], ["archive_video_artifacts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["profile_revision_id"],
            ["publish_profile_revisions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["route_id"], ["publish_profile_routes.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["object_binding_id"],
            ["publish_route_object_bindings.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["destination_id"],
            ["publish_object_destinations.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["last_work_item_id"], ["work_items.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["last_work_attempt_id"], ["work_attempts.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "artifact_id", "object_binding_id", name="uq_archive_object_delivery_binding"
        ),
        sa.UniqueConstraint("id", "artifact_id", name="uq_archive_object_delivery_artifact"),
    )
    op.create_index(
        "ix_archive_artifact_object_deliveries_artifact_id",
        "archive_artifact_object_deliveries",
        ["artifact_id"],
        unique=False,
    )


def _create_catalog_delivery_table() -> None:
    op.create_table(
        "archive_artifact_catalog_deliveries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("artifact_id", sa.Integer(), nullable=False),
        sa.Column("profile_revision_id", sa.Integer(), nullable=False),
        sa.Column("route_id", sa.Integer(), nullable=False),
        sa.Column("catalog_binding_id", sa.Integer(), nullable=False),
        sa.Column("destination_id", sa.Integer(), nullable=False),
        sa.Column("source_object_delivery_id", sa.Integer(), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_work_item_id", sa.Integer(), nullable=True),
        sa.Column("last_work_attempt_id", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("receipt_json", sa.Text(), nullable=True),
        sa.Column("succeeded_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('pending','running','succeeded','failed','unavailable')",
            name="archive_catalog_delivery_status_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id"], ["archive_video_artifacts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["profile_revision_id"],
            ["publish_profile_revisions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["route_id"], ["publish_profile_routes.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["catalog_binding_id"],
            ["publish_route_catalog_bindings.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["destination_id"],
            ["publish_catalog_destinations.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_object_delivery_id", "artifact_id"],
            [
                "archive_artifact_object_deliveries.id",
                "archive_artifact_object_deliveries.artifact_id",
            ],
            ondelete="RESTRICT",
            name="fk_archive_catalog_source_object",
        ),
        sa.ForeignKeyConstraint(["last_work_item_id"], ["work_items.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["last_work_attempt_id"], ["work_attempts.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "artifact_id", "catalog_binding_id", name="uq_archive_catalog_delivery_binding"
        ),
    )
    op.create_index(
        "ix_archive_artifact_catalog_deliveries_artifact_id",
        "archive_artifact_catalog_deliveries",
        ["artifact_id"],
        unique=False,
    )


def _create_publication_tables() -> None:
    op.create_table(
        "archive_publications",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("profile_revision_id", sa.Integer(), nullable=False),
        sa.Column("route_id", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("membership_sha256", sa.String(length=64), nullable=False),
        sa.Column("identity_key", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("video_count", sa.Integer(), nullable=False),
        sa.Column("artifact_count", sa.Integer(), nullable=False),
        sa.Column("work_item_id", sa.Integer(), nullable=True),
        sa.Column("work_attempt_id", sa.Integer(), nullable=True),
        sa.Column("legacy_index_publication_id", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
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
            "status IN ('building','ready','partially_published',"
            "'published','failed','unavailable')",
            name="archive_publication_status_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["profile_revision_id"],
            ["publish_profile_revisions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["route_id"], ["publish_profile_routes.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["work_item_id"], ["work_items.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["work_attempt_id"], ["work_attempts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["legacy_index_publication_id"],
            ["archive_index_publications.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "route_id",
            "identity_key",
            name="uq_archive_publication_identity",
        ),
        sa.UniqueConstraint(
            "route_id",
            "legacy_index_publication_id",
            name="uq_archive_publication_legacy_index",
        ),
    )
    op.create_index(
        "ix_archive_publications_route_id",
        "archive_publications",
        ["route_id"],
        unique=False,
    )
    op.create_table(
        "archive_publication_artifacts",
        sa.Column("publication_id", sa.Integer(), nullable=False),
        sa.Column("artifact_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["publication_id"], ["archive_publications.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id"], ["archive_video_artifacts.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("publication_id", "artifact_id"),
        sa.UniqueConstraint("publication_id", "position", name="uq_archive_publication_position"),
    )
    op.create_table(
        "archive_publication_deliveries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("publication_id", sa.Integer(), nullable=False),
        sa.Column("object_binding_id", sa.Integer(), nullable=False),
        sa.Column("destination_id", sa.Integer(), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("index_staging_key", sa.Text(), nullable=True),
        sa.Column("index_object_key", sa.Text(), nullable=True),
        sa.Column("index_public_url", sa.Text(), nullable=True),
        sa.Column("index_sha256", sa.String(length=64), nullable=True),
        sa.Column("index_byte_size", sa.BigInteger(), nullable=True),
        sa.Column("index_succeeded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pointer_staging_key", sa.Text(), nullable=True),
        sa.Column("pointer_object_key", sa.Text(), nullable=True),
        sa.Column("pointer_public_url", sa.Text(), nullable=True),
        sa.Column("pointer_sha256", sa.String(length=64), nullable=True),
        sa.Column("pointer_byte_size", sa.BigInteger(), nullable=True),
        sa.Column("pointer_succeeded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_work_item_id", sa.Integer(), nullable=True),
        sa.Column("last_work_attempt_id", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
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
            "status IN ('building','ready','partially_published',"
            "'published','failed','unavailable')",
            name="archive_publication_delivery_status_allowed",
        ),
        sa.CheckConstraint(
            "pointer_succeeded_at IS NULL OR index_succeeded_at IS NOT NULL",
            name="archive_publication_pointer_after_index",
        ),
        sa.ForeignKeyConstraint(
            ["publication_id"], ["archive_publications.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["object_binding_id"],
            ["publish_route_object_bindings.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["destination_id"],
            ["publish_object_destinations.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["last_work_item_id"], ["work_items.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["last_work_attempt_id"], ["work_attempts.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "publication_id",
            "object_binding_id",
            name="uq_archive_publication_delivery_binding",
        ),
    )
    op.create_index(
        "ix_archive_publication_deliveries_publication_id",
        "archive_publication_deliveries",
        ["publication_id"],
        unique=False,
    )
