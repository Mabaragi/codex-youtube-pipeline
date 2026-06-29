from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from codex_sdk_cli.domains.archive_publish.schemas import (
    ArchivePublishItemResponse,
    ArchivePublishRequest,
    ArchivePublishResponse,
)
from codex_sdk_cli.domains.micro_events.ports import MicroEventExtractionDetailRecord
from codex_sdk_cli.domains.operation_events.ports import OperationEventCreate
from codex_sdk_cli.domains.timelines.exceptions import TimelinePatchInvalid
from codex_sdk_cli.domains.timelines.patch_use_cases import PatchTimelineUseCase
from codex_sdk_cli.domains.timelines.ports import (
    JsonObject,
    TimelineBlockCreate,
    TimelineBlockRecord,
    TimelineCompositionCreate,
    TimelineCompositionRecord,
    TimelineEpisodeCreate,
    TimelineEpisodeRecord,
)
from codex_sdk_cli.domains.timelines.schemas import TimelinePatchRequest
from codex_sdk_cli.domains.videos.ports import VideoRecord

NOW = datetime(2026, 6, 30, tzinfo=UTC)


def test_timeline_patch_dry_run_splits_block_without_mutation() -> None:
    fakes = _Fakes()
    use_case = fakes.use_case()

    response = asyncio.run(
        use_case.execute(
            video_id=71,
            video_task_id=201,
            request=TimelinePatchRequest.model_validate(
                {
                    "dryRun": True,
                    "instruction": "Split the later segment into a new block.",
                    "operations": [
                        {
                            "operation": "split_block_after_episode",
                            "anchorEpisodeId": "episode_001",
                            "newBlock": {
                                "blockType": "POST_GAME",
                                "displayTitle": "After the game",
                            },
                        }
                    ],
                }
            ),
        )
    )

    assert response.applied is False
    assert fakes.timelines.replaced is None
    assert fakes.archive_publish.requests == []
    assert [block.episode_ids for block in response.after.blocks] == [
        ["episode_001"],
        ["episode_002", "episode_003"],
    ]
    assert response.after.blocks[1].block_id == "block_002"
    assert response.after.blocks[1].block_type == "POST_GAME"
    assert response.after.episodes[1].parent_block_id == "block_002"


def test_timeline_patch_apply_edits_display_copy_and_output_json() -> None:
    fakes = _Fakes()
    use_case = fakes.use_case()

    response = asyncio.run(
        use_case.execute(
            video_id=71,
            video_task_id=201,
            request=TimelinePatchRequest.model_validate(
                {
                    "dryRun": False,
                    "instruction": "Make this caption cuter.",
                    "operations": [
                        {
                            "operation": "edit_display_copy",
                            "targetType": "video",
                            "displayTitle": "오늘의 흐름",
                        },
                        {
                            "operation": "edit_display_copy",
                            "targetType": "episode",
                            "targetId": "episode_002",
                            "displaySummary": "이제 다음 얘기로 슥 넘어간다",
                        },
                    ],
                }
            ),
        )
    )

    assert response.applied is True
    assert fakes.timelines.replaced is not None
    replaced = fakes.timelines.replaced
    assert replaced.raw_response_text == "RAW ORIGINAL"
    assert replaced.display_title == "오늘의 흐름"
    episode_jsons = cast(list[JsonObject], replaced.output_json["episodes"])
    episode_002 = next(item for item in episode_jsons if item["episode_id"] == "episode_002")
    assert episode_002["display_summary"] == "이제 다음 얘기로 슥 넘어간다"
    assert fakes.events.items[0].event_type == "timeline_patch.applied"
    assert fakes.events.items[0].metadata_json["instruction"] == "Make this caption cuter."


def test_timeline_patch_rejects_last_episode_split() -> None:
    fakes = _Fakes()
    use_case = fakes.use_case()

    with pytest.raises(TimelinePatchInvalid, match="last episode"):
        asyncio.run(
            use_case.execute(
                video_id=71,
                video_task_id=201,
                request=TimelinePatchRequest.model_validate(
                    {
                        "dryRun": False,
                        "operations": [
                            {
                                "operation": "split_block_after_episode",
                                "anchorEpisodeId": "episode_003",
                            }
                        ],
                    }
                ),
            )
        )

    assert fakes.timelines.replaced is None


