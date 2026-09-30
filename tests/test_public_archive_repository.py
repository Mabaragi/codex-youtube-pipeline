from __future__ import annotations

import asyncio
import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import pytest
from alembic.config import Config

from alembic import command
from codex_sdk_cli.application.public_archive.queries import (
    PublicArchiveScope,
    PublicArchiveVideoQuery,
)
from codex_sdk_cli.infra.publication.catalog_database.models import PublishedVideoModel
from codex_sdk_cli.infra.publication.catalog_database.session import (
    create_catalog_engine,
    create_catalog_session_factory,
)
from codex_sdk_cli.infra.publication.public_archive_repository import (
    SqlAlchemyPublicArchiveRepository,
)


def test_public_archive_repository_scopes_filters_and_paginates(tmp_path: Path) -> None:
    database_url = _migrated_catalog_url(tmp_path)

    result = asyncio.run(_exercise_repository(database_url))

    assert result == {
        "all_ids": [2, 1],
        "first_page_ids": [2],
        "second_page_ids": [1],
        "search_ids": [2],
        "streamers": [("5", "유즈하 리코", 2)],
        "detail_id": 2,
        "hidden_detail": None,
        "version_suffix": ":3",
    }


def test_public_archive_repository_combines_configured_profiles(tmp_path: Path) -> None:
    database_url = _migrated_catalog_url(tmp_path)

    result = asyncio.run(_exercise_combined_profiles(database_url))

    assert result == {
        "all_ids": [2, 1],
        "total_count": 2,
        "filtered_ids": [2],
        "search_ids": [2],
        "streamers": [("5", 1), ("6", 1)],
        "detail_id": 2,
        "excluded_detail": None,
        "version_suffix": ":2",
    }


def _migrated_catalog_url(tmp_path: Path) -> str:
    database_url = f"sqlite+aiosqlite:///{(tmp_path / 'catalog.db').as_posix()}"
    config = Config()
    config.set_main_option("script_location", "catalog_alembic")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    return database_url


@pytest.mark.parametrize("sort", ["latest", "oldest"])
def test_cursor_keeps_same_video_across_profiles_and_variants(
    tmp_path: Path, sort: Literal["latest", "oldest"]
) -> None:
    asyncio.run(_exercise_cursor_ties(_migrated_catalog_url(tmp_path), sort))


async def _exercise_cursor_ties(database_url: str, sort: Literal["latest", "oldest"]) -> None:
    engine = create_catalog_engine(database_url)
    sessions = create_catalog_session_factory(engine)
    scope = PublicArchiveScope("profile-a", "prod", "prod", ("profile-b",))
    try:
        async with sessions() as session:
            for profile in scope.profile_keys:
                for variant in ("control", "experiment"):
                    row = _video(
                        1, "aaaaaaaaaaa", "Test", "2026-07-18T00:00:00+00:00", profile_key=profile
                    )
                    row.variant = variant
                    row.timeline_url = f"https://example.test/{profile}/{variant}.json"
                    session.add(row)
            await session.commit()
        async with sessions() as session:
            repo = SqlAlchemyPublicArchiveRepository(session)
            cursor = None
            urls = []
            for _ in range(4):
                page = await repo.list_videos(
                    PublicArchiveVideoQuery(scope=scope, sort=sort, limit=1, cursor=cursor)
                )
                assert page.total_count == 4 and len(page.items) == 1
                urls.append(page.items[0].timeline_url)
                cursor = page.next_cursor
            assert len(set(urls)) == 4 and cursor is None
            assert urls == sorted(urls, reverse=sort == "latest")
            for payload in ([], False, {"videoId": True}):
                malformed = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
                page = await repo.list_videos(
                    PublicArchiveVideoQuery(scope=scope, cursor=malformed)
                )
                assert len(page.items) == 4
    finally:
        await engine.dispose()


