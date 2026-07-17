"""expand work provenance columns

Revision ID: 20260711_0026
Revises: 20260711_0025
Create Date: 2026-07-11 00:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence
from hashlib import sha1

import sqlalchemy as sa

from alembic import op

revision: str = "20260711_0026"
down_revision: str | None = "20260711_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _add_provenance_columns()
    _populate_work_provenance()


def downgrade() -> None:
    for table_name, columns in reversed(tuple(_columns_by_table().items())):
        with op.batch_alter_table(table_name) as batch_op:
            for column_name, _target_table in reversed(columns):
                batch_op.drop_index(_identifier("ix", table_name, column_name))
                batch_op.drop_column(column_name)


def _add_provenance_columns() -> None:
    for table_name, columns in _columns_by_table().items():
        with op.batch_alter_table(table_name) as batch_op:
            for column_name, target_table in columns:
                batch_op.add_column(sa.Column(column_name, sa.Integer(), nullable=True))
                batch_op.create_foreign_key(
                    _identifier("fk", table_name, column_name, target_table),
                    target_table,
                    [column_name],
                    ["id"],
                    ondelete="SET NULL",
                )
                batch_op.create_index(
                    _identifier("ix", table_name, column_name),
                    [column_name],
                )


def _identifier(*parts: str) -> str:
    value = "_".join(parts)
    if len(value) <= 63:
        return value
    digest = sha1(value.encode("ascii")).hexdigest()[:8]
    return f"{value[:54]}_{digest}"


def _columns_by_table() -> dict[str, list[tuple[str, str]]]:
    grouped: dict[str, list[tuple[str, str]]] = {}
    for table_name, column_name, target_table in _PROVENANCE_COLUMNS:
        grouped.setdefault(table_name, []).append((column_name, target_table))
    return grouped


def _populate_work_provenance() -> None:
    connection = op.get_bind()
    for statement in _POPULATE_STATEMENTS:
        connection.execute(sa.text(statement))


_ITEM_COLUMNS = (
    ("channels", "source_work_item_id", "work_items"),
    ("videos", "source_work_item_id", "work_items"),
    ("codex_run_usages", "work_item_id", "work_items"),
    ("operation_events", "work_item_id", "work_items"),
    ("transcript_cues", "source_work_item_id", "work_items"),
    ("micro_event_extraction_windows", "work_item_id", "work_items"),
    ("micro_event_candidates", "work_item_id", "work_items"),
    ("micro_event_excluded_ranges", "work_item_id", "work_items"),
    ("asr_correction_candidates", "work_item_id", "work_items"),
    ("timeline_compositions", "work_item_id", "work_items"),
    ("timeline_compositions", "source_micro_event_work_item_id", "work_items"),
    ("archive_video_artifacts", "source_timeline_work_item_id", "work_items"),
    ("archive_video_artifacts", "source_micro_event_work_item_id", "work_items"),
    ("archive_video_artifacts", "publish_work_item_id", "work_items"),
)

_ATTEMPT_COLUMNS = (
    ("external_api_calls", "work_attempt_id", "work_attempts"),
    ("codex_run_usages", "work_attempt_id", "work_attempts"),
    ("operation_events", "work_attempt_id", "work_attempts"),
    ("transcript_cues", "source_work_attempt_id", "work_attempts"),
    ("micro_event_extraction_windows", "source_work_attempt_id", "work_attempts"),
    ("timeline_compositions", "source_work_attempt_id", "work_attempts"),
    ("archive_video_artifacts", "publish_work_attempt_id", "work_attempts"),
)

_PROVENANCE_COLUMNS = (
    *_ITEM_COLUMNS,
    *_ATTEMPT_COLUMNS,
    ("operation_events", "work_batch_id", "work_batches"),
)

_POPULATE_STATEMENTS = (
    """
    UPDATE channels
    SET source_work_item_id = (
        SELECT work_item_id FROM legacy_work_refs
        WHERE entity_kind = 'pipeline_job' AND legacy_id = channels.source_job_id
    )
    WHERE source_job_id IS NOT NULL
    """,
    """
    UPDATE videos
    SET source_work_item_id = (
        SELECT work_item_id FROM legacy_work_refs
        WHERE entity_kind = 'pipeline_job' AND legacy_id = videos.source_job_id
    )
    WHERE source_job_id IS NOT NULL
    """,
    """
    UPDATE external_api_calls
    SET work_attempt_id = (
        SELECT work_attempt_id FROM legacy_work_refs
        WHERE entity_kind = 'pipeline_job_attempt'
          AND legacy_id = external_api_calls.pipeline_job_attempt_id
    )
    WHERE pipeline_job_attempt_id IS NOT NULL
    """,
    """
    UPDATE codex_run_usages
    SET work_item_id = COALESCE(
        (SELECT work_item_id FROM legacy_work_refs
         WHERE entity_kind = 'video_task'
           AND legacy_id = codex_run_usages.video_task_id),
        (SELECT work_item_id FROM legacy_work_refs
         WHERE entity_kind = 'pipeline_job'
           AND legacy_id = codex_run_usages.job_id)
    ),
    work_attempt_id = (
        SELECT work_attempt_id FROM legacy_work_refs
        WHERE entity_kind = 'pipeline_job_attempt'
          AND legacy_id = codex_run_usages.job_attempt_id
    )
    """,
    """
    UPDATE operation_events
    SET work_item_id = COALESCE(
        (SELECT work_item_id FROM legacy_work_refs
         WHERE entity_kind = 'video_task'
           AND legacy_id = operation_events.video_task_id),
        (SELECT work_item_id FROM legacy_work_refs
         WHERE entity_kind = 'pipeline_job'
           AND legacy_id = operation_events.job_id)
    ),
    work_attempt_id = (
        SELECT work_attempt_id FROM legacy_work_refs
        WHERE entity_kind = 'pipeline_job_attempt'
          AND legacy_id = operation_events.job_attempt_id
    ),
    work_batch_id = (
        SELECT work_batch_id FROM legacy_work_refs
        WHERE entity_kind = 'pipeline_batch_job'
          AND legacy_id = operation_events.job_id
    )
    """,
    """
    UPDATE transcript_cues
    SET source_work_item_id = (
        SELECT work_item_id FROM legacy_work_refs
        WHERE entity_kind = 'pipeline_job'
          AND legacy_id = transcript_cues.source_job_id
    ),
    source_work_attempt_id = (
        SELECT work_attempt_id FROM legacy_work_refs
        WHERE entity_kind = 'pipeline_job_attempt'
          AND legacy_id = transcript_cues.source_job_attempt_id
    )
    """,
    """
    UPDATE micro_event_extraction_windows
    SET work_item_id = video_task_id,
    source_work_attempt_id = (
        SELECT work_attempt_id FROM legacy_work_refs
        WHERE entity_kind = 'pipeline_job_attempt'
          AND legacy_id = micro_event_extraction_windows.source_job_attempt_id
    )
    """,
    "UPDATE micro_event_candidates SET work_item_id = video_task_id",
    "UPDATE micro_event_excluded_ranges SET work_item_id = video_task_id",
    "UPDATE asr_correction_candidates SET work_item_id = video_task_id",
    """
    UPDATE timeline_compositions
    SET work_item_id = video_task_id,
        source_micro_event_work_item_id = source_micro_event_task_id,
        source_work_attempt_id = (
            SELECT work_attempt_id FROM legacy_work_refs
            WHERE entity_kind = 'pipeline_job_attempt'
              AND legacy_id = timeline_compositions.source_job_attempt_id
        )
    """,
    """
    UPDATE archive_video_artifacts
    SET source_timeline_work_item_id = source_timeline_task_id,
        source_micro_event_work_item_id = source_micro_event_task_id,
        publish_work_item_id = COALESCE(
            publish_task_id,
            (SELECT work_item_id FROM legacy_work_refs
             WHERE entity_kind = 'pipeline_job'
               AND legacy_id = archive_video_artifacts.publish_job_id)
        ),
        publish_work_attempt_id = (
            SELECT refs.work_attempt_id
            FROM pipeline_job_attempts attempts
            JOIN legacy_work_refs refs
              ON refs.entity_kind = 'pipeline_job_attempt'
             AND refs.legacy_id = attempts.id
            WHERE attempts.job_id = archive_video_artifacts.publish_job_id
            ORDER BY attempts.attempt_no DESC
            LIMIT 1
        )
    """,
)
