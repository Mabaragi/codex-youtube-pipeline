from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from alembic.config import Config
from sqlalchemy import inspect

from alembic import command
from codex_sdk_cli.api.main import app
from codex_sdk_cli.domains.archive_publish.exceptions import (
    ArchivePublishArtifactInvalid,
)
from codex_sdk_cli.domains.archive_publish.use_cases import _timeline_artifact
from codex_sdk_cli.domains.micro_events.ports import MicroEventCandidateRecord
from codex_sdk_cli.domains.timelines.ports import (
    TimelineBlockRecord,
    TimelineCompositionRecord,
    TimelineEpisodeRecord,
    TimelineReviewFlagRecord,
    TimelineTopicClusterRecord,
)
from codex_sdk_cli.domains.transcript_cues.ports import TranscriptCueRecord
from codex_sdk_cli.domains.videos.ports import VideoRecord
from codex_sdk_cli.infra.database.session import create_database_engine

NOW = datetime(2026, 6, 27, tzinfo=UTC)


def test_archive_publish_openapi_paths_are_registered() -> None:
    schema = app.openapi()

    assert "/video-tasks/archive-publish" in schema["paths"]
    assert "/video-tasks/archive-publish/enqueue" not in schema["paths"]
    assert "/ops/archive/current" in schema["paths"]
    assert "/ops/archive/videos" in schema["paths"]


def test_archive_worker_is_kept_only_as_legacy_reference() -> None:
    assert Path("legacy/src/codex_sdk_cli/workers/archive_publish.py").exists()
    assert not Path("src/codex_sdk_cli/workers/archive_publish.py").exists()


def test_archive_publish_migration_creates_archive_tables(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{(tmp_path / 'archive.db').as_posix()}"
    monkeypatch.setenv("CODEX_CLI_DATABASE_URL", database_url)

    command.upgrade(_alembic_config(), "head")

    tables = asyncio.run(_table_names(database_url))
    assert "archive_video_artifacts" in tables
    assert "archive_index_publications" in tables


def test_timeline_artifact_maps_episode_candidate_ranges_to_cue_times() -> None:
    artifact = _timeline_artifact(
        video=_video(),
        composition=_composition(),
        micro_events=[_candidate(100, 1, "tr1-c000001", "tr1-c000002")],
        cues=[
            _cue(1, "tr1-c000001", 10_000, 12_000),
            _cue(2, "tr1-c000002", 12_000, 15_000),
        ],
        prefix="archive",
        public_base_url="https://pub.example.dev",
        environment="prod",
        variant="control",
        schema_version=1,
    )

    episodes = cast(list[dict[str, object]], artifact.payload["episodes"])
    episode = episodes[0]
    assert episode["startCueId"] == "tr1-c000001"
    assert episode["endCueId"] == "tr1-c000002"
    assert episode["startMs"] == 10_000
    assert episode["endMs"] == 15_000
    assert "rawResponseText" not in artifact.payload


def test_timeline_artifact_rejects_missing_candidate_mapping() -> None:
    with pytest.raises(ArchivePublishArtifactInvalid):
        _timeline_artifact(
            video=_video(),
            composition=_composition(),
            micro_events=[],
            cues=[],
            prefix="archive",
            public_base_url="https://pub.example.dev",
            environment="prod",
            variant="control",
            schema_version=1,
        )


async def _table_names(database_url: str) -> set[str]:
    engine = create_database_engine(database_url)
    try:
        async with engine.connect() as connection:
            return set(
                await connection.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())
            )
    finally:
        await engine.dispose()


def _alembic_config() -> Config:
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    return config


def _video() -> VideoRecord:
    return VideoRecord(
        id=71,
        channel_id=7,
        youtube_video_id="JSbJMOXtqn8",
        title="Broadcast title",
        description="",
        published_at=NOW,
        duration="PT1H",
        thumbnail_url="https://img.example.dev/thumb.jpg",
        source_listing_api_call_id=None,
        source_details_api_call_id=None,
        source_job_id=None,
        created_at=NOW,
        updated_at=NOW,
    )


