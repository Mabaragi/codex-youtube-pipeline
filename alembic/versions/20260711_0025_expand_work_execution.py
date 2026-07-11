"""expand unified work execution model

Revision ID: 20260711_0025
Revises: 20260704_0024
Create Date: 2026-07-11 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260711_0025"
down_revision: str | None = "20260704_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_WORK_ITEM_STATUS = (
    "status IN ('pending', 'running', 'succeeded', 'failed', 'timed_out', 'blocked', 'canceled')"
)


def upgrade() -> None:
    _create_work_tables()
    _migrate_legacy_work()


def downgrade() -> None:
    op.drop_table("legacy_work_refs")
    op.drop_table("work_batch_items")
    op.drop_table("workflow_steps")
    op.drop_table("workflow_runs")
    op.drop_table("work_batches")
    op.drop_table("work_item_dependencies")
    op.drop_table("work_attempts")
    op.drop_table("work_items")


def _create_work_tables() -> None:
    op.create_table(
        "work_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("task_type", sa.String(64), nullable=False),
        sa.Column("subject_type", sa.String(64), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=True),
        sa.Column("external_key", sa.String(255), nullable=True),
        sa.Column("task_version", sa.String(64), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("execution_mode", sa.String(16), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("outcome_code", sa.String(64), nullable=True),
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("input_json", sa.JSON(), nullable=False),
        sa.Column("output_json", sa.JSON(), nullable=True),
        sa.Column("output_transcript_id", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(128), nullable=True),
        sa.Column("error_type", sa.String(255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("lease_owner", sa.String(255), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "available_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(_WORK_ITEM_STATUS, name="ck_work_items_work_items_status_allowed"),
        sa.CheckConstraint(
            "execution_mode IN ('inline', 'worker')",
            name="ck_work_items_work_items_execution_mode_allowed",
        ),
        sa.CheckConstraint(
            "timeout_seconds >= 1",
            name="ck_work_items_work_items_timeout_positive",
        ),
        sa.ForeignKeyConstraint(
            ["output_transcript_id"], ["youtube_transcripts.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_work_items_idempotency_key"),
    )
    op.create_index("ix_work_items_input_hash", "work_items", ["input_hash"])
    op.create_index("ix_work_items_lease_expires_at", "work_items", ["lease_expires_at"])
    op.create_index("ix_work_items_output_transcript_id", "work_items", ["output_transcript_id"])
    op.create_index("ix_work_items_subject", "work_items", ["subject_type", "subject_id"])
    op.create_index("ix_work_items_task_status", "work_items", ["task_type", "status"])
    op.create_index(
        "ix_work_items_pending_claim",
        "work_items",
        ["status", "execution_mode", "task_type", "available_at", "priority", "id"],
    )

    op.create_table(
        "work_attempts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("work_item_id", sa.Integer(), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("worker_id", sa.String(255), nullable=True),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("output_json", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(128), nullable=True),
        sa.Column("error_type", sa.String(255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.CheckConstraint("attempt_no >= 1", name="ck_work_attempts_attempt_no_positive"),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed', 'timed_out', 'canceled')",
            name="ck_work_attempts_status_allowed",
        ),
        sa.ForeignKeyConstraint(["work_item_id"], ["work_items.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("work_item_id", "attempt_no", name="uq_work_attempts_item_no"),
    )
    op.create_index("ix_work_attempts_work_item_id", "work_attempts", ["work_item_id"])
    op.create_index("ix_work_attempts_item_status", "work_attempts", ["work_item_id", "status"])

    op.create_table(
        "work_item_dependencies",
        sa.Column("work_item_id", sa.Integer(), nullable=False),
        sa.Column("dependency_work_item_id", sa.Integer(), nullable=False),
        sa.Column("requires_successful_output", sa.Boolean(), server_default="1", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "work_item_id <> dependency_work_item_id",
            name="ck_work_item_dependencies_not_self",
        ),
        sa.ForeignKeyConstraint(["work_item_id"], ["work_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["dependency_work_item_id"], ["work_items.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("work_item_id", "dependency_work_item_id"),
    )
    op.create_index(
        "ix_work_item_dependencies_dependency_work_item_id",
        "work_item_dependencies",
        ["dependency_work_item_id"],
    )

    _create_batch_and_workflow_tables()


def _create_batch_and_workflow_tables() -> None:
    op.create_table(
        "work_batches",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("operation_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("actor_type", sa.String(32), nullable=False),
        sa.Column("selection_json", sa.JSON(), nullable=False),
        sa.Column("options_json", sa.JSON(), nullable=False),
        sa.Column("requested_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'partial', 'failed', 'canceled')",
            name="ck_work_batches_status_allowed",
        ),
        sa.CheckConstraint("requested_count >= 0", name="ck_work_batches_requested_non_negative"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_work_batches_operation_status", "work_batches", ["operation_type", "status"]
    )

    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("workflow_type", sa.String(64), nullable=False),
        sa.Column("workflow_version", sa.String(64), nullable=False),
        sa.Column("video_id", sa.Integer(), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("current_stage", sa.String(64), nullable=True),
        sa.Column("options_json", sa.JSON(), nullable=False),
        sa.Column("output_json", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("lease_owner", sa.String(255), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'waiting', 'succeeded', 'failed', "
            "'blocked', 'canceled')",
            name="ck_workflow_runs_status_allowed",
        ),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workflow_type",
            "workflow_version",
            "video_id",
            "input_hash",
            name="uq_workflow_runs_input",
        ),
    )
    op.create_index("ix_workflow_runs_claim", "workflow_runs", ["status", "lease_expires_at", "id"])
    op.create_index("ix_workflow_runs_video", "workflow_runs", ["video_id", "workflow_type"])

    op.create_table(
        "workflow_steps",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("workflow_run_id", sa.Integer(), nullable=False),
        sa.Column("stage_name", sa.String(64), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("work_item_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["work_item_id"], ["work_items.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workflow_run_id", "stage_name", name="uq_workflow_steps_stage"),
        sa.UniqueConstraint("workflow_run_id", "position", name="uq_workflow_steps_position"),
    )
    op.create_index("ix_workflow_steps_workflow_run_id", "workflow_steps", ["workflow_run_id"])
    op.create_index("ix_workflow_steps_work_item_id", "workflow_steps", ["work_item_id"])

    op.create_table(
        "work_batch_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("video_id", sa.Integer(), nullable=True),
        sa.Column("work_item_id", sa.Integer(), nullable=True),
        sa.Column("workflow_run_id", sa.Integer(), nullable=True),
        sa.Column("selection_status", sa.String(32), nullable=False),
        sa.Column("reason", sa.String(128), nullable=True),
        sa.ForeignKeyConstraint(["batch_id"], ["work_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["work_item_id"], ["work_items.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_id", "position", name="uq_work_batch_items_position"),
    )
    op.create_index("ix_work_batch_items_batch_id", "work_batch_items", ["batch_id"])
    op.create_index("ix_work_batch_items_video", "work_batch_items", ["batch_id", "video_id"])

    op.create_table(
        "legacy_work_refs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("entity_kind", sa.String(64), nullable=False),
        sa.Column("legacy_id", sa.Integer(), nullable=False),
        sa.Column("work_item_id", sa.Integer(), nullable=True),
        sa.Column("work_attempt_id", sa.Integer(), nullable=True),
        sa.Column("work_batch_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["work_item_id"], ["work_items.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["work_attempt_id"], ["work_attempts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["work_batch_id"], ["work_batches.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("entity_kind", "legacy_id", name="uq_legacy_work_refs_entity"),
    )
    op.create_index("ix_legacy_work_refs_work_item_id", "legacy_work_refs", ["work_item_id"])
    op.create_index("ix_legacy_work_refs_work_attempt_id", "legacy_work_refs", ["work_attempt_id"])
    op.create_index("ix_legacy_work_refs_work_batch_id", "legacy_work_refs", ["work_batch_id"])


def _migrate_legacy_work() -> None:
    connection = op.get_bind()
    connection.execute(sa.text(_VIDEO_TASK_ITEMS_SQL))
    max_video_task_id = int(
        connection.execute(sa.text("SELECT COALESCE(MAX(id), 0) FROM video_tasks")).scalar_one()
    )
    connection.execute(sa.text(_STANDALONE_JOB_ITEMS_SQL), {"offset": max_video_task_id})
    connection.execute(sa.text(_VIDEO_TASK_REFS_SQL))
    connection.execute(sa.text(_PIPELINE_JOB_REFS_SQL), {"offset": max_video_task_id})
    connection.execute(sa.text(_WORK_ATTEMPTS_SQL), {"offset": max_video_task_id})
    connection.execute(sa.text(_ATTEMPT_REFS_SQL))
    connection.execute(sa.text(_LEGACY_BATCHES_SQL))
    connection.execute(sa.text(_BATCH_REFS_SQL))
    connection.execute(sa.text(_PARENT_DEPENDENCIES_SQL), {"offset": max_video_task_id})


_VIDEO_TASK_ITEMS_SQL = """
INSERT INTO work_items (
    id, task_type, subject_type, subject_id, external_key, task_version, input_hash,
    idempotency_key, execution_mode, status, outcome_code, priority, timeout_seconds,
    input_json, output_json, output_transcript_id, error_code, error_type, error_message,
    lease_owner, lease_expires_at, heartbeat_at, available_at, started_at, completed_at,
    created_at, updated_at
)
SELECT
    vt.id, vt.task_name, 'video', vt.video_id, v.youtube_video_id, vt.task_version,
    vt.input_hash, 'legacy:video_task:' || vt.id,
    CASE WHEN vt.task_name = 'archive_publish' THEN 'inline' ELSE 'worker' END,
    CASE
        WHEN vt.status = 'no_transcript' THEN 'succeeded'
        WHEN vt.status = 'skipped' THEN 'canceled'
        ELSE vt.status
    END,
    CASE
        WHEN vt.status = 'no_transcript' THEN 'no_transcript'
        WHEN vt.status = 'skipped' THEN 'legacy_skipped'
        ELSE NULL
    END,
    0, vt.timeout_seconds, COALESCE(vt.input_json, '{}'), vt.output_json,
    vt.output_transcript_id,
    CASE WHEN vt.status IN ('failed', 'timed_out') THEN 'legacy.' || vt.status ELSE NULL END,
    vt.error_type, vt.error_message,
    CASE WHEN vt.status = 'running' THEN vt.worker_id ELSE NULL END,
    CASE WHEN vt.status = 'running' THEN vt.updated_at ELSE NULL END,
    CASE WHEN vt.status = 'running' THEN vt.updated_at ELSE NULL END,
    COALESCE(vt.created_at, CURRENT_TIMESTAMP), vt.started_at, vt.completed_at,
    vt.created_at, vt.updated_at
