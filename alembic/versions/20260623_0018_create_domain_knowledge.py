"""create domain knowledge

Revision ID: 20260623_0018
Revises: 20260623_0017
Create Date: 2026-06-23 22:20:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260623_0018"
down_revision: str | None = "20260623_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "domain_entry_types",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("label_normalized", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False),
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
        sa.CheckConstraint("sort_order >= 0", name="domain_entry_types_sort_order_min"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_domain_entry_types")),
        sa.UniqueConstraint("key", name="uq_domain_entry_types_key"),
        sa.UniqueConstraint(
            "label_normalized",
            name="uq_domain_entry_types_label_normalized",
        ),
    )
    op.create_index(
        "ix_domain_entry_types_sort",
        "domain_entry_types",
        ["sort_order", "id"],
        unique=False,
    )
    domain_entry_types = sa.table(
        "domain_entry_types",
        sa.column("key", sa.String),
        sa.column("label", sa.String),
        sa.column("label_normalized", sa.String),
        sa.column("description", sa.Text),
        sa.column("sort_order", sa.Integer),
        sa.column("is_system", sa.Boolean),
    )
    op.bulk_insert(
        domain_entry_types,
        [
            {
                "key": "person",
                "label": "Person",
                "label_normalized": "person",
                "description": "Person name or identity.",
                "sort_order": 10,
                "is_system": True,
            },
            {
                "key": "content",
                "label": "Content",
                "label_normalized": "content",
                "description": "Content, series, media, or work title.",
                "sort_order": 20,
                "is_system": True,
            },
            {
                "key": "game",
                "label": "Game",
                "label_normalized": "game",
                "description": "Game title or game-specific term.",
                "sort_order": 30,
                "is_system": True,
            },
            {
                "key": "place",
                "label": "Place",
                "label_normalized": "place",
                "description": "Place or location name.",
                "sort_order": 40,
                "is_system": True,
            },
            {
                "key": "organization",
                "label": "Organization",
                "label_normalized": "organization",
                "description": "Organization, group, or company name.",
                "sort_order": 50,
                "is_system": True,
            },
            {
                "key": "term",
                "label": "Term",
                "label_normalized": "term",
                "description": "Domain-specific term.",
                "sort_order": 60,
                "is_system": True,
            },
            {
                "key": "meme",
                "label": "Meme",
                "label_normalized": "meme",
                "description": "Meme, nickname, or recurring joke.",
                "sort_order": 70,
                "is_system": True,
            },
            {
                "key": "other",
                "label": "Other",
                "label_normalized": "other",
                "description": "Other domain knowledge.",
                "sort_order": 1000,
                "is_system": True,
            },
        ],
    )
    op.create_table(
        "domain_entries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("type_id", sa.Integer(), nullable=False),
        sa.Column("canonical_name", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("disambiguation", sa.String(length=500), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("prompt_policy", sa.String(length=64), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
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
        sa.CheckConstraint(
            "prompt_policy IN ('AUTO_ON_MATCH', 'ALWAYS_FOR_SCOPED_STREAMER', 'DISABLED')",
            name="domain_entries_prompt_policy_allowed",
        ),
        sa.CheckConstraint("priority >= 0", name="domain_entries_priority_min"),
        sa.ForeignKeyConstraint(
            ["type_id"],
            ["domain_entry_types.id"],
            name=op.f("fk_domain_entries_type_id_domain_entry_types"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_domain_entries")),
    )
    op.create_index("ix_domain_entries_canonical", "domain_entries", ["canonical_name"])
    op.create_index(
        "ix_domain_entries_active_priority",
        "domain_entries",
        ["is_active", "priority"],
    )
    op.create_index(
        "ix_domain_entries_type_active",
        "domain_entries",
        ["type_id", "is_active"],
    )
    op.create_table(
        "domain_entry_streamers",
        sa.Column("entry_id", sa.Integer(), nullable=False),
        sa.Column("streamer_id", sa.Integer(), nullable=False),
        sa.Column("relevance", sa.String(length=255), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["entry_id"],
            ["domain_entries.id"],
            name=op.f("fk_domain_entry_streamers_entry_id_domain_entries"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["streamer_id"],
            ["streamers.id"],
            name=op.f("fk_domain_entry_streamers_streamer_id_streamers"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "entry_id",
            "streamer_id",
            name=op.f("pk_domain_entry_streamers"),
        ),
        sa.UniqueConstraint(
            "entry_id",
            "streamer_id",
            name="uq_domain_entry_streamers_entry_streamer",
        ),
    )
    op.create_index(
        "ix_domain_entry_streamers_streamer",
        "domain_entry_streamers",
        ["streamer_id", "entry_id"],
    )
    op.create_table(
        "domain_entry_aliases",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("entry_id", sa.Integer(), nullable=False),
        sa.Column("surface_form", sa.String(length=255), nullable=False),
        sa.Column("alias_kind", sa.String(length=64), nullable=False),
        sa.Column("certainty", sa.String(length=16), nullable=False),
        sa.Column("apply_scope", sa.String(length=32), nullable=False),
        sa.Column("language_code", sa.String(length=16), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
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
            "alias_kind IN ("
            "'ALIAS', 'ASR_ERROR', 'SEARCH_ALIAS', 'NICKNAME', "
            "'WORDPLAY', 'MISSPELLING'"
            ")",
            name="domain_entry_aliases_kind_allowed",
        ),
        sa.CheckConstraint(
            "certainty IN ('LOW', 'MEDIUM', 'HIGH')",
            name="domain_entry_aliases_certainty_allowed",
        ),
        sa.CheckConstraint(
            "apply_scope IN ('NONE', 'SEARCH_ONLY', 'SEARCH_AND_SUMMARY', 'DISPLAY_ALLOWED')",
            name="domain_entry_aliases_apply_scope_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["entry_id"],
            ["domain_entries.id"],
            name=op.f("fk_domain_entry_aliases_entry_id_domain_entries"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_domain_entry_aliases")),
        sa.UniqueConstraint(
            "entry_id",
            "surface_form",
            "alias_kind",
            name="uq_domain_entry_aliases_entry_surface_kind",
        ),
    )
    op.create_index("ix_domain_entry_aliases_entry", "domain_entry_aliases", ["entry_id"])
    op.create_index(
        "ix_domain_entry_aliases_surface",
        "domain_entry_aliases",
        ["surface_form"],
    )


def downgrade() -> None:
    op.drop_index("ix_domain_entry_aliases_surface", table_name="domain_entry_aliases")
    op.drop_index("ix_domain_entry_aliases_entry", table_name="domain_entry_aliases")
    op.drop_table("domain_entry_aliases")
    op.drop_index(
        "ix_domain_entry_streamers_streamer",
        table_name="domain_entry_streamers",
    )
    op.drop_table("domain_entry_streamers")
    op.drop_index("ix_domain_entries_type_active", table_name="domain_entries")
    op.drop_index("ix_domain_entries_active_priority", table_name="domain_entries")
    op.drop_index("ix_domain_entries_canonical", table_name="domain_entries")
    op.drop_table("domain_entries")
    op.drop_index("ix_domain_entry_types_sort", table_name="domain_entry_types")
    op.drop_table("domain_entry_types")
