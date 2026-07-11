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


@dataclass(frozen=True, slots=True)
class CutoverValidation:
    source: str
    candidate: str
    preserved_table_counts: dict[str, int]
    work_item_count: int
    work_attempt_count: int
    legacy_ref_count: int


def validate_work_cutover(source_path: Path, candidate_path: Path) -> CutoverValidation:
    source = _connect(source_path)
    candidate = _connect(candidate_path)
    try:
        counts = _validate_preserved_rows(source, candidate)
        _validate_candidate_integrity(candidate)
        _validate_legacy_mappings(source, candidate)
        _validate_provenance(candidate)
        return CutoverValidation(
            source=str(source_path.resolve()),
            candidate=str(candidate_path.resolve()),
            preserved_table_counts=counts,
            work_item_count=_count(candidate, "work_items"),
            work_attempt_count=_count(candidate, "work_attempts"),
            legacy_ref_count=_count(candidate, "legacy_work_refs"),
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


def _validate_candidate_integrity(candidate: sqlite3.Connection) -> None:
    integrity = candidate.execute("PRAGMA integrity_check").fetchone()
    if integrity is None or integrity[0] != "ok":
        raise RuntimeError(f"Candidate integrity check failed: {integrity!r}")
    foreign_key_errors = candidate.execute("PRAGMA foreign_key_check").fetchall()
    if foreign_key_errors:
        raise RuntimeError(f"Candidate has dangling foreign keys: {foreign_key_errors[:10]!r}")
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
