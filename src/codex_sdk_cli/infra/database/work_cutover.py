from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

PRESERVED_TABLES = (
    "streamers",
    "channels",
    "videos",
    "youtube_transcripts",
    "transcript_cues",
    "external_api_calls",
    "micro_event_extraction_windows",
    "micro_event_candidates",
    "micro_event_excluded_ranges",
    "asr_correction_candidates",
    "timeline_compositions",
    "timeline_blocks",
    "timeline_episodes",
    "timeline_topic_clusters",
    "timeline_review_flags",
    "archive_video_artifacts",
    "archive_index_publications",
    "codex_run_usages",
    "operation_events",
)

ForeignKeyViolation = tuple[
    str,
    int | None,
    str,
    tuple[tuple[str, str, object], ...],
]


@dataclass(frozen=True, slots=True)
class CutoverValidation:
    source: str
    candidate: str
    preserved_table_counts: dict[str, int]
    work_item_count: int
    work_attempt_count: int
    legacy_ref_count: int
    preexisting_foreign_key_violation_count: int


def validate_work_cutover(source_path: Path, candidate_path: Path) -> CutoverValidation:
    source = _connect(source_path)
    candidate = _connect(candidate_path)
    try:
        counts = _validate_preserved_rows(source, candidate)
        preexisting_foreign_key_violation_count = _validate_candidate_integrity(
            source,
            candidate,
        )
        _validate_legacy_mappings(source, candidate)
        _validate_provenance(candidate)
        return CutoverValidation(
            source=str(source_path.resolve()),
            candidate=str(candidate_path.resolve()),
            preserved_table_counts=counts,
            work_item_count=_count(candidate, "work_items"),
            work_attempt_count=_count(candidate, "work_attempts"),
            legacy_ref_count=_count(candidate, "legacy_work_refs"),
            preexisting_foreign_key_violation_count=(
                preexisting_foreign_key_violation_count
            ),
        )
    finally:
        source.close()
        candidate.close()


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _validate_preserved_rows(
    source: sqlite3.Connection,
    candidate: sqlite3.Connection,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in PRESERVED_TABLES:
        if not _table_exists(source, table):
            continue
        if not _table_exists(candidate, table):
            raise RuntimeError(f"Candidate is missing preserved table {table}.")
        source_ids = _primary_keys(source, table)
        candidate_ids = _primary_keys(candidate, table)
        if source_ids != candidate_ids:
            raise RuntimeError(f"Primary keys changed for preserved table {table}.")
        counts[table] = len(source_ids)
    _compare_values(source, candidate, "youtube_transcripts", "id", "storage_object_name")
    _compare_values(source, candidate, "archive_video_artifacts", "id", "object_key")
    _compare_values(source, candidate, "archive_video_artifacts", "id", "public_url")
    return counts


def _validate_candidate_integrity(
    source: sqlite3.Connection,
    candidate: sqlite3.Connection,
) -> int:
    integrity = candidate.execute("PRAGMA integrity_check").fetchone()
    if integrity is None or integrity[0] != "ok":
        raise RuntimeError(f"Candidate integrity check failed: {integrity!r}")
    source_foreign_key_errors = _foreign_key_violations(source)
    candidate_foreign_key_errors = _foreign_key_violations(candidate)
    if candidate_foreign_key_errors != source_foreign_key_errors:
        added = sorted(candidate_foreign_key_errors - source_foreign_key_errors)
        removed = sorted(source_foreign_key_errors - candidate_foreign_key_errors)
        raise RuntimeError(
            "Candidate changed the foreign-key violation baseline: "
            f"added={added[:10]!r}, removed={removed[:10]!r}"
        )
    for table in (
        "work_items",
        "work_attempts",
        "work_item_dependencies",
        "work_batches",
        "work_batch_items",
        "workflow_runs",
        "workflow_steps",
        "legacy_work_refs",
    ):
        if not _table_exists(candidate, table):
            raise RuntimeError(f"Candidate is missing work table {table}.")
    return len(source_foreign_key_errors)


def _foreign_key_violations(
    connection: sqlite3.Connection,
) -> set[ForeignKeyViolation]:
    violations: set[ForeignKeyViolation] = set()
    for table, row_id, parent, foreign_key_id in connection.execute(
        "PRAGMA foreign_key_check"
    ):
        column_pairs = tuple(
            (str(row[3]), str(row[4]))
            for row in connection.execute(f"PRAGMA foreign_key_list({table})")
            if row[0] == foreign_key_id
        )
        values: tuple[object, ...]
        if row_id is None:
            values = (None,) * len(column_pairs)
        else:
            selected = ", ".join(_quote_identifier(source) for source, _ in column_pairs)
            row = connection.execute(
                f"SELECT {selected} FROM {_quote_identifier(str(table))} WHERE rowid = ?",
                (row_id,),
            ).fetchone()
            values = tuple(row) if row is not None else (None,) * len(column_pairs)
        columns = tuple(
            (source, target, value)
            for (source, target), value in zip(column_pairs, values, strict=True)
        )
        violations.add((str(table), row_id, str(parent), columns))
    return violations


def _quote_identifier(identifier: str) -> str:
    return f'"{identifier.replace(chr(34), chr(34) * 2)}"'


def _validate_legacy_mappings(
    source: sqlite3.Connection,
    candidate: sqlite3.Connection,
) -> None:
    mapping_tables = (
        ("video_tasks", "video_task", "work_item_id"),
        ("pipeline_jobs", "pipeline_job", "work_item_id"),
        ("pipeline_job_attempts", "pipeline_job_attempt", "work_attempt_id"),
    )
    for legacy_table, entity_kind, target_column in mapping_tables:
        if not _table_exists(source, legacy_table):
            continue
        legacy_count = _count(source, legacy_table)
        mapped_count = candidate.execute(
            f"SELECT COUNT(*) FROM legacy_work_refs "
            f"WHERE entity_kind = ? AND {target_column} IS NOT NULL",
            (entity_kind,),
        ).fetchone()[0]
        if legacy_count != mapped_count:
            raise RuntimeError(
                f"{legacy_table} mapping count mismatch: {legacy_count} != {mapped_count}"
            )
    if _table_exists(source, "video_tasks"):
        no_transcript = candidate.execute(
            "SELECT COUNT(*) FROM video_tasks vt "
            "JOIN legacy_work_refs refs ON refs.entity_kind='video_task' "
            "AND refs.legacy_id=vt.id "
            "JOIN work_items wi ON wi.id=refs.work_item_id "
            "WHERE vt.status='no_transcript' "
            "AND (wi.status<>'succeeded' OR wi.outcome_code<>'no_transcript')"
        ).fetchone()[0]
        if no_transcript:
            raise RuntimeError("no_transcript tasks were not normalized to succeeded outcomes.")


def _validate_provenance(candidate: sqlite3.Connection) -> None:
    checks = (
        ("micro_event_extraction_windows", "video_task_id", "work_item_id"),
        ("timeline_compositions", "video_task_id", "work_item_id"),
        ("archive_video_artifacts", "publish_task_id", "publish_work_item_id"),
    )
    for table, legacy_column, work_column in checks:
        if not _table_exists(candidate, table):
            continue
        missing = candidate.execute(
            f"SELECT COUNT(*) FROM {table} "
            f"WHERE {legacy_column} IS NOT NULL AND {work_column} IS NULL"
        ).fetchone()[0]
        if missing:
            raise RuntimeError(f"{table} has {missing} row(s) without work provenance.")


def _compare_values(
    source: sqlite3.Connection,
    candidate: sqlite3.Connection,
    table: str,
    key: str,
    value: str,
) -> None:
    if not _table_exists(source, table) or not _table_exists(candidate, table):
        return
    source_rows = dict(source.execute(f"SELECT {key}, {value} FROM {table}"))
    candidate_rows = dict(candidate.execute(f"SELECT {key}, {value} FROM {table}"))
    if source_rows != candidate_rows:
        raise RuntimeError(f"Preserved values changed for {table}.{value}.")


def _primary_keys(connection: sqlite3.Connection, table: str) -> set[tuple[object, ...]]:
    columns = [
        row[1]
        for row in sorted(
            (row for row in connection.execute(f"PRAGMA table_info({table})") if row[5]),
            key=lambda row: row[5],
        )
    ]
    if not columns:
        return {(index,) for index in range(_count(connection, table))}
    selected = ", ".join(columns)
    return {tuple(row) for row in connection.execute(f"SELECT {selected} FROM {table}")}


def _count(connection: sqlite3.Connection, table: str) -> int:
    return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        is not None
    )