FROM video_tasks vt
JOIN videos v ON v.id = vt.video_id
"""

_STANDALONE_JOB_ITEMS_SQL = """
INSERT INTO work_items (
    id, task_type, subject_type, subject_id, external_key, task_version, input_hash,
    idempotency_key, execution_mode, status, outcome_code, priority, timeout_seconds,
    input_json, output_json, error_code, error_type, error_message, lease_owner,
    lease_expires_at, heartbeat_at, available_at, started_at, completed_at, created_at, updated_at
)
SELECT
    :offset + j.id, j.step, COALESCE(j.subject_type, 'system'), j.subject_id,
    j.external_key, 'legacy-v1', j.input_hash, 'legacy:pipeline_job:' || j.id,
    CASE
        WHEN j.step IN ('channel_resolve', 'video_collect', 'archive_publish') THEN 'inline'
        ELSE 'worker'
    END,
    CASE WHEN j.status = 'skipped' THEN 'canceled' ELSE j.status END,
    CASE WHEN j.status = 'skipped' THEN 'legacy_skipped' ELSE NULL END,
    0,
    MAX(1, CAST(COALESCE(json_extract(j.input_json, '$.timeoutSeconds'), 600) AS INTEGER)),
    j.input_json,
    (SELECT a.output_json FROM pipeline_job_attempts a WHERE a.job_id = j.id
     ORDER BY a.attempt_no DESC LIMIT 1),
    CASE WHEN j.status = 'failed' THEN 'legacy.failed' ELSE NULL END,
    (SELECT a.error_type FROM pipeline_job_attempts a WHERE a.job_id = j.id
     ORDER BY a.attempt_no DESC LIMIT 1),
    (SELECT a.error_message FROM pipeline_job_attempts a WHERE a.job_id = j.id
     ORDER BY a.attempt_no DESC LIMIT 1),
    (SELECT a.worker_id FROM pipeline_job_attempts a WHERE a.job_id = j.id AND a.status = 'running'
     ORDER BY a.attempt_no DESC LIMIT 1),
    CASE WHEN j.status = 'running' THEN j.updated_at ELSE NULL END,
    CASE WHEN j.status = 'running' THEN j.updated_at ELSE NULL END,
    j.created_at,
    (SELECT MIN(a.started_at) FROM pipeline_job_attempts a WHERE a.job_id = j.id),
    j.completed_at, j.created_at, j.updated_at
