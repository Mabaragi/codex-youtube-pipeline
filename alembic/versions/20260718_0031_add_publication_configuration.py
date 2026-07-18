"""add streamer publication routing configuration

Revision ID: 20260718_0031
Revises: 20260714_0030
Create Date: 2026-07-18 01:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260718_0031"
down_revision: str | None = "20260714_0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _create_configuration_tables()
    _seed_legacy_current_profile()
    _advance_postgresql_sequences()
    with op.batch_alter_table("publish_profiles") as batch_op:
        batch_op.create_foreign_key(
            "fk_publish_profiles_active_revision",
            "publish_profile_revisions",
            ["active_revision_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    with op.batch_alter_table("streamers") as batch_op:
        batch_op.add_column(sa.Column("publish_profile_id", sa.Integer(), nullable=True))
    op.execute(
        sa.text(
            "UPDATE streamers SET publish_profile_id = ("
            "SELECT id FROM publish_profiles WHERE key = 'legacy-current'"
            ")"
        )
    )
    with op.batch_alter_table("streamers") as batch_op:
        batch_op.alter_column(
            "publish_profile_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
        batch_op.create_foreign_key(
            "fk_streamers_publish_profile_id_publish_profiles",
            "publish_profiles",
            ["publish_profile_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_index(
            "ix_streamers_publish_profile_id",
            ["publish_profile_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("streamers") as batch_op:
        batch_op.drop_index("ix_streamers_publish_profile_id")
        batch_op.drop_constraint(
            "fk_streamers_publish_profile_id_publish_profiles",
            type_="foreignkey",
        )
        batch_op.drop_column("publish_profile_id")
    with op.batch_alter_table("publish_profiles") as batch_op:
        batch_op.drop_constraint(
            "fk_publish_profiles_active_revision",
            type_="foreignkey",
        )
    op.drop_index(
        "ix_publish_route_catalog_bindings_route",
        table_name="publish_route_catalog_bindings",
    )
    op.drop_table("publish_route_catalog_bindings")
    op.drop_index(
        "ix_publish_route_object_bindings_route",
        table_name="publish_route_object_bindings",
    )
    op.drop_table("publish_route_object_bindings")
    op.drop_index(
        "ix_publish_profile_routes_revision_lookup",
        table_name="publish_profile_routes",
    )
    op.drop_table("publish_profile_routes")
    op.drop_index(
        "ix_publish_profile_revisions_profile_state",
        table_name="publish_profile_revisions",
    )
    op.drop_table("publish_profile_revisions")
    op.drop_table("publish_catalog_destinations")
    op.drop_table("publish_object_destinations")
    op.drop_table("publish_profiles")


def _create_configuration_tables() -> None:
    op.create_table(
        "publish_profiles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("active_revision_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_publish_profiles")),
        sa.UniqueConstraint("key", name=op.f("uq_publish_profiles_key")),
    )
    op.create_table(
        "publish_object_destinations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("connection_ref", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_publish_object_destinations")),
        sa.UniqueConstraint("key", name=op.f("uq_publish_object_destinations_key")),
    )
    op.create_table(
        "publish_catalog_destinations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("connection_ref", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_publish_catalog_destinations")),
        sa.UniqueConstraint("key", name=op.f("uq_publish_catalog_destinations_key")),
    )
    op.create_table(
        "publish_profile_revisions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('draft', 'active', 'retired')",
            name=op.f("ck_publish_profile_revisions_publish_profile_revisions_state_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["publish_profiles.id"],
            name=op.f("fk_publish_profile_revisions_profile_id_publish_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_publish_profile_revisions")),
        sa.UniqueConstraint(
            "profile_id",
            "revision_number",
            name="uq_publish_profile_revisions_profile_number",
        ),
    )
    op.create_index(
        "ix_publish_profile_revisions_profile_state",
        "publish_profile_revisions",
        ["profile_id", "state"],
        unique=False,
    )
    op.create_table(
        "publish_profile_routes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("profile_revision_id", sa.Integer(), nullable=False),
        sa.Column("publish_mode", sa.String(length=16), nullable=False),
        sa.Column("environment", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "publish_mode IN ('prod', 'dev')",
            name=op.f("ck_publish_profile_routes_publish_profile_routes_mode_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["profile_revision_id"],
            ["publish_profile_revisions.id"],
            name=op.f("fk_publish_profile_routes_profile_revision_id_publish_profile_revisions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_publish_profile_routes")),
        sa.UniqueConstraint(
            "profile_revision_id",
            "publish_mode",
            "environment",
            name="uq_publish_profile_routes_revision_mode_environment",
        ),
    )
    op.create_index(
        "ix_publish_profile_routes_revision_lookup",
        "publish_profile_routes",
        ["profile_revision_id", "publish_mode", "environment"],
        unique=False,
    )
    op.create_table(
        "publish_route_object_bindings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("route_id", sa.Integer(), nullable=False),
        sa.Column("destination_id", sa.Integer(), nullable=False),
        sa.Column("key_prefix", sa.String(length=512), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["route_id"],
            ["publish_profile_routes.id"],
            name=op.f("fk_publish_route_object_bindings_route_id_publish_profile_routes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["destination_id"],
            ["publish_object_destinations.id"],
            name=op.f(
                "fk_publish_route_object_bindings_destination_id_publish_object_destinations"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_publish_route_object_bindings")),
        sa.UniqueConstraint(
            "route_id",
            "destination_id",
            name="uq_publish_route_object_bindings_route_destination",
        ),
        sa.UniqueConstraint(
            "id",
            "route_id",
            name="uq_publish_route_object_bindings_id_route",
        ),
    )
    op.create_index(
        "ix_publish_route_object_bindings_route",
        "publish_route_object_bindings",
        ["route_id"],
        unique=False,
    )
    op.create_table(
        "publish_route_catalog_bindings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("route_id", sa.Integer(), nullable=False),
        sa.Column("destination_id", sa.Integer(), nullable=False),
        sa.Column("source_object_binding_id", sa.Integer(), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["route_id"],
            ["publish_profile_routes.id"],
            name=op.f("fk_publish_route_catalog_bindings_route_id_publish_profile_routes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["destination_id"],
            ["publish_catalog_destinations.id"],
            name=op.f(
                "fk_publish_route_catalog_bindings_destination_id_publish_catalog_destinations"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_object_binding_id", "route_id"],
            [
                "publish_route_object_bindings.id",
                "publish_route_object_bindings.route_id",
            ],
            name="fk_publish_route_catalog_binding_source_same_route",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_publish_route_catalog_bindings")),
        sa.UniqueConstraint(
            "route_id",
            "destination_id",
            name="uq_publish_route_catalog_bindings_route_destination",
        ),
    )
    op.create_index(
        "ix_publish_route_catalog_bindings_route",
        "publish_route_catalog_bindings",
        ["route_id"],
        unique=False,
    )


def _seed_legacy_current_profile() -> None:
    op.bulk_insert(
        sa.table(
            "publish_profiles",
            sa.column("id", sa.Integer()),
            sa.column("key", sa.String()),
            sa.column("name", sa.String()),
            sa.column("description", sa.Text()),
            sa.column("active_revision_id", sa.Integer()),
        ),
        [
            {
                "id": 1,
                "key": "legacy-current",
                "name": "Legacy Current",
                "description": "Compatibility profile seeded for existing streamers.",
                "active_revision_id": 1,
            }
        ],
    )
    op.bulk_insert(
        sa.table(
            "publish_object_destinations",
            sa.column("id", sa.Integer()),
            sa.column("key", sa.String()),
            sa.column("name", sa.String()),
            sa.column("connection_ref", sa.String()),
        ),
        [
            {
                "id": 1,
                "key": "legacy-remote-object",
                "name": "Legacy Remote Object",
                "connection_ref": "legacy-remote-object",
            },
            {
                "id": 2,
                "key": "local-object",
                "name": "Local Published Object",
                "connection_ref": "local-public-object",
            },
            {
                "id": 3,
                "key": "legacy-dev-remote-object",
                "name": "Legacy Development Remote Object",
                "connection_ref": "legacy-dev-remote-object",
            },
        ],
    )
    op.bulk_insert(
        sa.table(
            "publish_catalog_destinations",
            sa.column("id", sa.Integer()),
            sa.column("key", sa.String()),
            sa.column("name", sa.String()),
            sa.column("connection_ref", sa.String()),
        ),
        [
            {
                "id": 1,
                "key": "legacy-remote-catalog",
                "name": "Legacy Remote Catalog",
                "connection_ref": "legacy-remote-catalog",
            },
            {
                "id": 2,
                "key": "local-catalog",
                "name": "Local Published Catalog",
                "connection_ref": "local-public-catalog",
            },
        ],
    )
    op.bulk_insert(
        sa.table(
            "publish_profile_revisions",
            sa.column("id", sa.Integer()),
            sa.column("profile_id", sa.Integer()),
            sa.column("revision_number", sa.Integer()),
            sa.column("state", sa.String()),
        ),
        [
            {
                "id": 1,
                "profile_id": 1,
                "revision_number": 1,
                "state": "active",
            }
        ],
    )
    op.bulk_insert(
        sa.table(
            "publish_profile_routes",
            sa.column("id", sa.Integer()),
            sa.column("profile_revision_id", sa.Integer()),
            sa.column("publish_mode", sa.String()),
            sa.column("environment", sa.String()),
        ),
        [
            {
                "id": 1,
                "profile_revision_id": 1,
                "publish_mode": "prod",
                "environment": "prod",
            },
            {
                "id": 2,
                "profile_revision_id": 1,
                "publish_mode": "dev",
                "environment": "dev",
            },
        ],
    )
    op.execute(
        sa.text(
            "UPDATE publish_profile_revisions SET activated_at = CURRENT_TIMESTAMP WHERE id = 1"
        )
    )
    op.bulk_insert(
        sa.table(
            "publish_route_object_bindings",
            sa.column("id", sa.Integer()),
            sa.column("route_id", sa.Integer()),
            sa.column("destination_id", sa.Integer()),
            sa.column("key_prefix", sa.String()),
            sa.column("required", sa.Boolean()),
            sa.column("is_primary", sa.Boolean()),
        ),
        [
            {
                "id": 1,
                "route_id": 1,
                "destination_id": 1,
                "key_prefix": "archive",
                "required": True,
                "is_primary": True,
            },
            {
                "id": 2,
                "route_id": 1,
                "destination_id": 2,
                "key_prefix": "archive",
                "required": True,
                "is_primary": False,
            },
            {
                "id": 3,
                "route_id": 2,
                "destination_id": 3,
                "key_prefix": "archive-dev",
                "required": True,
                "is_primary": True,
            },
            {
                "id": 4,
                "route_id": 2,
                "destination_id": 2,
                "key_prefix": "archive-dev",
                "required": True,
                "is_primary": False,
            },
        ],
    )
    op.bulk_insert(
        sa.table(
            "publish_route_catalog_bindings",
            sa.column("id", sa.Integer()),
            sa.column("route_id", sa.Integer()),
            sa.column("destination_id", sa.Integer()),
            sa.column("source_object_binding_id", sa.Integer()),
            sa.column("required", sa.Boolean()),
        ),
        [
            {
                "id": 1,
                "route_id": 1,
                "destination_id": 1,
                "source_object_binding_id": 1,
                "required": True,
            },
            {
                "id": 2,
                "route_id": 1,
                "destination_id": 2,
                "source_object_binding_id": 2,
                "required": True,
            },
            {
                "id": 3,
                "route_id": 2,
                "destination_id": 1,
                "source_object_binding_id": 3,
                "required": True,
            },
            {
                "id": 4,
                "route_id": 2,
                "destination_id": 2,
                "source_object_binding_id": 4,
                "required": True,
            },
        ],
    )


def _advance_postgresql_sequences() -> None:
    """Advance sequences after the compatibility seed uses fixed identifiers."""
    if op.get_bind().dialect.name != "postgresql":
        return
    for table_name in (
        "publish_profiles",
        "publish_object_destinations",
        "publish_catalog_destinations",
        "publish_profile_revisions",
        "publish_profile_routes",
        "publish_route_object_bindings",
        "publish_route_catalog_bindings",
    ):
        op.execute(
            sa.text(
                "SELECT setval("
                f"pg_get_serial_sequence('{table_name}', 'id'), "
                f"(SELECT MAX(id) FROM {table_name}), true)"
            )
        )
