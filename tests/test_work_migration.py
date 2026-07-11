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
        assert (
            connection.execute(
                "SELECT work_attempt_id FROM external_api_calls WHERE id = 80"
            ).fetchone()[0]
            == 101
        )
        usage = connection.execute(
            "SELECT work_item_id, work_attempt_id FROM codex_run_usages WHERE id = 70"
        ).fetchone()
        assert tuple(usage) == (5, 101)
        event = connection.execute(
            "SELECT work_item_id, work_attempt_id FROM operation_events WHERE id = 60"
        ).fetchone()
        assert tuple(event) == (5, 101)
        cue = connection.execute(
            "SELECT source_work_item_id, source_work_attempt_id FROM transcript_cues WHERE id = 50"
        ).fetchone()
        assert tuple(cue) == (5, 101)
        window = connection.execute(
            "SELECT work_item_id, source_work_attempt_id "
            "FROM micro_event_extraction_windows WHERE id = 20"
        ).fetchone()
        assert tuple(window) == (5, 101)
        composition = connection.execute(
            "SELECT work_item_id, source_micro_event_work_item_id, "
            "source_work_attempt_id FROM timeline_compositions WHERE id = 30"
        ).fetchone()
        assert tuple(composition) == (5, 5, 101)
        artifact = connection.execute(
            "SELECT source_timeline_work_item_id, source_micro_event_work_item_id, "
            "publish_work_item_id, publish_work_attempt_id "
            "FROM archive_video_artifacts WHERE id = 40"
        ).fetchone()
        assert tuple(artifact) == (5, 5, 5, 101)
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
        _insert_provenance_fixture(connection)
        connection.commit()
    finally:
        connection.close()


def _insert_provenance_fixture(connection: sqlite3.Connection) -> None:
    connection.execute(
        "INSERT INTO external_api_calls(id, provider, operation, request_method, "
        "request_url, request_params, response_headers, validation_status, duration_ms, "
        "pipeline_job_attempt_id) VALUES "
        "(80, 'youtube', 'test', 'GET', 'https://example.test', '{}', '{}', "
        "'valid', 1, 101)"
    )
    connection.execute(
        "INSERT INTO codex_run_usages(id, source, operation, status, duration_ms, "
        "video_id, video_task_id, job_id, job_attempt_id) VALUES "
        "(70, 'test', 'extract', 'succeeded', 1, 2, 5, 10, 101)"
    )
    connection.execute(
        "INSERT INTO operation_events(id, event_type, severity, message, actor_type, "
        "source, metadata_json, job_id, job_attempt_id, video_task_id, video_id) VALUES "
        "(60, 'test.succeeded', 'info', 'done', 'system', 'test', '{}', 10, 101, 5, 2)"
    )
    connection.execute(
        "INSERT INTO transcript_cues(id, transcript_id, cue_id, cue_index, text, start_ms, "
        "end_ms, duration_ms, source_segment_index, source_job_id, source_job_attempt_id) "
        "VALUES (50, 3, 'tr3-c000001', 1, 'test', 0, 1000, 1000, 0, 10, 101)"
    )
    connection.execute(
        "INSERT INTO micro_event_extraction_windows(id, video_task_id, video_id, "
        "transcript_id, window_index, start_cue_id, end_cue_id, cue_count, status, "
        "carry_out_unfinished, source_job_id, source_job_attempt_id) VALUES "
        "(20, 5, 2, 3, 1, 'tr3-c000001', 'tr3-c000001', 1, 'succeeded', 0, 10, 101)"
    )
    connection.execute(
        "INSERT INTO micro_event_candidates(id, window_id, video_task_id, transcript_id, "
        "candidate_index, activity, event, start_cue_id, end_cue_id, evidence_cue_ids, "
        "boundary_before, boundary_after, confidence, program_mode, content_kind) VALUES "
        "(21, 20, 5, 3, 1, 'JUST_CHATTING', 'test event', 'tr3-c000001', "
        "'tr3-c000001', '[\"tr3-c000001\"]', 1, 1, 0.9, 'JUST_CHATTING', 'META_CHAT')"
    )
    connection.execute(
        "INSERT INTO micro_event_excluded_ranges(id, window_id, video_task_id, "
        "transcript_id, range_index, start_cue_id, end_cue_id, reason) VALUES "
        "(22, 20, 5, 3, 1, 'tr3-c000001', 'tr3-c000001', 'LOW_INFORMATION')"
    )
    connection.execute(
        "INSERT INTO asr_correction_candidates(id, window_id, video_task_id, "
        "transcript_id, candidate_index, original, suggested, correction_type, "
        "apply_scope, evidence_cue_ids, confidence) VALUES "
        "(23, 20, 5, 3, 1, 'nagi', '나기', 'PROPER_NOUN', 'LOCAL', '[]', 0.9)"
    )
    connection.execute(
        "INSERT INTO timeline_compositions(id, video_task_id, video_id, "
        "source_micro_event_task_id, source_micro_event_fingerprint, copy_style, "
        "title, summary, display_title, display_summary, main_topics, output_json, "
        "validation_warnings, source_job_id, source_job_attempt_id) VALUES "
        "(30, 5, 2, 5, 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', "
        "'LIGHT_FANDOM_V1', 'title', 'summary', 'display', 'display summary', '[]', "
        "'{}', '[]', 10, 101)"
    )
    connection.execute(
        "INSERT INTO archive_video_artifacts(id, video_id, source_timeline_composition_id, "
        "source_timeline_task_id, source_micro_event_task_id, publish_task_id, "
        "publish_job_id, environment, variant, schema_version, version, object_key, "
        "public_url, sha256, byte_size, block_count, episode_count, topic_cluster_count, "
        "review_flag_count, micro_event_count) VALUES "
        "(40, 2, 30, 5, 5, 5, 10, 'prod', 'control', 1, 'v1', 'timeline.json', "
        "'https://example.test/timeline.json', "
        "'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc', "
        "1, 0, 0, 0, 0, 1)"
    )


def _alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", "alembic")
    return config
