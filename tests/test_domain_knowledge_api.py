from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from codex_sdk_cli.api.dependencies import _get_database_engine, get_settings
from tests.support.legacy_api import create_legacy_app as create_app


def test_domain_knowledge_api_creates_entry_with_new_type(
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
        "created_name": "테스트 인물",
        "created_type_label": "사람 이름",
        "created_streamer_count": 1,
        "created_alias_kind": "ASR_ERROR",
        "type_reused": True,
        "listed_count": 1,
        "archived_active": False,
    }


async def _exercise_api() -> dict[str, object]:
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        streamer_response = await client.post("/streamers", json={"name": "Streamer"})
        streamer_response.raise_for_status()
        streamer_id = streamer_response.json()["id"]
        created_response = await client.post(
            "/domain-entries",
            json={
                "typeLabel": "사람 이름",
                "canonicalName": "테스트 인물",
                "detail": "테스트 인물에 대한 설명",
                "streamerIds": [streamer_id],
                "aliases": [
                    {
                        "surfaceForm": "테인",
                        "aliasKind": "ASR_ERROR",
                        "certainty": "HIGH",
                        "applyScope": "SEARCH_AND_SUMMARY",
                    }
                ],
            },
        )
        created_response.raise_for_status()
        created = created_response.json()
        type_response = await client.post(
            "/domain-entry-types",
            json={"label": "사람 이름"},
        )
        list_response = await client.get(
            "/domain-entries",
            params={"streamerId": streamer_id},
        )
        list_response.raise_for_status()
        archived_response = await client.delete(f"/domain-entries/{created['entryId']}")
        archived_response.raise_for_status()
        archived = archived_response.json()
        return {
            "created_name": created["canonicalName"],
            "created_type_label": created["typeLabel"],
            "created_streamer_count": len(created["streamers"]),
            "created_alias_kind": created["aliases"][0]["aliasKind"],
            "type_reused": type_response.status_code == 409,
            "listed_count": len(list_response.json()["items"]),
            "archived_active": archived["isActive"],
        }