def test_timeline_patch_rejects_ambiguous_anchor() -> None:
    fakes = _Fakes(record=_timeline_record(duplicate_anchor=True))
    use_case = fakes.use_case()

    with pytest.raises(TimelinePatchInvalid, match="matched 2 episodes"):
        asyncio.run(
            use_case.execute(
                video_id=71,
                video_task_id=201,
                request=TimelinePatchRequest.model_validate(
                    {
                        "dryRun": True,
                        "operations": [
                            {
                                "operation": "split_block_after_episode",
                                "anchor": {"displaySummary": "같은 요약"},
                            }
                        ],
                    }
                ),
            )
        )


def test_timeline_patch_apply_can_publish_regenerated_archive() -> None:
    fakes = _Fakes()
    use_case = fakes.use_case()

    response = asyncio.run(
        use_case.execute(
            video_id=71,
            video_task_id=201,
            request=TimelinePatchRequest.model_validate(
                {
                    "dryRun": False,
                    "operations": [
                        {
                            "operation": "split_block_after_episode",
                            "anchorEpisodeId": "episode_001",
                        }
                    ],
                    "publish": {"enabled": True, "environment": "prod"},
                }
            ),
        )
    )

    assert response.publish_result is not None
    assert response.publish_result["publishedCount"] == 1
    assert response.publish_summary is not None
    assert response.publish_summary.status == "succeeded"
    assert response.publish_summary.reason == "regenerated"
    assert response.publish_summary.artifact_id == 401
    assert response.publish_summary.public_url == "https://example.test/timeline.json"
    assert len(fakes.archive_publish.requests) == 1
    publish_request = fakes.archive_publish.requests[0]
    assert publish_request.target == "selected_videos"
    assert publish_request.video_ids == [71]
    assert publish_request.regenerate_succeeded is True


class _Fakes:
    def __init__(self, record: TimelineCompositionRecord | None = None) -> None:
        self.videos = _VideoRepository()
        self.timelines = _TimelineRepository(record or _timeline_record())
        self.micro_events = _MicroEventRepository()
        self.cues = _TranscriptCueRepository()
        self.events = _EventRecorder()
        self.archive_publish = _ArchivePublisher()

    def use_case(self) -> PatchTimelineUseCase:
        return PatchTimelineUseCase(
            videos=cast(Any, self.videos),
            timelines=cast(Any, self.timelines),
            micro_events=cast(Any, self.micro_events),
            transcript_cues=cast(Any, self.cues),
            events=self.events,
            archive_publish=self.archive_publish,
        )


class _VideoRepository:
    async def get_video(self, video_id: int) -> VideoRecord | None:
        if video_id != 71:
            return None
        return VideoRecord(
            id=71,
            channel_id=1,
            youtube_video_id="youtube-1",
            title="테스트 영상",
            description="",
            published_at=NOW,
            duration="PT1H",
            thumbnail_url=None,
            source_listing_api_call_id=None,
            source_details_api_call_id=None,
            source_job_id=None,
            created_at=NOW,
            updated_at=NOW,
        )


class _TimelineRepository:
    def __init__(self, record: TimelineCompositionRecord) -> None:
        self.record = record
        self.replaced: TimelineCompositionCreate | None = None

    async def delete_composition(self, video_task_id: int) -> None:
        raise AssertionError("delete_composition should not be called")

    async def replace_composition(
        self,
        create: TimelineCompositionCreate,
    ) -> TimelineCompositionRecord | None:
        self.replaced = create
        self.record = _record_from_create(create, composition_id=self.record.id)
        return self.record

    async def get_composition(
        self,
        *,
        video_id: int,
        video_task_id: int,
    ) -> TimelineCompositionRecord | None:
        if video_id == self.record.video_id and video_task_id == self.record.video_task_id:
            return self.record
        return None

    async def get_latest_succeeded_composition(
        self,
        *,
        video_id: int,
    ) -> TimelineCompositionRecord | None:
        if video_id == self.record.video_id:
            return self.record
        return None


class _MicroEventRepository:
    async def get_extraction(
        self,
        *,
        video_id: int,
        video_task_id: int,
    ) -> MicroEventExtractionDetailRecord | None:
        return None


