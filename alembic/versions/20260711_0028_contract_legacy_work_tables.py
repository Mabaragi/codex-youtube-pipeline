"""contract legacy task and pipeline job tables

Revision ID: 20260711_0028
Revises: 20260711_0027
Create Date: 2026-07-11 18:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260711_0028"
down_revision: str | None = "20260711_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JOB_COLUMNS = (
    ("channels", "source_job_id"),
    ("videos", "source_job_id"),
    ("operation_events", "job_id"),
    ("transcript_cues", "source_job_id"),
    ("micro_event_extraction_windows", "source_job_id"),
    ("timeline_compositions", "source_job_id"),
    ("codex_run_usages", "job_id"),
    ("archive_video_artifacts", "publish_job_id"),
)

_ATTEMPT_COLUMNS = (
    ("external_api_calls", "pipeline_job_attempt_id"),
    ("operation_events", "job_attempt_id"),
    ("transcript_cues", "source_job_attempt_id"),
    ("micro_event_extraction_windows", "source_job_attempt_id"),
    ("timeline_compositions", "source_job_attempt_id"),
    ("codex_run_usages", "job_attempt_id"),
)

_FOREIGN_KEYS = {
    "channels": (("source_job_id", "pipeline_jobs", "work_items", "SET NULL"),),
    "videos": (("source_job_id", "pipeline_jobs", "work_items", "SET NULL"),),
    "external_api_calls": (
        ("pipeline_job_attempt_id", "pipeline_job_attempts", "work_attempts", "SET NULL"),
    ),
    "operation_events": (
        ("job_id", "pipeline_jobs", "work_items", "SET NULL"),
        ("job_attempt_id", "pipeline_job_attempts", "work_attempts", "SET NULL"),
        ("video_task_id", "video_tasks", "work_items", "SET NULL"),
    ),
    "transcript_cues": (
        ("source_job_id", "pipeline_jobs", "work_items", "SET NULL"),
        ("source_job_attempt_id", "pipeline_job_attempts", "work_attempts", "SET NULL"),
    ),
    "micro_event_extraction_windows": (
        ("video_task_id", "video_tasks", "work_items", "CASCADE"),
        ("source_job_id", "pipeline_jobs", "work_items", "SET NULL"),
        ("source_job_attempt_id", "pipeline_job_attempts", "work_attempts", "SET NULL"),
    ),
    "micro_event_candidates": (
        ("video_task_id", "video_tasks", "work_items", "CASCADE"),
    ),
    "micro_event_excluded_ranges": (
        ("video_task_id", "video_tasks", "work_items", "CASCADE"),
    ),
    "asr_correction_candidates": (
        ("video_task_id", "video_tasks", "work_items", "CASCADE"),
    ),
    "timeline_compositions": (
        ("video_task_id", "video_tasks", "work_items", "CASCADE"),
        ("source_micro_event_task_id", "video_tasks", "work_items", "RESTRICT"),
        ("source_job_id", "pipeline_jobs", "work_items", "SET NULL"),
        ("source_job_attempt_id", "pipeline_job_attempts", "work_attempts", "SET NULL"),
    ),
    "codex_run_usages": (
        ("video_task_id", "video_tasks", "work_items", "SET NULL"),
        ("job_id", "pipeline_jobs", "work_items", "SET NULL"),
        ("job_attempt_id", "pipeline_job_attempts", "work_attempts", "SET NULL"),
    ),
    "archive_video_artifacts": (
        ("source_micro_event_task_id", "video_tasks", "work_items", "RESTRICT"),
        ("source_timeline_task_id", "video_tasks", "work_items", "RESTRICT"),
        ("publish_task_id", "video_tasks", "work_items", "RESTRICT"),
        ("publish_job_id", "pipeline_jobs", "work_items", "RESTRICT"),
    ),
}


def upgrade() -> None:
    connection = op.get_bind()
    _backfill_post_expand_refs(connection)
    _map_legacy_ids(connection, _JOB_COLUMNS, "pipeline_job", "work_item_id")
    _map_legacy_ids(
        connection,
        _ATTEMPT_COLUMNS,
        "pipeline_job_attempt",
        "work_attempt_id",
    )
    for table_name, constraints in _FOREIGN_KEYS.items():
        _rewire_table(table_name, constraints)
    op.drop_table("pipeline_job_attempts")
    op.drop_table("pipeline_jobs")
    op.drop_table("video_tasks")
    _create_compatibility_views(connection)


def downgrade() -> None:
    raise RuntimeError(
        "The legacy work-table contract migration is intentionally irreversible. "
        "Restore the pre-cutover database backup to roll back."
    )


def _map_legacy_ids(
    connection: sa.engine.Connection,
    columns: tuple[tuple[str, str], ...],
    entity_kind: str,
    target_column: str,
) -> None:
    for table_name, column_name in columns:
        connection.execute(
            sa.text(
                f"""
                UPDATE {table_name}
                SET {column_name} = COALESCE(
                    (
                        SELECT {target_column}
                        FROM legacy_work_refs
                        WHERE entity_kind = :entity_kind
                          AND legacy_id = {table_name}.{column_name}
                    ),
                    {column_name}
                )
                WHERE {column_name} IS NOT NULL
                """
            ),
            {"entity_kind": entity_kind},
        )


def _backfill_post_expand_refs(connection: sa.engine.Connection) -> None:
    _backfill_refs_from_provenance(connection)
    _backfill_task_linked_refs(connection)
    _backfill_unmapped_jobs(connection)
    _backfill_attempt_refs(connection)


def _backfill_refs_from_provenance(connection: sa.engine.Connection) -> None:
    job_pairs = (
        ("channels", "source_job_id", "source_work_item_id"),
        ("videos", "source_job_id", "source_work_item_id"),
        ("operation_events", "job_id", "work_item_id"),
        ("transcript_cues", "source_job_id", "source_work_item_id"),
        ("micro_event_extraction_windows", "source_job_id", "work_item_id"),
        ("timeline_compositions", "source_job_id", "work_item_id"),
        ("codex_run_usages", "job_id", "work_item_id"),
        ("archive_video_artifacts", "publish_job_id", "publish_work_item_id"),
    )
    attempt_pairs = (
        ("external_api_calls", "pipeline_job_attempt_id", "work_attempt_id"),
        ("operation_events", "job_attempt_id", "work_attempt_id"),
        ("transcript_cues", "source_job_attempt_id", "source_work_attempt_id"),
        (
            "micro_event_extraction_windows",
            "source_job_attempt_id",
            "source_work_attempt_id",
        ),
        ("timeline_compositions", "source_job_attempt_id", "source_work_attempt_id"),
        ("codex_run_usages", "job_attempt_id", "work_attempt_id"),
    )
    for table_name, legacy_column, work_column in job_pairs:
        _insert_refs_from_pair(
            connection,
            table_name=table_name,
            legacy_column=legacy_column,
            work_column=work_column,
            entity_kind="pipeline_job",
            ref_column="work_item_id",
        )
    for table_name, legacy_column, work_column in attempt_pairs:
        _insert_refs_from_pair(
            connection,
            table_name=table_name,
            legacy_column=legacy_column,
            work_column=work_column,
            entity_kind="pipeline_job_attempt",
            ref_column="work_attempt_id",
        )


def _insert_refs_from_pair(
    connection: sa.engine.Connection,
    *,
    table_name: str,
    legacy_column: str,
    work_column: str,
    entity_kind: str,
    ref_column: str,
) -> None:
    connection.execute(
        sa.text(
            f"""
            INSERT OR IGNORE INTO legacy_work_refs (
                entity_kind, legacy_id, {ref_column}
            )
            SELECT DISTINCT :entity_kind, {legacy_column}, {work_column}
            FROM {table_name}
            WHERE {legacy_column} IS NOT NULL
              AND {work_column} IS NOT NULL
            """
        ),
        {"entity_kind": entity_kind},
    )


def _backfill_task_linked_refs(connection: sa.engine.Connection) -> None:
    connection.execute(
        sa.text(
            """
            INSERT OR IGNORE INTO legacy_work_refs (
                entity_kind, legacy_id, work_item_id
            )
            SELECT 'pipeline_job', vt.job_id, task_ref.work_item_id
            FROM video_tasks vt
            JOIN legacy_work_refs task_ref
              ON task_ref.entity_kind = 'video_task'
             AND task_ref.legacy_id = vt.id
            WHERE vt.job_id IS NOT NULL
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT OR IGNORE INTO legacy_work_refs (
                entity_kind, legacy_id, work_attempt_id
            )
            SELECT 'pipeline_job_attempt', vt.job_attempt_id, attempt_ref.work_attempt_id
            FROM video_tasks vt
            JOIN legacy_work_refs attempt_ref
              ON attempt_ref.entity_kind = 'pipeline_job_attempt'
             AND attempt_ref.legacy_id = vt.job_attempt_id
            WHERE vt.job_attempt_id IS NOT NULL
            """
        )
    )


def _backfill_unmapped_jobs(connection: sa.engine.Connection) -> None:
    jobs = list(
        connection.execute(
            sa.text(
            """
            SELECT j.*
            FROM pipeline_jobs j
            LEFT JOIN legacy_work_refs ref
              ON ref.entity_kind = 'pipeline_job' AND ref.legacy_id = j.id
            WHERE ref.id IS NULL
            ORDER BY j.id
            """
            )
        ).mappings()
    )
    for job in jobs:
        work_item_id = connection.execute(
            sa.text(
                """
                INSERT INTO work_items (
                    task_type, subject_type, subject_id, external_key, task_version,
                    input_hash, idempotency_key, execution_mode, status, outcome_code,
                    priority, timeout_seconds, input_json, output_json, error_code,
                    error_type, error_message, available_at, started_at, completed_at,
                    created_at, updated_at
                )
                VALUES (
                    :task_type, :subject_type, :subject_id, :external_key, 'contract-v1',
                    :input_hash, :idempotency_key, :execution_mode, :status, :outcome_code,
                    0, :timeout_seconds, COALESCE(:input_json, '{}'),
                    (SELECT output_json FROM pipeline_job_attempts
                     WHERE job_id = :legacy_job_id ORDER BY attempt_no DESC LIMIT 1),
                    :error_code,
                    (SELECT error_type FROM pipeline_job_attempts
                     WHERE job_id = :legacy_job_id ORDER BY attempt_no DESC LIMIT 1),
                    (SELECT error_message FROM pipeline_job_attempts
                     WHERE job_id = :legacy_job_id ORDER BY attempt_no DESC LIMIT 1),
                    COALESCE(:created_at, CURRENT_TIMESTAMP),
                    (SELECT MIN(started_at) FROM pipeline_job_attempts
                     WHERE job_id = :legacy_job_id),
                    :completed_at, :created_at, :updated_at
                )
                RETURNING id
                """
            ),
            {
                "task_type": job["step"],
                "subject_type": job["subject_type"] or "system",
                "subject_id": job["subject_id"],
                "external_key": job["external_key"],
                "input_hash": job["input_hash"],
                "idempotency_key": f"contract:pipeline_job:{job['id']}",
                "execution_mode": (
                    "inline"
                    if job["step"]
                    in {"channel_resolve", "video_collect", "archive_publish"}
                    else "worker"
                ),
                "status": "canceled" if job["status"] == "skipped" else job["status"],
                "outcome_code": "legacy_skipped" if job["status"] == "skipped" else None,
                "timeout_seconds": 600,
                "input_json": job["input_json"],
                "error_code": "legacy.failed" if job["status"] == "failed" else None,
                "legacy_job_id": job["id"],
                "completed_at": job["completed_at"],
                "created_at": job["created_at"],
                "updated_at": job["updated_at"],
            },
        ).scalar_one()
        connection.execute(
            sa.text(
                """
                INSERT INTO legacy_work_refs (entity_kind, legacy_id, work_item_id)
                VALUES ('pipeline_job', :legacy_id, :work_item_id)
                """
            ),
            {"legacy_id": job["id"], "work_item_id": work_item_id},
        )


def _backfill_attempt_refs(connection: sa.engine.Connection) -> None:
    attempts = list(
        connection.execute(
            sa.text(
            """
            SELECT a.*, job_ref.work_item_id
            FROM pipeline_job_attempts a
            JOIN legacy_work_refs job_ref
              ON job_ref.entity_kind = 'pipeline_job'
             AND job_ref.legacy_id = a.job_id
            LEFT JOIN legacy_work_refs attempt_ref
              ON attempt_ref.entity_kind = 'pipeline_job_attempt'
             AND attempt_ref.legacy_id = a.id
            WHERE attempt_ref.id IS NULL
            ORDER BY a.id
            """
            )
        ).mappings()
    )
    for attempt in attempts:
        existing_id = connection.execute(
            sa.text(
                """
                SELECT id FROM work_attempts
                WHERE work_item_id = :work_item_id AND attempt_no = :attempt_no
                """
            ),
            {
                "work_item_id": attempt["work_item_id"],
                "attempt_no": attempt["attempt_no"],
            },
        ).scalar_one_or_none()
        work_attempt_id = existing_id
        if work_attempt_id is None:
            work_attempt_id = connection.execute(
                sa.text(
                    """
                    INSERT INTO work_attempts (
                        work_item_id, attempt_no, status, worker_id, started_at,
                        finished_at, output_json, error_code, error_type, error_message
                    )
                    VALUES (
                        :work_item_id, :attempt_no, :status, :worker_id, :started_at,
                        :finished_at, :output_json, :error_code, :error_type, :error_message
                    )
                    RETURNING id
                    """
                ),
                {
                    "work_item_id": attempt["work_item_id"],
                    "attempt_no": attempt["attempt_no"],
                    "status": attempt["status"],
                    "worker_id": attempt["worker_id"],
                    "started_at": attempt["started_at"],
                    "finished_at": attempt["finished_at"],
                    "output_json": attempt["output_json"],
                    "error_code": (
                        "legacy.failed" if attempt["status"] == "failed" else None
                    ),
                    "error_type": attempt["error_type"],
                    "error_message": attempt["error_message"],
                },
            ).scalar_one()
        connection.execute(
            sa.text(
                """
                INSERT INTO legacy_work_refs (entity_kind, legacy_id, work_attempt_id)
                VALUES ('pipeline_job_attempt', :legacy_id, :work_attempt_id)
                """
            ),
            {"legacy_id": attempt["id"], "work_attempt_id": work_attempt_id},
        )


def _rewire_table(
    table_name: str,
    constraints: tuple[tuple[str, str, str, str], ...],
) -> None:
    with op.batch_alter_table(table_name) as batch_op:
        for column_name, old_table, new_table, ondelete in constraints:
            batch_op.drop_constraint(
                op.f(f"fk_{table_name}_{column_name}_{old_table}"),
                type_="foreignkey",
            )
            batch_op.create_foreign_key(
                op.f(f"fk_{table_name}_{column_name}_{new_table}"),
                new_table,
                [column_name],
                ["id"],
                ondelete=ondelete,
            )


def _create_compatibility_views(connection: sa.engine.Connection) -> None:
    connection.execute(
        sa.text(
            """
            CREATE VIEW video_tasks AS
            SELECT
                wi.id,
                wi.subject_id AS video_id,
                wi.task_type AS task_name,
                wi.task_version,
                wi.input_hash,
                CASE
                    WHEN wi.status = 'succeeded' AND wi.outcome_code = 'no_transcript'
                        THEN 'no_transcript'
                    WHEN wi.status = 'canceled' AND wi.outcome_code = 'legacy_skipped'
                        THEN 'skipped'
                    WHEN wi.status = 'blocked' THEN 'failed'
                    ELSE wi.status
                END AS status,
                wi.lease_owner AS worker_id,
                wi.timeout_seconds,
                wi.input_json,
                CASE WHEN EXISTS (
                    SELECT 1 FROM work_attempts wa WHERE wa.work_item_id = wi.id
                ) THEN wi.id ELSE NULL END AS job_id,
                (
                    SELECT wa.id FROM work_attempts wa
                    WHERE wa.work_item_id = wi.id
                    ORDER BY wa.attempt_no DESC LIMIT 1
                ) AS job_attempt_id,
                wi.output_transcript_id,
                wi.output_json,
                wi.error_type,
                wi.error_message,
                wi.started_at,
                wi.completed_at,
                wi.created_at,
                wi.updated_at
            FROM work_items wi
            WHERE wi.subject_type = 'video'
            """
        )
    )
    connection.execute(
        sa.text(
            """
            CREATE VIEW pipeline_jobs AS
            SELECT
                id,
                task_type AS step,
                CASE
                    WHEN status IN ('timed_out', 'blocked') THEN 'failed'
                    ELSE status
                END AS status,
                subject_type,
                subject_id,
                external_key,
                input_json,
                input_hash,
                NULL AS parent_job_id,
                created_at,
                updated_at,
                completed_at
            FROM work_items
            """
        )
    )
    connection.execute(
        sa.text(
            """
            CREATE VIEW pipeline_job_attempts AS
            SELECT
                id,
                work_item_id AS job_id,
                attempt_no,
                CASE WHEN status = 'timed_out' THEN 'failed' ELSE status END AS status,
                started_at,
                finished_at,
                worker_id,
                error_type,
                error_message,
                output_json
            FROM work_attempts
            """
        )
    )
