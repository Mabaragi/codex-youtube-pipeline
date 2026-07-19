from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from codex_sdk_cli.api.dependencies import _get_database_engine, get_settings
from codex_sdk_cli.api.main import create_app
from codex_sdk_cli.infra.database.session import create_database_engine, create_session_factory


def test_ops_work_commands_and_queries(
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{migrated_database_path.as_posix()}"
    monkeypatch.setenv("CODEX_CLI_DATABASE_URL", database_url)
    get_settings.cache_clear()
    _get_database_engine.cache_clear()
    try:
        asyncio.run(_exercise_work_api(database_url))
    finally:
        get_settings.cache_clear()
        _get_database_engine.cache_clear()


def test_new_work_paths_are_exported() -> None:
    schema = create_app().openapi()

    assert "/ops/operations/transcript-collect" in schema["paths"]
    assert "/ops/operations/channel-resolve" in schema["paths"]
    assert "/ops/operations/video-collect" in schema["paths"]
    assert "/ops/operations/archive-publish" in schema["paths"]
    assert "/ops/operations/embed-status-refresh" in schema["paths"]
    assert "/ops/operations/transcript-cue-generate" in schema["paths"]
    assert "/ops/operations/micro-event-extract" in schema["paths"]
    assert "/ops/operations/timeline-compose" in schema["paths"]
    assert "/ops/workflows/process-to-publish" in schema["paths"]
    assert "/ops/work-items" in schema["paths"]
    assert "/ops/work-items/{work_item_id}" in schema["paths"]
    assert "/ops/work-batches/{batch_id}" in schema["paths"]
    assert "/ops/workflows/{workflow_run_id}" in schema["paths"]
    assert not any(path.startswith("/video-tasks/") for path in schema["paths"])
    assert not any(path.startswith("/pipeline/jobs") for path in schema["paths"])
    assert "/youtube-transcripts" not in schema["paths"]
    assert "/ops/transcripts" in schema["paths"]


async def _exercise_work_api(database_url: str) -> None:
    await _insert_video(database_url)
    await _insert_legacy_micro_event_items(database_url)
    async with AsyncClient(
        transport=ASGITransport(app=create_app()),
        base_url="http://testserver",
    ) as client:
        created = await client.post(
            "/ops/operations/transcript-collect",
            json={
                "selection": {"type": "selected", "videoIds": [1]},
                "languages": ["ko", "en", "ko"],
            },
        )
        assert created.status_code == 202
        body = created.json()
        assert body["createdCount"] == 1
        assert body["items"][0]["status"] == "pending"
        work_item_id = body["items"][0]["workItemId"]

        listed = await client.get(
            "/ops/work-items",
            params={"taskType": "transcript_collect", "limit": 1},
        )
        assert listed.status_code == 200
        assert listed.json()["items"][0]["id"] == work_item_id

        detail = await client.get(f"/ops/work-items/{work_item_id}")
        assert detail.status_code == 200
        assert detail.json()["attempts"] == []
        assert detail.json()["input"]["languages"] == ["ko", "en"]

        conflict = await client.post(
            f"/ops/work-items/{work_item_id}/retry",
            json={},
        )
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "work_item.transition_not_allowed"

        canceled = await client.post(
            f"/ops/work-items/{work_item_id}/cancel",
            json={"reason": "test cancellation"},
        )
        assert canceled.status_code == 200
        assert canceled.json()["status"] == "canceled"

        workflow_created = await client.post(
            "/ops/workflows/process-to-publish",
            json={
                "selection": {"type": "selected", "videoIds": [1]},
                "transcriptFallback": {
                    "graceSeconds": 21600,
                    "recheckIntervalSeconds": 900,
                },
            },
        )
        assert workflow_created.status_code == 202
        workflow_body = workflow_created.json()
        workflow_id = workflow_body["items"][0]["workflowRunId"]
        batch_id = workflow_body["batchId"]

        workflow_detail = await client.get(f"/ops/workflows/{workflow_id}")
        assert workflow_detail.status_code == 200
        assert workflow_detail.json()["status"] == "pending"
        assert workflow_detail.json()["steps"] == []
        assert workflow_detail.json()["options"][
            "transcript_recheck_interval_seconds"
        ] == 900

        batch_detail = await client.get(f"/ops/work-batches/{batch_id}")
        assert batch_detail.status_code == 200
        assert batch_detail.json()["items"][0]["workflowRunId"] == workflow_id

        missing = await client.get("/ops/work-items/999999")
        assert missing.status_code == 404
        assert missing.json() == {
            "error": {
                "code": "work_item.not_found",
                "message": "Work item was not found.",
                "details": {"workItemId": 999999},
            }
        }

        invalid = await client.post(
            "/ops/operations/transcript-collect",
            json={"selection": {"type": "selected", "videoIds": []}},
        )
        assert invalid.status_code == 422
        assert invalid.json()["error"]["code"] == "request_validation_failed"

        missing_transcript = await client.get("/ops/transcripts/999999")
        assert missing_transcript.status_code == 404
        assert missing_transcript.json()["error"]["code"] == (
            "youtube_transcript_metadata_not_found"
        )

        superseded = await client.post("/ops/work-items/100/retry", json={})
        assert superseded.status_code == 409
        assert superseded.json() == {
            "error": {
                "code": "work_item.retry_superseded",
                "message": "A newer succeeded work item already replaces this work item.",
                "details": {"workItemId": 100, "replacementWorkItemId": 101},
            }
        }

        incomplete = await client.post("/ops/work-items/102/retry", json={})
        assert incomplete.status_code == 409
        assert incomplete.json()["error"] == {
            "code": "work_item.retry_input_unavailable",
            "message": "The stored work input is incomplete and cannot be retried safely.",
            "details": {
                "workItemId": 102,
                "invalidFields": [
                    "videoId",
                    "transcriptId",
                    "windowMinutes",
                    "overlapMinutes",
                    "model",
                    "reasoningEffort",
                ],
            },
        }
        unchanged = await client.get("/ops/work-items/102")
        assert unchanged.json()["status"] == "failed"

        complete = await client.post("/ops/work-items/103/retry", json={})
        assert complete.status_code == 200
        assert complete.json()["status"] == "pending"

        distinct_input = await client.post("/ops/work-items/105/retry", json={})
        assert distinct_input.status_code == 200
        assert distinct_input.json()["status"] == "pending"

        resumed_workflow = await client.get("/ops/workflows/200")
        assert resumed_workflow.status_code == 200
        assert resumed_workflow.json()["status"] == "pending"
        assert resumed_workflow.json()["currentStage"] is None
        assert resumed_workflow.json()["errorCode"] is None


async def _insert_video(database_url: str) -> None:
    engine = create_database_engine(database_url)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            await session.execute(
                text(
                    "INSERT INTO streamers(id, name, publish_profile_id) "
                    "VALUES (1, 'Nagi', 1)"
                )
            )
            await session.execute(
                text(
                    "INSERT INTO channels(id, streamer_id, handle, name) "
                    "VALUES (1, 1, '@nagi', 'Nagi')"
                )
            )
            await session.execute(
                text(
                    "INSERT INTO videos(id, channel_id, youtube_video_id, title, "
                    "description, published_at, is_embeddable) VALUES "
                    "(1, 1, 'abcdefghijk', 'Test', '', "
                    "'2026-07-01T00:00:00+00:00', 1), "
                    "(2, 1, 'lmnopqrstuv', 'Test 2', '', "
                    "'2026-07-02T00:00:00+00:00', 1), "
                    "(3, 1, 'wxyzabcdefg', 'Test 3', '', "
                    "'2026-07-03T00:00:00+00:00', 1)"
                )
            )
            await session.commit()
    finally:
        await engine.dispose()


async def _insert_legacy_micro_event_items(database_url: str) -> None:
    engine = create_database_engine(database_url)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            await session.execute(
                text(
                    "INSERT INTO work_items("
                    "id, task_type, subject_type, subject_id, external_key, task_version, "
                    "input_hash, idempotency_key, execution_mode, status, priority, "
                    "timeout_seconds, input_json) VALUES "
                    "(100, 'micro_event_extract', 'video', 1, 'abcdefghijk', 'v1', "
                    "'legacy-failed', 'legacy:video_task:100', 'worker', 'failed', 0, 3600, '{}'), "
                    "(101, 'micro_event_extract', 'video', 1, 'abcdefghijk', 'v2', "
                    "'replacement-success', 'legacy:video_task:101', 'worker', "
                    "'succeeded', 0, 3600, '{}'), "
                    "(102, 'micro_event_extract', 'video', 2, 'lmnopqrstuv', 'v1', "
                    "'legacy-incomplete', 'legacy:video_task:102', 'worker', "
                    "'failed', 0, 3600, '{}')"
                )
            )
            await session.execute(
                text(
                    "INSERT INTO work_items("
                    "id, task_type, subject_type, subject_id, external_key, task_version, "
                    "input_hash, idempotency_key, execution_mode, status, priority, "
                    "timeout_seconds, input_json) VALUES "
                    "(103, 'micro_event_extract', 'video', 2, 'lmnopqrstuv', 'v2', "
                    "'complete-retry', 'micro:complete-retry', 'worker', "
                    "'failed', 0, 3600, :input_json)"
                ),
                {
                    "input_json": json.dumps(
                        {
                            "videoId": 2,
                            "transcriptId": 2,
                            "windowMinutes": 30,
                            "overlapMinutes": 5,
                            "model": "gpt-5.6-sol",
                            "reasoningEffort": "high",
                        }
                    )
                },
            )
            await session.execute(
                text(
                    "INSERT INTO work_items("
                    "id, task_type, subject_type, subject_id, external_key, task_version, "
                    "input_hash, idempotency_key, execution_mode, status, priority, "
                    "timeout_seconds, input_json) VALUES "
                    "(105, 'micro_event_extract', 'video', 3, 'wxyzabcdefg', 'v2', "
                    "'retry-this-input', 'micro:retry-this-input', 'worker', "
                    "'failed', 0, 3600, :failed_input), "
                    "(106, 'micro_event_extract', 'video', 3, 'wxyzabcdefg', 'v2', "
                    "'different-success', 'micro:different-success', 'worker', "
                    "'succeeded', 0, 3600, :success_input)"
                ),
                {
                    "failed_input": json.dumps(
                        {
                            "videoId": 3,
                            "transcriptId": 3,
                            "windowMinutes": 30,
                            "overlapMinutes": 5,
                            "model": "gpt-5.6-sol",
                            "reasoningEffort": "high",
                        }
                    ),
                    "success_input": json.dumps(
                        {
                            "videoId": 3,
                            "transcriptId": 3,
                            "windowMinutes": 20,
                            "overlapMinutes": 2,
                            "model": "gpt-5.6-sol",
                            "reasoningEffort": "medium",
                        }
                    ),
                },
            )
            await session.execute(
                text(
                    "INSERT INTO workflow_runs("
                    "id, workflow_type, workflow_version, video_id, input_hash, status, "
                    "current_stage, options_json, error_code, error_message) VALUES "
                    "(200, 'process_to_publish', 'v2', 2, 'linked-complete-retry', "
                    "'failed', NULL, '{}', 'work.execution_failed', 'micro failed')"
                )
            )
            await session.execute(
                text(
                    "INSERT INTO workflow_steps("
                    "id, workflow_run_id, stage_name, position, work_item_id, status) VALUES "
                    "(200, 200, 'micro_event_extract', 4, 103, 'failed')"
                )
            )
            await session.commit()
    finally:
        await engine.dispose()
