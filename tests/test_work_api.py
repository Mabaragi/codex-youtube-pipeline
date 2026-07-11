from __future__ import annotations

import asyncio
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
            json={"selection": {"type": "selected", "videoIds": [1]}},
        )
        assert workflow_created.status_code == 202
        workflow_body = workflow_created.json()
        workflow_id = workflow_body["items"][0]["workflowRunId"]
        batch_id = workflow_body["batchId"]

        workflow_detail = await client.get(f"/ops/workflows/{workflow_id}")
        assert workflow_detail.status_code == 200
        assert workflow_detail.json()["status"] == "pending"
        assert workflow_detail.json()["steps"] == []

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


async def _insert_video(database_url: str) -> None:
    engine = create_database_engine(database_url)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            await session.execute(text("INSERT INTO streamers(id, name) VALUES (1, 'Nagi')"))
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
                    "'2026-07-01T00:00:00+00:00', 1)"
                )
            )
            await session.commit()
    finally:
        await engine.dispose()