FROM pipeline_jobs j
WHERE NOT EXISTS (
    SELECT 1 FROM video_tasks vt
    WHERE vt.id = CAST(json_extract(j.input_json, '$.videoTaskId') AS INTEGER)
       OR vt.job_id = j.id
)
"""

_VIDEO_TASK_REFS_SQL = """
INSERT INTO legacy_work_refs (entity_kind, legacy_id, work_item_id)
SELECT 'video_task', id, id FROM video_tasks
"""

_PIPELINE_JOB_REFS_SQL = """
INSERT INTO legacy_work_refs (entity_kind, legacy_id, work_item_id)
SELECT
    'pipeline_job', j.id,
    COALESCE(
        (SELECT vt.id FROM video_tasks vt
         WHERE vt.id = CAST(json_extract(j.input_json, '$.videoTaskId') AS INTEGER)
         LIMIT 1),
        (SELECT vt.id FROM video_tasks vt WHERE vt.job_id = j.id LIMIT 1),
        :offset + j.id
    )
FROM pipeline_jobs j
"""

_WORK_ATTEMPTS_SQL = """
WITH mapped AS (
    SELECT
        a.*,
        COALESCE(
            (SELECT vt.id FROM video_tasks vt
             JOIN pipeline_jobs pj ON pj.id = a.job_id
             WHERE vt.id = CAST(json_extract(pj.input_json, '$.videoTaskId') AS INTEGER)
             LIMIT 1),
            (SELECT vt.id FROM video_tasks vt WHERE vt.job_id = a.job_id LIMIT 1),
            :offset + a.job_id
        ) AS work_item_id
    FROM pipeline_job_attempts a
), numbered AS (
    SELECT mapped.*,
           ROW_NUMBER() OVER (
               PARTITION BY work_item_id ORDER BY started_at, id
           ) AS new_attempt_no
    FROM mapped
)
INSERT INTO work_attempts (
    id, work_item_id, attempt_no, status, worker_id, started_at, finished_at,
    output_json, error_code, error_type, error_message
)
SELECT
    id, work_item_id, new_attempt_no, status, worker_id, started_at, finished_at,
    output_json,
    CASE WHEN status = 'failed' THEN 'legacy.failed' ELSE NULL END,
    error_type, error_message
