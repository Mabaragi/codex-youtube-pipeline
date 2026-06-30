from __future__ import annotations

import asyncio
import json
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
from codex_sdk_cli.domains.archive_publish.ports import (
    ArchiveChannelRecord,
    ArchiveStreamerRecord,
    ArchiveVideoArtifactRecord,
    ArchiveVideoArtifactWithVideoRecord,
)
from codex_sdk_cli.domains.archive_publish.use_cases import (
    _archive_micro_event_text,
    _index_artifact,
    _timeline_artifact,
)
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


def test_archive_publish_has_no_active_worker_module() -> None:
    assert not (Path("src/codex_sdk_cli/workers/archive_publish.py")).exists()


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
        channel=_channel(),
        streamer=_streamer(),
        composition=_composition(),
        micro_events=[
            _candidate(100, 1, "tr1-c000001", "tr1-c000002"),
            _candidate(101, 2, "tr1-c000003", "tr1-c000004"),
        ],
        cues=[
            _cue(1, "tr1-c000001", 10_000, 12_000),
            _cue(2, "tr1-c000002", 12_000, 15_000),
            _cue(3, "tr1-c000003", 15_000, 18_000),
            _cue(4, "tr1-c000004", 18_000, 20_000),
        ],
        prefix="archive",
        public_base_url="https://pub.example.dev",
        environment="prod",
        variant="control",
        schema_version=1,
    )

    episodes = cast(list[dict[str, object]], artifact.payload["episodes"])
    episode = episodes[0]
    assert episode["startMs"] == 10_000
    assert episode["endMs"] == 20_000
    video = cast(dict[str, object], artifact.payload["video"])
    assert video["streamer"] == {"id": 3, "name": "아마네 나기"}
    assert video["channel"] == {
        "id": 7,
        "name": "Nagi channel",
        "handle": "@nagi",
        "youtubeChannelId": "UC_NAGI",
    }
    micro_events = cast(list[dict[str, object]], episode["microEvents"])
    assert micro_events[0]["event"] == "게임 설정을 설명한다. 잠시 뒤 선택이 바뀐다."
    assert micro_events[1]["event"] == "채팅이 공략을 제안하고 받아들인다. 파냐가 옆에서 웃는다."
    assert micro_events[0]["startMs"] == 10_000
    assert micro_events[1]["endMs"] == 20_000
    blocks = cast(list[dict[str, object]], artifact.payload["blocks"])
    block_episodes = cast(list[dict[str, object]], blocks[0]["episodes"])
    assert block_episodes[0]["episodeId"] == "episode_001"
    assert cast(list[dict[str, object]], block_episodes[0]["microEvents"])[1][
        "event"
    ] == "채팅이 공략을 제안하고 받아들인다. 파냐가 옆에서 웃는다."
    assert "rawResponseText" not in artifact.payload
    assert "reviewFlags" not in artifact.payload
    assert "sourceTimelineCompositionId" not in artifact.payload
    assert "sourceTimelineTaskId" not in artifact.payload
    assert "sourceMicroEventTaskId" not in artifact.payload
    assert "startCueId" not in episode
    assert "endCueId" not in episode
    assert "startMicroEventCandidateId" not in episode
    assert "endMicroEventCandidateId" not in episode
    assert "highlightMicroEventCandidateIds" not in episode
    for micro_event in micro_events:
        assert "microEventCandidateId" not in micro_event
        assert "candidateIndex" not in micro_event
        assert "startCueId" not in micro_event
        assert "endCueId" not in micro_event
        assert "evidenceCueIds" not in micro_event
        assert "boundaryBefore" not in micro_event
        assert "boundaryAfter" not in micro_event
        assert "relationToPrevious" not in micro_event
        assert "continuesToNext" not in micro_event
        assert "supportLevel" not in micro_event
    assert "Overbroad episode repair failed" not in json.dumps(
        artifact.payload,
        ensure_ascii=False,
    )


def test_timeline_artifact_rejects_missing_candidate_mapping() -> None:
    with pytest.raises(ArchivePublishArtifactInvalid):
        _timeline_artifact(
            video=_video(),
            channel=_channel(),
            streamer=_streamer(),
            composition=_composition(),
            micro_events=[],
            cues=[],
            prefix="archive",
            public_base_url="https://pub.example.dev",
            environment="prod",
            variant="control",
            schema_version=1,
        )


def test_index_artifact_includes_streamer_and_channel_metadata() -> None:
    artifact = _index_artifact(
        artifacts=[
            ArchiveVideoArtifactWithVideoRecord(
                artifact=_video_artifact(),
                video=_video(),
                channel=_channel(),
                streamer=_streamer(),
            )
        ],
        prefix="archive",
        public_base_url="https://pub.example.dev",
        environment="prod",
        schema_version=1,
    )

    videos = cast(list[dict[str, object]], artifact.payload["videos"])
    video = videos[0]
    assert video["streamer"] == {"id": 3, "name": "아마네 나기"}
    assert video["channel"] == {
        "id": 7,
        "name": "Nagi channel",
        "handle": "@nagi",
        "youtubeChannelId": "UC_NAGI",
    }
    variants = cast(list[dict[str, object]], video["timelineVariants"])
    assert variants == [
        {
            "key": "control",
            "url": "https://pub.example.dev/archive/archive/v1/videos/71/timeline.json",
            "version": "20260627T120000Z",
        }
    ]


def test_archive_micro_event_text_removes_only_current_streamer_subjects() -> None:
    assert (
        _archive_micro_event_text(
            "치치가 설명한다. 파냐가 옆에서 웃는다.",
            streamer_subject_aliases=("스트리머", "치치"),
        )
        == "설명한다. 파냐가 옆에서 웃는다."
    )
    assert (
        _archive_micro_event_text(
            "파냐가 설명한다. 치치가 옆에서 웃는다.",
            streamer_subject_aliases=("카네코 파냐", "스트리머", "파냐"),
        )
        == "설명한다. 치치가 옆에서 웃는다."
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


def _channel() -> ArchiveChannelRecord:
    return ArchiveChannelRecord(
        id=7,
        name="Nagi channel",
        handle="@nagi",
        youtube_channel_id="UC_NAGI",
    )


def _streamer() -> ArchiveStreamerRecord:
    return ArchiveStreamerRecord(id=3, name="아마네 나기")


def _video_artifact() -> ArchiveVideoArtifactRecord:
    return ArchiveVideoArtifactRecord(
        id=15,
        video_id=71,
        source_timeline_composition_id=9,
        source_timeline_task_id=33,
        source_micro_event_task_id=22,
        publish_task_id=44,
        publish_job_id=45,
        environment="prod",
        variant="control",
        schema_version=1,
        version="20260627T120000Z",
        object_key="archive/archive/v1/videos/71/timeline.20260627T120000Z.control.json",
        public_url="https://pub.example.dev/archive/archive/v1/videos/71/timeline.json",
        sha256="b" * 64,
        byte_size=1234,
        block_count=1,
        episode_count=1,
        topic_cluster_count=1,
        review_flag_count=1,
        micro_event_count=2,
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
                end_micro_event_candidate_id=101,
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
                reason="Overbroad episode repair failed; original episode was kept.",
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
        event=(
            "스트리머가 게임 설정을 설명한다. 잠시 뒤 아마네 나기의 선택이 바뀐다."
            if candidate_index == 1
            else "채팅이 공략을 제안하고 나기가 받아들인다. 파냐가 옆에서 웃는다."
        ),
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
