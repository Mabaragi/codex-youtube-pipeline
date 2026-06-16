"""create pipeline jobs

Revision ID: 20260616_0005
Revises: 20260616_0004
Create Date: 2026-06-16 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260616_0005"
down_revision: str | None = "20260616_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pipeline_jobs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("step", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("subject_type", sa.String(length=64), nullable=True),
        sa.Column("subject_id", sa.Integer(), nullable=True),
        sa.Column("external_key", sa.String(length=255), nullable=True),
        sa.Column("input_json", sa.JSON(), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("parent_job_id", sa.Integer(), nullable=True),
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
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed', 'skipped', 'canceled')",
            name=op.f("ck_pipeline_jobs_pipeline_jobs_status_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["parent_job_id"],
            ["pipeline_jobs.id"],
            name=op.f("fk_pipeline_jobs_parent_job_id_pipeline_jobs"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pipeline_jobs")),
    )
    op.create_index(op.f("ix_pipeline_jobs_input_hash"), "pipeline_jobs", ["input_hash"])
    op.create_index(op.f("ix_pipeline_jobs_parent_job_id"), "pipeline_jobs", ["parent_job_id"])
    op.create_index(op.f("ix_pipeline_jobs_status"), "pipeline_jobs", ["status"])
    op.create_index(op.f("ix_pipeline_jobs_step"), "pipeline_jobs", ["step"])
    op.create_index(
        op.f("ix_pipeline_jobs_step_status"),
        "pipeline_jobs",
        ["step", "status"],
    )
    op.create_index(
        op.f("ix_pipeline_jobs_subject"),
        "pipeline_jobs",
        ["subject_type", "subject_id"],
    )

    op.create_table(
        "pipeline_job_attempts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_id", sa.String(length=255), nullable=True),
        sa.Column("error_type", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("output_json", sa.JSON(), nullable=True),
        sa.CheckConstraint(
            "attempt_no >= 1",
            name=op.f("ck_pipeline_job_attempts_pipeline_job_attempts_attempt_no_min"),
        ),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed', 'canceled')",
            name=op.f("ck_pipeline_job_attempts_pipeline_job_attempts_status_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["pipeline_jobs.id"],
            name=op.f("fk_pipeline_job_attempts_job_id_pipeline_jobs"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pipeline_job_attempts")),
        sa.UniqueConstraint(
            "job_id",
            "attempt_no",
            name=op.f("uq_pipeline_job_attempts_job_attempt_no"),
        ),
    )
    op.create_index(
        op.f("ix_pipeline_job_attempts_job_id"),
        "pipeline_job_attempts",
        ["job_id"],
    )
    op.create_index(
        op.f("ix_pipeline_job_attempts_status"),
        "pipeline_job_attempts",
        ["status"],
    )

    with op.batch_alter_table("external_api_calls") as batch_op:
        batch_op.add_column(sa.Column("pipeline_job_attempt_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            op.f("fk_external_api_calls_pipeline_job_attempt_id_pipeline_job_attempts"),
            "pipeline_job_attempts",
            ["pipeline_job_attempt_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            op.f("ix_external_api_calls_pipeline_job_attempt_id"),
            ["pipeline_job_attempt_id"],
            unique=False,
        )

    with op.batch_alter_table("channels") as batch_op:
        batch_op.add_column(sa.Column("source_job_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            op.f("fk_channels_source_job_id_pipeline_jobs"),
            "pipeline_jobs",
            ["source_job_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            op.f("ix_channels_source_job_id"),
            ["source_job_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("channels") as batch_op:
        batch_op.drop_index(op.f("ix_channels_source_job_id"))
        batch_op.drop_constraint(
            op.f("fk_channels_source_job_id_pipeline_jobs"),
            type_="foreignkey",
        )
        batch_op.drop_column("source_job_id")

    with op.batch_alter_table("external_api_calls") as batch_op:
        batch_op.drop_index(op.f("ix_external_api_calls_pipeline_job_attempt_id"))
        batch_op.drop_constraint(
            op.f("fk_external_api_calls_pipeline_job_attempt_id_pipeline_job_attempts"),
            type_="foreignkey",
        )
        batch_op.drop_column("pipeline_job_attempt_id")

    op.drop_index(op.f("ix_pipeline_job_attempts_status"), table_name="pipeline_job_attempts")
    op.drop_index(op.f("ix_pipeline_job_attempts_job_id"), table_name="pipeline_job_attempts")
    op.drop_table("pipeline_job_attempts")

    op.drop_index(op.f("ix_pipeline_jobs_subject"), table_name="pipeline_jobs")
    op.drop_index(op.f("ix_pipeline_jobs_step_status"), table_name="pipeline_jobs")
    op.drop_index(op.f("ix_pipeline_jobs_step"), table_name="pipeline_jobs")
    op.drop_index(op.f("ix_pipeline_jobs_status"), table_name="pipeline_jobs")
    op.drop_index(op.f("ix_pipeline_jobs_parent_job_id"), table_name="pipeline_jobs")
    op.drop_index(op.f("ix_pipeline_jobs_input_hash"), table_name="pipeline_jobs")
    op.drop_table("pipeline_jobs")
