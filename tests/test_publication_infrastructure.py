from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

import httpx
import pytest
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, inspect, select
from sqlalchemy.ext.asyncio import AsyncEngine

from alembic import command
from codex_sdk_cli.api.main import create_app
from codex_sdk_cli.api.use_case_dependencies.publication import (
    get_publication_connection_registry,
)
from codex_sdk_cli.domains.archive_publish.ports import (
    ArchivePublicCatalogTimelineIndex,
    ArchivePublicCatalogTimelineIndexBlock,
    ArchivePublicCatalogTimelineIndexEpisode,
    ArchivePublicCatalogTimelineIndexMicroEvent,
    ArchivePublicCatalogTimelineIndexTopicCluster,
    ArchivePublicCatalogVideoRow,
)
from codex_sdk_cli.domains.publication.exceptions import PublicationCatalogPublishError
from codex_sdk_cli.domains.publication.ports import (
    PublicationCatalogContext,
    PublicationCatalogVideoKey,
)
from codex_sdk_cli.infra.publication.catalog_database.models import (
    PublishedTimelineBlockModel,
    PublishedVideoModel,
)
from codex_sdk_cli.infra.publication.catalog_database.session import (
    create_catalog_engine,
    create_catalog_session_factory,
    ensure_catalog_database,
)
from codex_sdk_cli.infra.publication.catalog_publishers import (
    HttpPublicationCatalogPublisher,
    SqlPublicationCatalogPublisher,
)
from codex_sdk_cli.infra.publication.connections import (
    PublicationConnectionRegistry,
    load_publication_connection_registry,
)
from codex_sdk_cli.infra.publication.object_store import (
    ObjectReadResponseLike,
    ObjectStatLike,
    ObjectWriteResultLike,
    S3CompatibleClient,
    S3CompatiblePublicationObjectStore,
)
from codex_sdk_cli.settings import CliSettings

NOW = datetime(2026, 7, 18, 1, 30, tzinfo=UTC)


def test_settings_expose_publication_registry_and_local_store_refs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "CODEX_CLI_PUBLISH_CONNECTIONS_FILE",
        "private/publish-connections.json",
    )

    settings = CliSettings()

    assert settings.publish_connections_file == Path("private/publish-connections.json")
    assert settings.publication_artifact_store_ref == "local-artifact-store"
    assert settings.publication_staging_store_ref == "local-publication-staging"


def test_connection_registry_safe_summaries_never_expose_secrets(tmp_path: Path) -> None:
    registry_path = tmp_path / "connections.json"
    registry_path.write_text(json.dumps(_registry_payload()), encoding="utf-8")

    registry = load_publication_connection_registry(registry_path)
    serialized = json.dumps(
        [summary.model_dump(by_alias=True) for summary in registry.safe_summaries()]
    )

    assert "ACCESS_SECRET" not in serialized
    assert "ENDPOINT_SECRET" not in serialized
    assert "HTTP_SECRET" not in serialized
    assert "TOKEN_SECRET" not in serialized
    assert "URL_SECRET" not in serialized
    assert "PASSWORD_SECRET" not in serialized
    assert "operator" not in serialized
    summaries = {item.connection_ref: item for item in registry.safe_summaries()}
    assert summaries["local-artifact-store"].target == "http://127.0.0.1:9000"
    assert summaries["local-artifact-store"].public_base_url == "http://127.0.0.1:9000"
    assert summaries["remote-catalog"].target == "https://catalog.example.test:8443"
    assert summaries["local-public-catalog"].target == (
        "postgresql+asyncpg://127.0.0.1:5432/codex_public_catalog"
    )


def test_safe_connection_api_returns_only_masked_summaries() -> None:
    registry = PublicationConnectionRegistry.model_validate(_registry_payload())
    response = asyncio.run(_connection_api_request(registry))

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 3
    assert payload["items"][0]["connectionRef"] == "local-artifact-store"
    serialized = response.text
    assert "ACCESS_SECRET" not in serialized
    assert "ENDPOINT_SECRET" not in serialized
    assert "HTTP_SECRET" not in serialized
    assert "TOKEN_SECRET" not in serialized
    assert "URL_SECRET" not in serialized
    assert "PASSWORD_SECRET" not in serialized


def test_s3_compatible_object_store_put_get_stat_with_fake_client() -> None:
    client = FakeS3Client()
    store = S3CompatiblePublicationObjectStore(
        client=client,
        bucket="archive-public",
        public_base_url="http://127.0.0.1:9000/archive-public",
    )

    location = asyncio.run(
        store.put_bytes(
            object_key="archive/video.json",
            payload=b'{"ok":true}',
            content_type="application/json",
            cache_control="public, max-age=60",
        )
    )
    payload = asyncio.run(store.get_bytes(object_key="archive/video.json"))
    stat = asyncio.run(store.stat_object(object_key="archive/video.json"))

    assert location.public_url == ("http://127.0.0.1:9000/archive-public/archive/video.json")
    assert location.etag == "fake-etag"
    assert payload == b'{"ok":true}'
    assert stat is not None
    assert stat.byte_size == 11
    assert client.metadata == {"Cache-Control": "public, max-age=60"}


