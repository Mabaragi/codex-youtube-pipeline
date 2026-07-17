"""add pipeline automation, ASR checkpoints, and workflow scheduling

Revision ID: 20260713_0029
Revises: 20260711_0028
Create Date: 2026-07-13 09:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260713_0029"
down_revision: str | None = "20260711_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("workflow_runs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "available_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            )
        )
        batch_op.create_index("ix_workflow_runs_available_at", ["available_at"])

    op.create_table(
        "asr_chunk_checkpoints",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "work_item_id",
            sa.Integer(),
            sa.ForeignKey("work_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("segments_json", sa.JSON(), nullable=False),
        sa.Column("device", sa.String(length=32), nullable=False),
        sa.Column("compute_type", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "work_item_id", "chunk_index", name="uq_asr_chunk_checkpoint_item"
        ),
    )
    op.create_index(
        "ix_asr_chunk_checkpoints_work_item_id",
        "asr_chunk_checkpoints",
        ["work_item_id"],
    )

    op.create_table(
        "pipeline_incidents",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("fingerprint", sa.String(length=64), nullable=False, unique=True),
        sa.Column("incident_type", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column(
            "work_item_id",
            sa.Integer(),
            sa.ForeignKey("work_items.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "workflow_run_id",
            sa.Integer(),
            sa.ForeignKey("workflow_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("task_type", sa.String(length=64), nullable=True),
        sa.Column("error_type", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "state IN ('open', 'acknowledged', 'resolved', 'suppressed')",
            name="pipeline_incidents_state_allowed",
        ),
        sa.CheckConstraint(
            "severity IN ('info', 'warning', 'error', 'critical')",
            name="pipeline_incidents_severity_allowed",
        ),
    )
    op.create_index("ix_pipeline_incidents_work_item_id", "pipeline_incidents", ["work_item_id"])
    op.create_index(
        "ix_pipeline_incidents_workflow_run_id", "pipeline_incidents", ["workflow_run_id"]
    )
    op.create_index(
        "ix_pipeline_incidents_state_seen", "pipeline_incidents", ["state", "last_seen_at"]
    )

    op.create_table(
        "pipeline_remediation_actions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "incident_id",
            sa.Integer(),
            sa.ForeignKey("pipeline_incidents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("parameters_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "idempotency_key", name="uq_pipeline_remediation_action_key"
        ),
    )
    op.create_index(
        "ix_pipeline_remediation_actions_incident_id",
        "pipeline_remediation_actions",
        ["incident_id"],
    )

    op.create_table(
        "pipeline_runtime_controls",
        sa.Column("task_type", sa.String(length=64), primary_key=True),
        sa.Column("max_concurrency", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "pipeline_automation_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("backfill_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("steady_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.execute(
        sa.text(
            "INSERT INTO pipeline_automation_state "
            "(id, mode, backfill_started_at) VALUES (1, 'backfill', CURRENT_TIMESTAMP)"
        )
    )


def downgrade() -> None:
    op.drop_table("pipeline_automation_state")
    op.drop_table("pipeline_runtime_controls")
    op.drop_index(
        "ix_pipeline_remediation_actions_incident_id",
        table_name="pipeline_remediation_actions",
    )
    op.drop_table("pipeline_remediation_actions")
    op.drop_index("ix_pipeline_incidents_state_seen", table_name="pipeline_incidents")
    op.drop_index("ix_pipeline_incidents_workflow_run_id", table_name="pipeline_incidents")
    op.drop_index("ix_pipeline_incidents_work_item_id", table_name="pipeline_incidents")
    op.drop_table("pipeline_incidents")
    op.drop_index("ix_asr_chunk_checkpoints_work_item_id", table_name="asr_chunk_checkpoints")
    op.drop_table("asr_chunk_checkpoints")
    with op.batch_alter_table("workflow_runs") as batch_op:
        batch_op.drop_index("ix_workflow_runs_available_at")
        batch_op.drop_column("available_at")
