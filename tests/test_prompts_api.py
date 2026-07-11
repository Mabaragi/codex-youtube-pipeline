from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from codex_sdk_cli.api.dependencies import _get_database_engine, get_settings
from tests.support.legacy_api import create_legacy_app as create_app


def test_prompts_api_manages_publish_rollback_archive_and_cache(
    monkeypatch: pytest.MonkeyPatch,
    migrated_database_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{migrated_database_path.as_posix()}"
    monkeypatch.setenv("CODEX_CLI_DATABASE_URL", database_url)
    get_settings.cache_clear()
    _get_database_engine.cache_clear()

    try:
        result = asyncio.run(_exercise_api())
    finally:
        get_settings.cache_clear()
        _get_database_engine.cache_clear()

    assert result == {
        "fallback_source": "fallback",
        "known_keys": [
            "micro_event_extract",
            "timeline_compose",
            "timeline_episode_repair",
        ],
        "created_status": "DRAFT",
        "duplicate_status": 409,
        "updated_sha_len": 64,
        "published_active_label": "ops-v1",
        "active_after_second_publish": "ops-v2",
        "active_after_rollback": "ops-v1",
        "archive_active_status": 409,
        "archive_inactive_status": "ARCHIVED",
        "archive_draft_status": "ARCHIVED",
        "invalidated_count": 1,
    }


async def _exercise_api() -> dict[str, object]:
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        list_response = await client.get("/prompts")
        list_response.raise_for_status()
        listed = list_response.json()
        fallback_source = next(
            item["active"]["source"] for item in listed if item["key"] == "micro_event_extract"
        )

        created_response = await client.post(
            "/prompts/micro_event_extract/versions",
            json={
                "versionLabel": "ops-v1",
                "body": "prompt body one",
                "sourceNote": "first API draft",
            },
        )
        created_response.raise_for_status()
        created = created_response.json()
        duplicate_response = await client.post(
            "/prompts/micro_event_extract/versions",
            json={"versionLabel": "ops-v1", "body": "duplicate body"},
        )
        updated_response = await client.patch(
            f"/prompts/micro_event_extract/versions/{created['id']}",
            json={"body": "prompt body one updated", "sourceNote": None},
        )
        updated_response.raise_for_status()
        updated = updated_response.json()
        publish_response = await client.post(
            f"/prompts/micro_event_extract/versions/{created['id']}/publish"
        )
        publish_response.raise_for_status()
        first_detail_response = await client.get("/prompts/micro_event_extract")
        first_detail_response.raise_for_status()
        published_active_label = first_detail_response.json()["active"]["versionLabel"]

        second_response = await client.post(
            "/prompts/micro_event_extract/versions",
            json={"versionLabel": "ops-v2", "body": "prompt body two"},
        )
        second_response.raise_for_status()
        second = second_response.json()
        second_publish_response = await client.post(
            f"/prompts/micro_event_extract/versions/{second['id']}/publish"
        )
        second_publish_response.raise_for_status()
        second_detail_response = await client.get("/prompts/micro_event_extract")
        second_detail_response.raise_for_status()
        active_after_second_publish = second_detail_response.json()["active"]["versionLabel"]

        rollback_response = await client.post(
            f"/prompts/micro_event_extract/versions/{created['id']}/publish"
        )
        rollback_response.raise_for_status()
        rollback_detail_response = await client.get("/prompts/micro_event_extract")
        rollback_detail_response.raise_for_status()
        active_after_rollback = rollback_detail_response.json()["active"]["versionLabel"]

        archive_active_response = await client.post(
            f"/prompts/micro_event_extract/versions/{created['id']}/archive"
        )
        archive_inactive_response = await client.post(
            f"/prompts/micro_event_extract/versions/{second['id']}/archive"
        )
        archive_inactive_response.raise_for_status()
        draft_response = await client.post(
            "/prompts/micro_event_extract/versions",
            json={"versionLabel": "ops-v3", "body": "prompt body three"},
        )
        draft_response.raise_for_status()
        archive_draft_response = await client.post(
            f"/prompts/micro_event_extract/versions/{draft_response.json()['id']}/archive"
        )
        archive_draft_response.raise_for_status()

        refill_cache_response = await client.get("/prompts/micro_event_extract")
        refill_cache_response.raise_for_status()
        invalidate_response = await client.post(
            "/prompts/cache/invalidate",
            json={"promptKey": "micro_event_extract"},
        )
        invalidate_response.raise_for_status()

        return {
            "fallback_source": fallback_source,
            "known_keys": [item["key"] for item in listed],
            "created_status": created["status"],
            "duplicate_status": duplicate_response.status_code,
            "updated_sha_len": len(updated["bodySha256"]),
            "published_active_label": published_active_label,
            "active_after_second_publish": active_after_second_publish,
            "active_after_rollback": active_after_rollback,
            "archive_active_status": archive_active_response.status_code,
            "archive_inactive_status": archive_inactive_response.json()["status"],
            "archive_draft_status": archive_draft_response.json()["status"],
            "invalidated_count": invalidate_response.json()["invalidatedCount"],
        }