def test_http_catalog_publisher_keeps_existing_payload_contract() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(204)

    publisher = HttpPublicationCatalogPublisher(
        url="https://catalog.example.test/api/admin/archive/videos/upsert",
        token="TOKEN_SECRET",
        timeout_seconds=3,
        transport=httpx.MockTransport(handler),
    )

    asyncio.run(
        publisher.upsert_video(
            PublicationCatalogContext(profile_key="legacy-current", publish_mode="prod"),
            _catalog_row(),
        )
    )

    assert len(requests) == 1
    assert requests[0].headers["authorization"] == "Bearer TOKEN_SECRET"
    payload = json.loads(requests[0].content)
    assert payload["videos"][0]["videoId"] == 71
    assert payload["timelineIndex"]["blocks"][0]["blockId"] == "block-1"
    assert "profileKey" not in payload
    assert "publishMode" not in payload


def test_catalog_migration_and_sql_upsert_are_atomic_and_idempotent(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "public-catalog.db"
    database_url = f"sqlite+aiosqlite:///{database_path.as_posix()}"
    config = Config()
    config.set_main_option("script_location", "catalog_alembic")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")

    result = asyncio.run(_exercise_sql_catalog(database_url))

    assert result == (1, 1, "Original title", True, False)
    engine = create_catalog_engine(database_url)
    try:
        table_names = asyncio.run(_table_names(engine))
    finally:
        asyncio.run(engine.dispose())
    assert table_names == {
        "alembic_version",
        "published_videos",
        "published_timeline_blocks",
        "published_timeline_episodes",
        "published_timeline_micro_events",
        "published_timeline_topic_clusters",
    }


def test_catalog_database_provisioning_is_noop_for_sqlite(tmp_path: Path) -> None:
    database_url = f"sqlite+aiosqlite:///{(tmp_path / 'catalog.db').as_posix()}"

    created = asyncio.run(ensure_catalog_database(database_url))

    assert created is False


async def _connection_api_request(
    registry: PublicationConnectionRegistry,
) -> httpx.Response:
    app = create_app()
    app.dependency_overrides[get_publication_connection_registry] = lambda: registry
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        return await client.get("/ops/publish/connections")


async def _exercise_sql_catalog(database_url: str) -> tuple[int, int, str, bool, bool]:
    engine = create_catalog_engine(database_url)
    session_factory = create_catalog_session_factory(engine)
    publisher = SqlPublicationCatalogPublisher(session_factory=session_factory)
    context = PublicationCatalogContext(profile_key="legacy-current", publish_mode="prod")
    original = _catalog_row()
    try:
        await publisher.upsert_video(context, original)
        await publisher.upsert_video(context, original)
        await publisher.upsert_video(context, _catalog_row(video_id=72))
        await publisher.reconcile_videos(
            context,
            environment="prod",
            retained=(
                PublicationCatalogVideoKey(
                    video_id=original.video_id,
                    variant=original.variant,
                ),
            ),
        )
        matching = await publisher.verify_video(context, original)
        mismatching = await publisher.verify_video(context, _catalog_row(title="Changed title"))
        broken = _catalog_row(title="Must roll back", duplicate_block=True)
        with pytest.raises(PublicationCatalogPublishError):
            await publisher.upsert_video(context, broken)
        async with session_factory() as session:
            video_count = await session.scalar(
                select(func.count()).select_from(PublishedVideoModel)
            )
            block_count = await session.scalar(
                select(func.count()).select_from(PublishedTimelineBlockModel)
            )
            title = await session.scalar(select(PublishedVideoModel.title))
        return (
            video_count or 0,
            block_count or 0,
            title or "",
            matching.matches,
            mismatching.matches,
        )
    finally:
        await engine.dispose()


async def _table_names(engine: AsyncEngine) -> set[str]:
    async with engine.connect() as connection:
        return set(
            await connection.run_sync(
                lambda sync_connection: inspect(sync_connection).get_table_names()
            )
        )


def _catalog_row(
    *,
    title: str = "Original title",
    duplicate_block: bool = False,
    video_id: int = 71,
) -> ArchivePublicCatalogVideoRow:
    block = ArchivePublicCatalogTimelineIndexBlock(
        block_id="block-1",
        block_index=1,
        block_type="JUST_CHATTING",
        title="Block",
        display_title="Block",
        start_ms=0,
        end_ms=60_000,
        episode_count=1,
    )
    blocks = [block, block] if duplicate_block else [block]
    index = ArchivePublicCatalogTimelineIndex(
        environment="prod",
        video_id=video_id,
        variant="control",
        timeline_version="20260718T013000Z",
        updated_at=NOW.isoformat(),
        blocks=blocks,
        episodes=[
            ArchivePublicCatalogTimelineIndexEpisode(
                episode_id="episode-1",
                block_id="block-1",
                episode_index=1,
                start_ms=0,
                end_ms=60_000,
                title="Episode",
                display_title="Episode",
                program_mode="JUST_CHATTING",
                content_kind="STORY",
                visibility="DEFAULT",
                topics=["topic"],
                viewer_tags=["story"],
                micro_event_count=1,
            )
        ],
        micro_events=[
            ArchivePublicCatalogTimelineIndexMicroEvent(
                micro_event_id="event-1",
                episode_id="episode-1",
                event_index=1,
                start_ms=0,
                end_ms=30_000,
                text="Event",
                program_mode="JUST_CHATTING",
                content_kind="STORY",
            )
        ],
        topic_clusters=[
            ArchivePublicCatalogTimelineIndexTopicCluster(
                topic_id="topic-1",
                label="Topic",
                display_label="Topic",
                episode_ids=["episode-1"],
            )
        ],
    )
    return ArchivePublicCatalogVideoRow(
        environment="prod",
        video_id=video_id,
        youtube_video_id=f"youtube-{video_id}",
        title=title,
        streamer_id="3",
        streamer_name="Streamer",
        channel_id=7,
        channel_name="Channel",
        channel_handle="@channel",
        youtube_channel_id="UC_CHANNEL",
        published_at=NOW.isoformat(),
        duration_text="PT1M",
        duration_seconds=60.0,
        thumbnail_url="https://img.example.test/71.jpg",
        is_embeddable=True,
        display_title=title,
        display_summary="Summary",
        main_topics=["topic"],
        episode_count=1,
        micro_event_count=1,
        topic_cluster_count=1,
        block_count=1,
        variant="control",
        timeline_version="20260718T013000Z",
        timeline_url="https://cdn.example.test/archive/71.json",
        artifact_sha256="a" * 64,
        artifact_byte_size=1234,
        updated_at=NOW.isoformat(),
        timeline_index=index,
    )


def _registry_payload() -> dict[str, object]:
    return {
        "version": 1,
        "connections": {
            "local-artifact-store": {
                "kind": "s3_compatible_object",
                "endpoint": "http://operator:ENDPOINT_SECRET@127.0.0.1:9000?secret=x",
                "accessKey": "ACCESS_SECRET",
                "secretKey": "SECRET_SECRET",
                "bucket": "archive-artifacts",
                "secure": False,
                "publicBaseUrl": "http://127.0.0.1:9000/archive-artifacts",
            },
            "local-public-catalog": {
                "kind": "sql_catalog",
                "databaseUrl": (
                    "postgresql+asyncpg://operator:PASSWORD_SECRET@127.0.0.1:5432/"
                    "codex_public_catalog"
                ),
            },
            "remote-catalog": {
                "kind": "http_catalog",
                "url": (
                    "https://operator:HTTP_SECRET@catalog.example.test:8443/"
                    "upsert/private?secret=URL_SECRET#internal"
                ),
                "token": "TOKEN_SECRET",
            },
        },
    }


class FakeWriteResult(ObjectWriteResultLike):
    etag = "fake-etag"


class FakeStat(ObjectStatLike):
    def __init__(self, size: int) -> None:
        self.size = size
        self.etag = "fake-etag"
        self.last_modified = NOW


class FakeReadResponse(ObjectReadResponseLike):
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self, amt: int | None = None) -> bytes:
        return self._payload if amt is None else self._payload[:amt]

    def close(self) -> None:
        pass

    def release_conn(self) -> None:
        pass


class FakeS3Client(S3CompatibleClient):
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.metadata: dict[str, list[str] | str | tuple[str]] | None = None

    def bucket_exists(self, bucket_name: str) -> bool:
        return bucket_name == "archive-public"

    def put_object(
        self,
        bucket_name: str,
        object_name: str,
        data: BinaryIO,
        length: int,
        content_type: str = "application/octet-stream",
        metadata: dict[str, list[str] | str | tuple[str]] | None = None,
    ) -> ObjectWriteResultLike:
        del bucket_name, content_type
        payload = data.read(length)
        self.objects[object_name] = payload
        self.metadata = metadata
        return FakeWriteResult()

    def get_object(self, bucket_name: str, object_name: str) -> ObjectReadResponseLike:
        del bucket_name
        return FakeReadResponse(self.objects[object_name])

    def stat_object(self, bucket_name: str, object_name: str) -> ObjectStatLike:
        del bucket_name
        return FakeStat(len(self.objects[object_name]))
