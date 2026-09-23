from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from httpx import ASGITransport, AsyncClient, Response

from codex_sdk_cli.api.main import create_app
from codex_sdk_cli.api.use_case_dependencies.public_archive import (
    get_public_archive_repository,
)
from codex_sdk_cli.application.public_archive.queries import (
    PublicArchiveRepositoryPort,
    PublicArchiveScope,
    PublicArchiveStreamer,
    PublicArchiveTimelineVariant,
    PublicArchiveTopicMatch,
    PublicArchiveVideo,
    PublicArchiveVideoPage,
    PublicArchiveVideoQuery,
)


class FakePublicArchiveRepository(PublicArchiveRepositoryPort):
    def __init__(self) -> None:
        self.query: PublicArchiveVideoQuery | None = None
        self.identifier: str | None = None
        self.video = _video()

    async def list_videos(
        self,
        query: PublicArchiveVideoQuery,
    ) -> PublicArchiveVideoPage:
        self.query = query
        return PublicArchiveVideoPage(
            items=(self.video,),
            next_cursor="next-page",
            total_count=1,
        )

    async def get_video(
        self,
        *,
        scope: PublicArchiveScope,
        identifier: str,
    ) -> PublicArchiveVideo | None:
        self.identifier = identifier
        return self.video if identifier in {"101", "abcdefghijk"} else None

    async def list_streamers(
        self,
        scope: PublicArchiveScope,
    ) -> tuple[PublicArchiveStreamer, ...]:
        return (PublicArchiveStreamer(id="5", name="유즈하 리코", video_count=1),)

    async def catalog_version(self, scope: PublicArchiveScope) -> str:
        return "123:1"


def test_list_videos_matches_planetip_archive_contract() -> None:
    repository = FakePublicArchiveRepository()

    response = asyncio.run(
        _request(
            repository,
            "GET",
            "/api/archive/videos",
            params={
                "environment": "prod",
                "sort": "oldest",
                "limit": "12",
                "q": "리코",
                "streamerId": "5",
                "channelId": "9",
                "youtubeVideoId": "abcdefghijk",
                "includeStats": "true",
            },
        )
    )

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "environment": "prod",
                "id": 101,
                "youtubeId": "abcdefghijk",
                "title": "리코 다시보기",
                "streamerId": "5",
                "streamer": {"id": "5", "name": "유즈하 리코"},
                "channel": {
                    "id": 9,
                    "name": "리코 다시보기",
                    "handle": "@rikoreplay",
                    "youtubeChannelId": "UC-local",
                },
                "publishedAt": "2026-07-19T00:00:00+00:00",
                "durationText": "1:00:00",
                "durationSeconds": 3600.0,
                "thumbnailUrl": "https://img.example/video.jpg",
                "isEmbeddable": True,
                "displayTitle": "리코의 방송",
                "displaySummary": "방송 요약",
                "mainTopics": ["게임"],
                "episodeCount": 2,
                "eventCount": 3,
                "topicClusterCount": 1,
                "blockCount": 1,
                "timelineVariants": [
                    {
                        "key": "control",
                        "url": "http://127.0.0.1:9000/archive-public/timeline.json",
                        "version": "v1",
                    }
                ],
                "timelineUrl": "http://127.0.0.1:9000/archive-public/timeline.json",
                "updatedAt": "2026-07-20T00:00:00Z",
                "openCount": 0,
                "timelineLoadCount": 0,
                "episodeClickCount": 0,
                "searchMatches": {"topics": [{"id": "topic-1", "label": "게임"}]},
            }
        ],
        "nextCursor": "next-page",
        "totalCount": 1,
    }
    assert repository.query == PublicArchiveVideoQuery(
        scope=PublicArchiveScope(
            profile_key="stellive-cliche-local",
            publish_mode="prod",
            environment="prod",
        ),
        sort="oldest",
        limit=12,
        query="리코",
        streamer_id="5",
        channel_id=9,
        youtube_video_id="abcdefghijk",
        include_stats=True,
    )


def test_detail_supports_youtube_and_legacy_numeric_ids_and_head() -> None:
    repository = FakePublicArchiveRepository()

    youtube = asyncio.run(_request(repository, "GET", "/api/archive/videos/abcdefghijk"))
    numeric = asyncio.run(_request(repository, "GET", "/api/archive/videos/101"))
    head = asyncio.run(_request(repository, "HEAD", "/api/archive/videos/abcdefghijk"))

    assert youtube.status_code == 200
    assert youtube.json()["item"]["youtubeId"] == "abcdefghijk"
    assert numeric.status_code == 200
    assert head.status_code == 200
    assert head.content == b""
    assert head.headers["cache-control"] == "no-store"


def test_missing_detail_uses_stable_404_error() -> None:
    repository = FakePublicArchiveRepository()

    response = asyncio.run(_request(repository, "GET", "/api/archive/videos/zzzzzzzzzzz"))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "public_archive_video_not_found"


def test_streamers_catalog_version_and_cors_are_frontend_compatible() -> None:
    repository = FakePublicArchiveRepository()

    streamers = asyncio.run(_request(repository, "GET", "/api/archive/streamers"))
    version = asyncio.run(_request(repository, "GET", "/api/archive/catalog-version"))
    preflight = asyncio.run(
        _request(
            repository,
            "OPTIONS",
            "/api/archive/videos",
            headers={
                "origin": "http://127.0.0.1:3001",
                "access-control-request-method": "GET",
            },
        )
    )

    assert streamers.json() == {"items": [{"id": "5", "name": "유즈하 리코", "videoCount": 1}]}
    assert version.json() == {"version": "123:1"}
    assert version.headers["cache-control"] == "no-store"
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "http://127.0.0.1:3001"


async def _request(
    repository: FakePublicArchiveRepository,
    method: str,
    path: str,
    *,
    params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> Response:
    app = create_app()
    app.dependency_overrides[get_public_archive_repository] = lambda: repository
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        return await client.request(method, path, params=params, headers=headers)


def _video() -> PublicArchiveVideo:
    return PublicArchiveVideo(
        environment="prod",
        id=101,
        youtube_id="abcdefghijk",
        title="리코 다시보기",
        streamer_id="5",
        streamer_name="유즈하 리코",
        channel_id=9,
        channel_name="리코 다시보기",
        channel_handle="@rikoreplay",
        youtube_channel_id="UC-local",
        published_at="2026-07-19T00:00:00+00:00",
        duration_text="1:00:00",
        duration_seconds=3600.0,
        thumbnail_url="https://img.example/video.jpg",
        is_embeddable=True,
        display_title="리코의 방송",
        display_summary="방송 요약",
        main_topics=("게임",),
        episode_count=2,
        event_count=3,
        topic_cluster_count=1,
        block_count=1,
        timeline_variants=(
            PublicArchiveTimelineVariant(
                key="control",
                url="http://127.0.0.1:9000/archive-public/timeline.json",
                version="v1",
            ),
        ),
        timeline_url="http://127.0.0.1:9000/archive-public/timeline.json",
        updated_at=datetime(2026, 7, 20, tzinfo=UTC),
        search_matches=(PublicArchiveTopicMatch(id="topic-1", label="게임"),),
    )
