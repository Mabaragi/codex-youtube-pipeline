"""enforce publication routing integrity

Revision ID: 20260718_0034
Revises: 20260718_0033
Create Date: 2026-07-18 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260718_0034"
down_revision: str | None = "20260718_0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _normalize_active_revision_states()
    op.create_index(
        "uq_publish_profile_revisions_single_active",
        "publish_profile_revisions",
        ["profile_id"],
        unique=True,
        postgresql_where=sa.text("state = 'active'"),
        sqlite_where=sa.text("state = 'active'"),
    )
    _add_configuration_scope_keys()
    _add_object_delivery_scope_constraints()
    _add_catalog_delivery_scope_constraints()
    _add_publication_scope_constraints()
    _add_publication_delivery_scope_constraints()


def downgrade() -> None:
    _drop_publication_delivery_scope_constraints()
    _drop_publication_scope_constraints()
    _drop_catalog_delivery_scope_constraints()
    _drop_object_delivery_scope_constraints()
    _drop_configuration_scope_keys()
    op.drop_index(
        "uq_publish_profile_revisions_single_active",
        table_name="publish_profile_revisions",
    )


def _normalize_active_revision_states() -> None:
    op.execute(
        sa.text(
            "UPDATE publish_profile_revisions SET state = 'retired' "
            "WHERE state = 'active' AND id NOT IN ("
            "SELECT active_revision_id FROM publish_profiles "
            "WHERE active_revision_id IS NOT NULL)"
        )
    )
    op.execute(
        sa.text(
            "UPDATE publish_profile_revisions SET state = 'active' "
            "WHERE id IN (SELECT active_revision_id FROM publish_profiles "
            "WHERE active_revision_id IS NOT NULL)"
        )
    )


def _add_configuration_scope_keys() -> None:
    with op.batch_alter_table("publish_profile_routes") as batch_op:
        batch_op.create_unique_constraint(
            "uq_publish_profile_routes_id_revision",
            ["id", "profile_revision_id"],
        )
    with op.batch_alter_table("publish_route_object_bindings") as batch_op:
        batch_op.create_unique_constraint(
            "uq_publish_route_object_bindings_delivery_scope",
            ["id", "route_id", "destination_id", "required"],
        )
    with op.batch_alter_table("publish_route_catalog_bindings") as batch_op:
        batch_op.create_unique_constraint(
            "uq_publish_route_catalog_bindings_delivery_scope",
            ["id", "route_id", "destination_id", "source_object_binding_id", "required"],
        )


def _drop_configuration_scope_keys() -> None:
    with op.batch_alter_table("publish_route_catalog_bindings") as batch_op:
        batch_op.drop_constraint(
            "uq_publish_route_catalog_bindings_delivery_scope",
            type_="unique",
        )
    with op.batch_alter_table("publish_route_object_bindings") as batch_op:
        batch_op.drop_constraint(
            "uq_publish_route_object_bindings_delivery_scope",
            type_="unique",
        )
    with op.batch_alter_table("publish_profile_routes") as batch_op:
        batch_op.drop_constraint(
            "uq_publish_profile_routes_id_revision",
            type_="unique",
        )


def _add_object_delivery_scope_constraints() -> None:
    with op.batch_alter_table("archive_artifact_object_deliveries") as batch_op:
        batch_op.create_unique_constraint(
            "uq_archive_object_delivery_source_scope",
            ["id", "artifact_id", "profile_revision_id", "route_id", "object_binding_id"],
        )
        batch_op.create_foreign_key(
            "fk_archive_object_delivery_route_revision",
            "publish_profile_routes",
            ["route_id", "profile_revision_id"],
            ["id", "profile_revision_id"],
            ondelete="RESTRICT",
        )
        batch_op.create_foreign_key(
            "fk_archive_object_delivery_binding_scope",
            "publish_route_object_bindings",
            ["object_binding_id", "route_id", "destination_id", "required"],
            ["id", "route_id", "destination_id", "required"],
            ondelete="RESTRICT",
        )


def _drop_object_delivery_scope_constraints() -> None:
    with op.batch_alter_table("archive_artifact_object_deliveries") as batch_op:
        batch_op.drop_constraint(
            "fk_archive_object_delivery_binding_scope",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "fk_archive_object_delivery_route_revision",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "uq_archive_object_delivery_source_scope",
            type_="unique",
        )


def _add_catalog_delivery_scope_constraints() -> None:
    op.add_column(
        "archive_artifact_catalog_deliveries",
        sa.Column("source_object_binding_id", sa.Integer(), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE archive_artifact_catalog_deliveries "
            "SET source_object_binding_id = ("
            "SELECT source_object_binding_id FROM publish_route_catalog_bindings "
            "WHERE publish_route_catalog_bindings.id = "
            "archive_artifact_catalog_deliveries.catalog_binding_id)"
        )
    )
    with op.batch_alter_table("archive_artifact_catalog_deliveries") as batch_op:
        batch_op.alter_column(
            "source_object_binding_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
        batch_op.drop_constraint("fk_archive_catalog_source_object", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_archive_catalog_delivery_route_revision",
            "publish_profile_routes",
            ["route_id", "profile_revision_id"],
            ["id", "profile_revision_id"],
            ondelete="RESTRICT",
        )
        batch_op.create_foreign_key(
            "fk_archive_catalog_delivery_binding_scope",
            "publish_route_catalog_bindings",
            [
                "catalog_binding_id",
                "route_id",
                "destination_id",
                "source_object_binding_id",
                "required",
            ],
            ["id", "route_id", "destination_id", "source_object_binding_id", "required"],
            ondelete="RESTRICT",
        )
        batch_op.create_foreign_key(
            "fk_archive_catalog_delivery_source_scope",
            "archive_artifact_object_deliveries",
            [
                "source_object_delivery_id",
                "artifact_id",
                "profile_revision_id",
                "route_id",
                "source_object_binding_id",
            ],
            ["id", "artifact_id", "profile_revision_id", "route_id", "object_binding_id"],
            ondelete="RESTRICT",
        )


def _drop_catalog_delivery_scope_constraints() -> None:
    with op.batch_alter_table("archive_artifact_catalog_deliveries") as batch_op:
        batch_op.drop_constraint(
            "fk_archive_catalog_delivery_source_scope",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "fk_archive_catalog_delivery_binding_scope",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "fk_archive_catalog_delivery_route_revision",
            type_="foreignkey",
        )
        batch_op.create_foreign_key(
            "fk_archive_catalog_source_object",
            "archive_artifact_object_deliveries",
            ["source_object_delivery_id", "artifact_id"],
            ["id", "artifact_id"],
            ondelete="RESTRICT",
        )
        batch_op.drop_column("source_object_binding_id")


def _add_publication_scope_constraints() -> None:
    with op.batch_alter_table("archive_publications") as batch_op:
        batch_op.create_unique_constraint(
            "uq_archive_publication_id_route",
            ["id", "route_id"],
        )
        batch_op.create_foreign_key(
            "fk_archive_publication_route_revision",
            "publish_profile_routes",
            ["route_id", "profile_revision_id"],
            ["id", "profile_revision_id"],
            ondelete="RESTRICT",
        )


def _drop_publication_scope_constraints() -> None:
    with op.batch_alter_table("archive_publications") as batch_op:
        batch_op.drop_constraint(
            "fk_archive_publication_route_revision",
            type_="foreignkey",
        )
        batch_op.drop_constraint("uq_archive_publication_id_route", type_="unique")


def _add_publication_delivery_scope_constraints() -> None:
    op.add_column(
        "archive_publication_deliveries",
        sa.Column("route_id", sa.Integer(), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE archive_publication_deliveries SET route_id = ("
            "SELECT route_id FROM archive_publications "
            "WHERE archive_publications.id = archive_publication_deliveries.publication_id)"
        )
    )
    with op.batch_alter_table("archive_publication_deliveries") as batch_op:
        batch_op.alter_column("route_id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_foreign_key(
            "fk_archive_publication_delivery_publication_route",
            "archive_publications",
            ["publication_id", "route_id"],
            ["id", "route_id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_archive_publication_delivery_binding_scope",
            "publish_route_object_bindings",
            ["object_binding_id", "route_id", "destination_id", "required"],
            ["id", "route_id", "destination_id", "required"],
            ondelete="RESTRICT",
        )


def _drop_publication_delivery_scope_constraints() -> None:
    with op.batch_alter_table("archive_publication_deliveries") as batch_op:
        batch_op.drop_constraint(
            "fk_archive_publication_delivery_binding_scope",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "fk_archive_publication_delivery_publication_route",
            type_="foreignkey",
        )
        batch_op.drop_column("route_id")
