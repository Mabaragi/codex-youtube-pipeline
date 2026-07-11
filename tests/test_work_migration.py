from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command


def test_work_expand_migration_preserves_legacy_execution_history(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "work-migration.db"
    monkeypatch.setenv(
        "CODEX_CLI_DATABASE_URL",
        f"sqlite+aiosqlite:///{database_path.as_posix()}",
    )
    config = _alembic_config()
    command.upgrade(config, "20260704_0024")
    _insert_legacy_fixture(database_path)

    command.upgrade(config, "head")

    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        migrated_task = connection.execute("SELECT * FROM work_items WHERE id = 5").fetchone()
        assert migrated_task is not None
        assert migrated_task["task_type"] == "transcript_collect"
        assert migrated_task["status"] == "succeeded"
        assert migrated_task["outcome_code"] == "no_transcript"
        assert migrated_task["output_transcript_id"] == 3

        job_refs = {
            row["legacy_id"]: row["work_item_id"]
            for row in connection.execute(
                "SELECT legacy_id, work_item_id FROM legacy_work_refs "
                "WHERE entity_kind = 'pipeline_job' ORDER BY legacy_id"
            )
        }
        assert job_refs[10] == 5
        assert job_refs[11] == 16
        assert job_refs[12] == 17

        linked_attempts = connection.execute(
            "SELECT id, attempt_no, status FROM work_attempts "
            "WHERE work_item_id = 5 ORDER BY attempt_no"
        ).fetchall()
        assert [tuple(row) for row in linked_attempts] == [
            (100, 1, "failed"),
            (101, 2, "succeeded"),
        ]
        assert (
            connection.execute(
                "SELECT work_attempt_id FROM legacy_work_refs "
                "WHERE entity_kind = 'pipeline_job_attempt' AND legacy_id = 101"
            ).fetchone()[0]
            == 101
        )

        batch = connection.execute(
            "SELECT id, operation_type, status FROM work_batches WHERE id = 12"
        ).fetchone()
        assert tuple(batch) == (12, "transcript_collect_batch", "succeeded")

        dependency = connection.execute(
            "SELECT work_item_id, dependency_work_item_id "
            "FROM work_item_dependencies WHERE work_item_id = 16"
        ).fetchone()
        assert tuple(dependency) == (16, 5)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()


def _insert_legacy_fixture(database_path: Path) -> None:
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("INSERT INTO streamers(id, name) VALUES (1, 'Nagi')")
        connection.execute(
            "INSERT INTO channels(id, streamer_id, handle, name, youtube_channel_id) "
            "VALUES (1, 1, '@nagi', 'Nagi', 'UC_TEST')"
        )
        connection.execute(
            "INSERT INTO videos(id, channel_id, youtube_video_id, title, description, "
            "published_at, is_embeddable) "
            "VALUES (2, 1, 'abcdefghijk', 'Test', '', '2026-07-01T00:00:00+00:00', 1)"
        )
        connection.execute(
            "INSERT INTO youtube_transcripts(id, video_id, language, language_code, "
            "is_generated, requested_languages, preserve_formatting, storage_bucket, "
            "storage_object_name, storage_uri, response_sha256, segment_count, text_length) "
            "VALUES (3, 'abcdefghijk', 'Korean', 'ko', 1, '[\"ko\"]', 0, "
            "'transcripts', 'video.json', 's3://transcripts/video.json', "
            "'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', 1, 4)"
        )
        jobs = [
            (
                10,
                "transcript_collect",
                "succeeded",
                "video",
                2,
                {"videoTaskId": 5, "timeoutSeconds": 600},
                "job-10",
                None,
            ),
            (
                11,
                "video_collect",
                "succeeded",
                "channel",
                1,
                {"channelId": 1},
                "job-11",
                10,
            ),
            (
                12,
                "transcript_collect_batch",
                "succeeded",
                "channel",
                1,
                {"channelId": 1, "limit": 5},
                "job-12",
                None,
            ),
        ]
        connection.executemany(
            "INSERT INTO pipeline_jobs(id, step, status, subject_type, subject_id, "
            "input_json, input_hash, parent_job_id, completed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
            [(*row[:5], json.dumps(row[5]), row[6], row[7]) for row in jobs],
        )
        attempts = [
            (100, 10, 1, "failed", "worker:1", "UpstreamError", "failed", None),
            (101, 10, 2, "succeeded", "worker:1", None, None, {"transcriptId": 3}),
            (102, 11, 1, "succeeded", None, None, None, {"createdCount": 1}),
        ]
        connection.executemany(
            "INSERT INTO pipeline_job_attempts(id, job_id, attempt_no, status, worker_id, "
            "error_type, error_message, output_json, finished_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
            [(*row[:7], json.dumps(row[7]) if row[7] is not None else None) for row in attempts],
        )
        connection.execute(
            "INSERT INTO video_tasks(id, video_id, task_name, task_version, input_hash, "
            "status, timeout_seconds, input_json, job_id, job_attempt_id, "
            "output_transcript_id, output_json, completed_at) "
            "VALUES (5, 2, 'transcript_collect', 'v1', 'task-5', 'no_transcript', 600, "
            "?, 10, 101, 3, ?, CURRENT_TIMESTAMP)",
            (
                json.dumps({"videoId": 2, "youtubeVideoId": "abcdefghijk"}),
                json.dumps({"transcriptId": 3}),
            ),
        )
        connection.commit()
    finally:
        connection.close()


def _alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", "alembic")
    return config
