"""create external api calls

Revision ID: 20260616_0004
Revises: 20260615_0003
Create Date: 2026-06-16 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260616_0004"
down_revision: str | None = "20260615_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "external_api_calls",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("operation", sa.String(length=128), nullable=False),
        sa.Column("request_method", sa.String(length=16), nullable=False),
        sa.Column("request_url", sa.Text(), nullable=False),
        sa.Column("request_params", sa.JSON(), nullable=False),
        sa.Column("request_body", sa.JSON(), nullable=True),
        sa.Column("response_status_code", sa.Integer(), nullable=True),
        sa.Column("response_headers", sa.JSON(), nullable=False),
        sa.Column("response_storage_bucket", sa.String(length=255), nullable=True),
        sa.Column("response_storage_object_name", sa.Text(), nullable=True),
        sa.Column("response_storage_uri", sa.Text(), nullable=True),
        sa.Column("response_sha256", sa.String(length=64), nullable=True),
        sa.Column("schema_name", sa.String(length=255), nullable=True),
        sa.Column("schema_version", sa.String(length=64), nullable=True),
        sa.Column("validation_status", sa.String(length=32), nullable=False),
        sa.Column("validation_error", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("quota_cost", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "duration_ms >= 0",
            name=op.f("ck_external_api_calls_external_api_calls_duration_ms_non_negative"),
        ),
        sa.CheckConstraint(
            "quota_cost IS NULL OR quota_cost >= 0",
            name=op.f("ck_external_api_calls_external_api_calls_quota_cost_non_negative"),
        ),
        sa.CheckConstraint(
            "response_status_code IS NULL OR response_status_code >= 100",
            name=op.f("ck_external_api_calls_external_api_calls_status_code_min"),
        ),
        sa.CheckConstraint(
            "validation_status IN ('not_validated', 'valid', 'invalid')",
            name=op.f("ck_external_api_calls_external_api_calls_validation_status_allowed"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_external_api_calls")),
    )
    op.create_index(
        op.f("ix_external_api_calls_operation"),
        "external_api_calls",
        ["operation"],
        unique=False,
    )
    op.create_index(
        op.f("ix_external_api_calls_provider"),
        "external_api_calls",
        ["provider"],
        unique=False,
    )

    with op.batch_alter_table("channels") as batch_op:
        batch_op.add_column(sa.Column("source_api_call_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            op.f("fk_channels_source_api_call_id_external_api_calls"),
            "external_api_calls",
            ["source_api_call_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            op.f("ix_channels_source_api_call_id"),
            ["source_api_call_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("channels") as batch_op:
        batch_op.drop_index(op.f("ix_channels_source_api_call_id"))
        batch_op.drop_constraint(
            op.f("fk_channels_source_api_call_id_external_api_calls"),
            type_="foreignkey",
        )
        batch_op.drop_column("source_api_call_id")

    op.drop_index(op.f("ix_external_api_calls_provider"), table_name="external_api_calls")
    op.drop_index(op.f("ix_external_api_calls_operation"), table_name="external_api_calls")
    op.drop_table("external_api_calls")