async def _exercise_repository(database_url: str) -> dict[str, object]:
    engine = create_catalog_engine(database_url)
    session_factory = create_catalog_session_factory(engine)
    scope = PublicArchiveScope("stellive-cliche-local", "prod", "prod")
    try:
        async with session_factory() as session:
            session.add_all(
                [
                    _video(1, "aaaaaaaaaaa", "첫 방송", "2026-07-18T00:00:00+00:00"),
                    _video(2, "bbbbbbbbbbb", "리코 게임", "2026-07-19T00:00:00+00:00"),
                    _video(
                        3,
                        "ccccccccccc",
                        "숨김 영상",
                        "2026-07-20T00:00:00+00:00",
                        is_embeddable=False,
                    ),
                    _video(
                        4,
                        "ddddddddddd",
                        "다른 프로필",
                        "2026-07-21T00:00:00+00:00",
                        profile_key="legacy-current",
                    ),
                ]
            )
            await session.commit()

        async with session_factory() as session:
            repository = SqlAlchemyPublicArchiveRepository(session)
            all_page = await repository.list_videos(PublicArchiveVideoQuery(scope=scope))
            first_page = await repository.list_videos(PublicArchiveVideoQuery(scope=scope, limit=1))
            second_page = await repository.list_videos(
                PublicArchiveVideoQuery(
                    scope=scope,
                    limit=1,
                    cursor=first_page.next_cursor,
                )
            )
            search_page = await repository.list_videos(
                PublicArchiveVideoQuery(scope=scope, query="게임")
            )
            streamers = await repository.list_streamers(scope)
            detail = await repository.get_video(scope=scope, identifier="bbbbbbbbbbb")
            hidden = await repository.get_video(scope=scope, identifier="ccccccccccc")
            version = await repository.catalog_version(scope)
        return {
            "all_ids": [item.id for item in all_page.items],
            "first_page_ids": [item.id for item in first_page.items],
            "second_page_ids": [item.id for item in second_page.items],
            "search_ids": [item.id for item in search_page.items],
            "streamers": [(item.id, item.name, item.video_count) for item in streamers],
            "detail_id": detail.id if detail else None,
            "hidden_detail": hidden,
            "version_suffix": version[-2:],
        }
    finally:
        await engine.dispose()


async def _exercise_combined_profiles(database_url: str) -> dict[str, object]:
    engine = create_catalog_engine(database_url)
    session_factory = create_catalog_session_factory(engine)
    scope = PublicArchiveScope(
        "stellive-cliche-local",
        "prod",
        "prod",
        additional_profile_keys=("ddddragon-local",),
    )
    try:
        async with session_factory() as session:
            dragon_video = _video(
                2,
                "bbbbbbbbbbb",
                "디디디용 방송",
                "2026-07-19T00:00:00+00:00",
                profile_key="ddddragon-local",
            )
            dragon_video.streamer_id = "6"
            dragon_video.streamer_name = "디디디용"
            dragon_video.channel_id = 7
            dragon_video.channel_name = "디디디용 다시보기"
            session.add_all(
                [
                    _video(1, "aaaaaaaaaaa", "리코 방송", "2026-07-18T00:00:00+00:00"),
                    dragon_video,
                    _video(
                        3,
                        "ccccccccccc",
                        "다른 프로필",
                        "2026-07-20T00:00:00+00:00",
                        profile_key="unlisted-local",
                    ),
                ]
            )
            await session.commit()

        async with session_factory() as session:
            repository = SqlAlchemyPublicArchiveRepository(session)
            all_page = await repository.list_videos(PublicArchiveVideoQuery(scope=scope))
            filtered_page = await repository.list_videos(
                PublicArchiveVideoQuery(scope=scope, streamer_id="6")
            )
            search_page = await repository.list_videos(
                PublicArchiveVideoQuery(scope=scope, query="디디디용")
            )
            streamers = await repository.list_streamers(scope)
            detail = await repository.get_video(scope=scope, identifier="bbbbbbbbbbb")
            excluded = await repository.get_video(scope=scope, identifier="ccccccccccc")
            version = await repository.catalog_version(scope)
        return {
            "all_ids": [item.id for item in all_page.items],
            "total_count": all_page.total_count,
            "filtered_ids": [item.id for item in filtered_page.items],
            "search_ids": [item.id for item in search_page.items],
            "streamers": sorted((item.id, item.video_count) for item in streamers),
            "detail_id": detail.id if detail else None,
            "excluded_detail": excluded,
            "version_suffix": version[-2:],
        }
    finally:
        await engine.dispose()


def _video(
    video_id: int,
    youtube_video_id: str,
    title: str,
    published_at: str,
    *,
    profile_key: str = "stellive-cliche-local",
    is_embeddable: bool = True,
) -> PublishedVideoModel:
    now = datetime(2026, 7, 20, tzinfo=UTC) + timedelta(seconds=video_id)
    return PublishedVideoModel(
        profile_key=profile_key,
        publish_mode="prod",
        environment="prod",
        video_id=video_id,
        variant="control",
        youtube_video_id=youtube_video_id,
        title=title,
        streamer_id="5",
        streamer_name="유즈하 리코",
        channel_id=9,
        channel_name="리코 다시보기",
        channel_handle="@rikoreplay",
        youtube_channel_id="UC-local",
        published_at=published_at,
        duration_text="1:00:00",
        duration_seconds=3600,
        thumbnail_url="https://img.example/video.jpg",
        is_embeddable=is_embeddable,
        display_title=title,
        display_summary="요약",
        main_topics=["게임"],
        episode_count=2,
        micro_event_count=3,
        topic_cluster_count=1,
        block_count=1,
        timeline_version="v1",
        timeline_url=f"http://127.0.0.1:9000/archive-public/{video_id}.json",
        artifact_sha256="a" * 64,
        artifact_byte_size=100,
        projection_updated_at=now,
        created_at=now,
        updated_at=now,
    )