FROM numbered
"""

_ATTEMPT_REFS_SQL = """
INSERT INTO legacy_work_refs (entity_kind, legacy_id, work_attempt_id)
SELECT 'pipeline_job_attempt', id, id FROM pipeline_job_attempts
"""

_LEGACY_BATCHES_SQL = """
INSERT INTO work_batches (
    id, operation_type, status, actor_type, selection_json, options_json,
    requested_count, created_at, completed_at
)
SELECT
    id, step,
    CASE
        WHEN status = 'skipped' THEN 'canceled'
        WHEN status IN ('pending', 'running', 'succeeded', 'failed', 'canceled') THEN status
        ELSE 'failed'
    END,
    'system', input_json, input_json, 0, created_at, completed_at
FROM pipeline_jobs
WHERE step LIKE '%_batch'
"""

_BATCH_REFS_SQL = """
INSERT INTO legacy_work_refs (entity_kind, legacy_id, work_batch_id)
SELECT 'pipeline_batch_job', id, id FROM pipeline_jobs WHERE step LIKE '%_batch'
"""

_PARENT_DEPENDENCIES_SQL = """
INSERT OR IGNORE INTO work_item_dependencies (
    work_item_id, dependency_work_item_id, requires_successful_output
)
SELECT
    child_ref.work_item_id, parent_ref.work_item_id, 1
FROM pipeline_jobs child
JOIN legacy_work_refs child_ref
  ON child_ref.entity_kind = 'pipeline_job' AND child_ref.legacy_id = child.id
JOIN legacy_work_refs parent_ref
  ON parent_ref.entity_kind = 'pipeline_job' AND parent_ref.legacy_id = child.parent_job_id
WHERE child.parent_job_id IS NOT NULL
  AND child_ref.work_item_id <> parent_ref.work_item_id
"""