class _TranscriptCueRepository:
    async def list_cues(self, transcript_id: int) -> list[object]:
        return []


class _EventRecorder:
    def __init__(self) -> None:
        self.items: list[OperationEventCreate] = []

    async def record_event(self, event: OperationEventCreate) -> None:
        self.items.append(event)


class _ArchivePublisher:
    def __init__(self) -> None:
        self.requests: list[ArchivePublishRequest] = []

    async def publish(self, request: ArchivePublishRequest) -> ArchivePublishResponse:
        self.requests.append(request)
        return ArchivePublishResponse(
            requestedCount=1,
            scannedCount=1,
            processedCount=1,
            publishedCount=1,
            alreadyPublishedCount=0,
            regeneratedCount=1,
            failedCount=0,
            failedSkippedCount=0,
            ineligibleCount=0,
            items=[
                ArchivePublishItemResponse(
                    videoId=71,
                    youtubeVideoId="youtube-1",
                    videoTaskId=301,
                    status="succeeded",
                    reason="regenerated",
                    sourceTimelineTaskId=201,
                    sourceTimelineCompositionId=501,
                    environment=request.environment,
                    variant=request.variant,
                    schemaVersion=request.schema_version,
                    artifactId=401,
                    publicUrl="https://example.test/timeline.json",
                    errorType=None,
                    errorMessage=None,
                )
            ],
        )


def _timeline_record(*, duplicate_anchor: bool = False) -> TimelineCompositionRecord:
    episodes = [
        _episode_record(1, "episode_001", "block_001", "시작", "같은 요약"),
        _episode_record(
            2,
            "episode_002",
            "block_001",
            "중간",
            "같은 요약" if duplicate_anchor else "중간 요약",
        ),
        _episode_record(3, "episode_003", "block_001", "끝", "끝 요약"),
    ]
    blocks = [
        TimelineBlockRecord(
            id=1,
            composition_id=501,
            block_id="block_001",
            block_index=1,
            block_type="GAMEPLAY",
            title="게임 흐름",
            summary="게임을 진행한다",
            display_title="게임 흐름",
            display_summary="게임을 진행한다",
            episode_ids=[episode.episode_id for episode in episodes],
            created_at=NOW,
            updated_at=NOW,
        )
    ]
    return TimelineCompositionRecord(
        id=501,
        video_task_id=201,
        video_id=71,
        youtube_video_id="youtube-1",
        source_micro_event_task_id=101,
        source_micro_event_fingerprint="fingerprint-1",
        copy_style="LIGHT_FANDOM_V1",
        status="succeeded",
        model="gpt-5.5",
        reasoning_effort="medium",
        title="테스트 타임라인",
        summary="테스트 요약",
        display_title="테스트 타임라인",
        display_summary="테스트 요약",
        main_topics=["게임"],
        output_json=_output_json(blocks, episodes),
        validation_warnings=[],
        source_job_id=11,
        source_job_attempt_id=12,
        codex_thread_id="thread-1",
        codex_turn_id="turn-1",
        raw_response_text="RAW ORIGINAL",
        created_at=NOW,
        updated_at=NOW,
        blocks=blocks,
        episodes=episodes,
        topic_clusters=[],
        review_flags=[],
    )


def _record_from_create(
    create: TimelineCompositionCreate,
    *,
    composition_id: int,
) -> TimelineCompositionRecord:
    return TimelineCompositionRecord(
        id=composition_id,
        video_task_id=create.video_task_id,
        video_id=create.video_id,
        youtube_video_id="youtube-1",
        source_micro_event_task_id=create.source_micro_event_task_id,
        source_micro_event_fingerprint=create.source_micro_event_fingerprint,
        copy_style=create.copy_style,
        status="succeeded",
        model=create.model,
        reasoning_effort=create.reasoning_effort,
        title=create.title,
        summary=create.summary,
        display_title=create.display_title,
        display_summary=create.display_summary,
        main_topics=create.main_topics,
        output_json=create.output_json,
        validation_warnings=create.validation_warnings,
        source_job_id=create.source_job_id,
        source_job_attempt_id=create.source_job_attempt_id,
        codex_thread_id=create.codex_thread_id,
        codex_turn_id=create.codex_turn_id,
        raw_response_text=create.raw_response_text,
        created_at=NOW,
        updated_at=NOW,
        blocks=[
            _block_record_from_create(index, composition_id, block)
            for index, block in enumerate(create.blocks, start=1)
        ],
        episodes=[
            _episode_record_from_create(index, composition_id, episode)
            for index, episode in enumerate(create.episodes, start=1)
        ],
        topic_clusters=[],
        review_flags=[],
    )