def _composition() -> TimelineCompositionRecord:
    return TimelineCompositionRecord(
        id=9,
        video_task_id=33,
        video_id=71,
        youtube_video_id="JSbJMOXtqn8",
        source_micro_event_task_id=22,
        source_micro_event_fingerprint="a" * 64,
        copy_style="LIGHT_FANDOM_V1",
        status="succeeded",
        model="gpt-5.2",
        reasoning_effort="medium",
        title="Timeline",
        summary="Summary",
        display_title="Timeline",
        display_summary="Summary",
        main_topics=["topic"],
        output_json={},
        validation_warnings=[],
        source_job_id=44,
        source_job_attempt_id=45,
        codex_thread_id=None,
        codex_turn_id=None,
        raw_response_text=None,
        created_at=NOW,
        updated_at=NOW,
        blocks=[
            TimelineBlockRecord(
                id=1,
                composition_id=9,
                block_id="block_001",
                block_index=1,
                block_type="JUST_CHATTING",
                title="Block",
                summary="Block summary",
                display_title="Block",
                display_summary="Block summary",
                episode_ids=["episode_001"],
                created_at=NOW,
                updated_at=NOW,
            )
        ],
        episodes=[
            TimelineEpisodeRecord(
                id=1,
                composition_id=9,
                episode_id="episode_001",
                episode_index=1,
                parent_block_id="block_001",
                start_micro_event_candidate_id=100,
                end_micro_event_candidate_id=100,
                program_mode="JUST_CHATTING",
                primary_content_kind="PERSONAL_STORY",
                title="Episode",
                summary="Episode summary",
                display_title="Episode",
                display_summary="Episode summary",
                topics=["topic"],
                viewer_tags=["STORY"],
                highlight_micro_event_candidate_ids=[100],
                visibility="DEFAULT",
                created_at=NOW,
                updated_at=NOW,
            )
        ],
        topic_clusters=[
            TimelineTopicClusterRecord(
                id=1,
                composition_id=9,
                topic_id="topic_001",
                topic_index=1,
                label="Topic",
                summary="Topic summary",
                display_label="Topic",
                episode_ids=["episode_001"],
                created_at=NOW,
                updated_at=NOW,
            )
        ],
        review_flags=[
            TimelineReviewFlagRecord(
                id=1,
                composition_id=9,
                flag_index=1,
                start_micro_event_candidate_id=100,
                end_micro_event_candidate_id=100,
                type="BOUNDARY_AMBIGUOUS",
                reason="Check boundary.",
                created_at=NOW,
                updated_at=NOW,
            )
        ],
    )


def _candidate(
    candidate_id: int,
    candidate_index: int,
    start_cue_id: str,
    end_cue_id: str,
) -> MicroEventCandidateRecord:
    return MicroEventCandidateRecord(
        id=candidate_id,
        window_id=1,
        video_task_id=22,
        transcript_id=47,
        candidate_index=candidate_index,
        activity="JUST_CHATTING",
        event="Event",
        start_cue_id=start_cue_id,
        end_cue_id=end_cue_id,
        evidence_cue_ids=[start_cue_id, end_cue_id],
        boundary_before=True,
        boundary_after=True,
        confidence=0.9,
        program_mode="JUST_CHATTING",
        content_kind="PERSONAL_STORY",
        topics=["topic"],
        relation_to_previous="NEW_TOPIC",
        continues_to_next=False,
        support_level="DIRECT",
        created_at=NOW,
        updated_at=NOW,
    )


def _cue(index: int, cue_id: str, start_ms: int, end_ms: int) -> TranscriptCueRecord:
    return TranscriptCueRecord(
        id=index,
        transcript_id=47,
        cue_id=cue_id,
        cue_index=index,
        text="text",
        start_ms=start_ms,
        end_ms=end_ms,
        duration_ms=end_ms - start_ms,
        source_segment_index=index,
        source_job_id=None,
        source_job_attempt_id=None,
        created_at=NOW,
        updated_at=NOW,
    )
