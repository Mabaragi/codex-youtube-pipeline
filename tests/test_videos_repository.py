from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command
from codex_sdk_cli.domains.channels.ports import ChannelCreate
from codex_sdk_cli.domains.external_api_calls.ports import ExternalApiCallCreate
from codex_sdk_cli.domains.pipeline_jobs.ports import PipelineJobCreate
from codex_sdk_cli.domains.videos.exceptions import VideoAlreadyExists
from codex_sdk_cli.domains.videos.ports import VideoCreate
from codex_sdk_cli.infra.channels.repository import SqlAlchemyChannelRepository
from codex_sdk_cli.infra.database.session import create_database_engine, create_session_factory
from codex_sdk_cli.infra.external_api_calls.repository import SqlAlchemyExternalApiCallRepository
from codex_sdk_cli.infra.pipeline_jobs.repository import SqlAlchemyPipelineJobRepository
from codex_sdk_cli.infra.streamers.repository import SqlAlchemyStreamerRepository
from codex_sdk_cli.infra.videos.repository import SqlAlchemyVideoRepository


def test_video_repository_bulk_creates_lists_and_detects_existing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{(tmp_path / 'videos.db').as_posix()}"
    monkeypatch.setenv("CODEX_CLI_DATABASE_URL", database_url)
    command.upgrade(_alembic_config(), "head")

    asyncio.run(_exercise_repository(database_url))


async def _exercise_repository(database_url: str) -> None:
    engine = create_database_engine(database_url)
    try:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            streamers = SqlAlchemyStreamerRepository(session)
            channels = SqlAlchemyChannelRepository(session)
            external_api_calls = SqlAlchemyExternalApiCallRepository(session)
            pipeline_jobs = SqlAlchemyPipelineJobRepository(session)
            videos = SqlAlchemyVideoRepository(session)

            streamer = await streamers.create_streamer(name="Google")
            channel = await channels.create_channel(
                ChannelCreate(
                    streamer_id=streamer.id,
                    handle="@GoogleDevelopers",
                    name="Google for Developers",
                    youtube_channel_id="UC_x5XG1OV2P6uZZ5FSM9Ttw",
                )
            )
            job = await pipeline_jobs.create_job(
                PipelineJobCreate(
                    step="video_collect",
                    status="running",
                    subject_type="channel",
                    subject_id=channel.id,
                    external_key="youtube-channel-test",
                    input_json={
                        "channelId": channel.id,
                        "youtubeChannelId": "UC_x5XG1OV2P6uZZ5FSM9Ttw",
                    },
                    input_hash="0" * 64,
                )
            )
            search_call = await external_api_calls.create_external_api_call(
                _external_call("search.list")
            )
            details_call = await external_api_calls.create_external_api_call(
                _external_call("videos.list")
            )
            now = datetime.now(UTC)

            created = await videos.create_videos(
                [
                    _video_create(
                        channel.id,
                        "video-old",
                        now - timedelta(days=1),
                        search_call.id,
                        details_call.id,
                        job.id,
                    ),
                    _video_create(
                        channel.id,
                        "video-new",
                        now,
                        search_call.id,
                        details_call.id,
                        job.id,
                    ),
                ]
            )
            listed = await videos.list_videos(channel_id=channel.id)
            existing = await videos.find_existing_youtube_video_id(
                channel_id=channel.id,
                youtube_video_ids=("missing", "video-new", "video-old"),
            )

            assert [record.youtube_video_id for record in created] == ["video-old", "video-new"]
            assert [record.youtube_video_id for record in listed] == ["video-new", "video-old"]
            assert existing == "video-new"

            with pytest.raises(VideoAlreadyExists):
                await videos.create_videos(
                    [
                        _video_create(
                            channel.id,
                            "video-new",
                            now,
                            search_call.id,
                            details_call.id,
                            job.id,
                        )
                    ]
                )
    finally:
        await engine.dispose()


def _video_create(
    channel_id: int,
    youtube_video_id: str,
    published_at: datetime,
    source_search_api_call_id: int,
    source_details_api_call_id: int,
    source_job_id: int,
) -> VideoCreate:
    return VideoCreate(
        channel_id=channel_id,
        youtube_video_id=youtube_video_id,
        title=f"title {youtube_video_id}",
        description="description",
        published_at=published_at,
        duration="PT1M",
        privacy_status="public",
        upload_status="processed",
        live_broadcast_content="none",
        view_count=1,
        like_count=2,
        comment_count=3,
        thumbnail_url="https://img.example/high.jpg",
        source_search_api_call_id=source_search_api_call_id,
        source_details_api_call_id=source_details_api_call_id,
        source_job_id=source_job_id,
    )


def _external_call(operation: str) -> ExternalApiCallCreate:
    return ExternalApiCallCreate(
        provider="youtube_data",
        operation=operation,
        request_method="GET",
        request_url=f"https://www.googleapis.com/youtube/v3/{operation}",
        request_params={"part": "snippet"},
        request_body=None,
        response_status_code=200,
        response_headers={"content-type": "application/json"},
        response_storage_bucket="raw",
        response_storage_object_name=f"external-api-calls/{operation}.json",
        response_storage_uri=f"s3://raw/external-api-calls/{operation}.json",
        response_sha256="0" * 64,
        schema_name="schema",
        schema_version="v1",
        validation_status="valid",
        validation_error=None,
        duration_ms=12,
        quota_cost=1,
    )


def _alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", "alembic")
    config.set_main_option("prepend_sys_path", ".")
    config.set_main_option("path_separator", "os")
    return config