def _block_record_from_create(
    index: int,
    composition_id: int,
    block: TimelineBlockCreate,
) -> TimelineBlockRecord:
    return TimelineBlockRecord(
        id=index,
        composition_id=composition_id,
        block_id=block.block_id,
        block_index=block.block_index,
        block_type=block.block_type,
        title=block.title,
        summary=block.summary,
        display_title=block.display_title,
        display_summary=block.display_summary,
        episode_ids=block.episode_ids,
        created_at=NOW,
        updated_at=NOW,
    )


def _episode_record_from_create(
    index: int,
    composition_id: int,
    episode: TimelineEpisodeCreate,
) -> TimelineEpisodeRecord:
    return TimelineEpisodeRecord(
        id=index,
        composition_id=composition_id,
        episode_id=episode.episode_id,
        episode_index=episode.episode_index,
        parent_block_id=episode.parent_block_id,
        start_micro_event_candidate_id=episode.start_micro_event_candidate_id,
        end_micro_event_candidate_id=episode.end_micro_event_candidate_id,
        program_mode=episode.program_mode,
        primary_content_kind=episode.primary_content_kind,
        title=episode.title,
        summary=episode.summary,
        display_title=episode.display_title,
        display_summary=episode.display_summary,
        topics=episode.topics,
        viewer_tags=episode.viewer_tags,
        highlight_micro_event_candidate_ids=episode.highlight_micro_event_candidate_ids,
        visibility=episode.visibility,
        created_at=NOW,
        updated_at=NOW,
    )


def _episode_record(
    index: int,
    episode_id: str,
    block_id: str,
    display_title: str,
    display_summary: str,
) -> TimelineEpisodeRecord:
    return TimelineEpisodeRecord(
        id=index,
        composition_id=501,
        episode_id=episode_id,
        episode_index=index,
        parent_block_id=block_id,
        start_micro_event_candidate_id=index,
        end_micro_event_candidate_id=index,
        program_mode="GAMEPLAY",
        primary_content_kind="GAME_PROGRESS",
        title=display_title,
        summary=display_summary,
        display_title=display_title,
        display_summary=display_summary,
        topics=["게임"],
        viewer_tags=["GAME_PROGRESS"],
        highlight_micro_event_candidate_ids=[index],
        visibility="DEFAULT",
        created_at=NOW,
        updated_at=NOW,
    )


def _output_json(
    blocks: list[TimelineBlockRecord],
    episodes: list[TimelineEpisodeRecord],
) -> JsonObject:
    return {
        "video_summary": {
            "title": "테스트 타임라인",
            "summary": "테스트 요약",
            "display_title": "테스트 타임라인",
            "display_summary": "테스트 요약",
            "main_topics": ["게임"],
        },
        "blocks": [
            {
                "block_id": block.block_id,
                "block_type": block.block_type,
                "title": block.title,
                "summary": block.summary,
                "display_title": block.display_title,
                "display_summary": block.display_summary,
                "episode_ids": block.episode_ids,
            }
            for block in blocks
        ],
        "episodes": [
            {
                "episode_id": episode.episode_id,
                "parent_block_id": episode.parent_block_id,
                "start_micro_event_id": f"me_{episode.episode_index:04d}",
                "end_micro_event_id": f"me_{episode.episode_index:04d}",
                "program_mode": episode.program_mode,
                "primary_content_kind": episode.primary_content_kind,
                "title": episode.title,
                "summary": episode.summary,
                "display_title": episode.display_title,
                "display_summary": episode.display_summary,
                "topics": episode.topics,
                "viewer_tags": episode.viewer_tags,
                "highlight_micro_event_ids": [f"me_{episode.episode_index:04d}"],
                "visibility": episode.visibility,
            }
            for episode in episodes
        ],
        "topic_clusters": [],
        "review_flags": [],
    }
