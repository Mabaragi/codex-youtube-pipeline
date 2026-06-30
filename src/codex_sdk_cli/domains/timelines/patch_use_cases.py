from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Protocol, cast

from codex_sdk_cli.domains.archive_publish.schemas import ArchivePublishRequest
from codex_sdk_cli.domains.micro_events.ports import (
    MicroEventCandidateRecord,
    MicroEventExtractionDetailRecord,
    MicroEventExtractionRepositoryPort,
)
from codex_sdk_cli.domains.operation_events.ports import (
    OperationEventCreate,
    OperationEventRecorderPort,
)
from codex_sdk_cli.domains.timelines.exceptions import (
    TimelineCompositionNotFound,
    TimelineCompositionPersistenceError,
    TimelinePatchInvalid,
)
from codex_sdk_cli.domains.timelines.ports import (
    JsonObject,
    TimelineBlockCreate,
    TimelineBlockRecord,
    TimelineCompositionCreate,
    TimelineCompositionRecord,
    TimelineCompositionRepositoryPort,
    TimelineEpisodeCreate,
    TimelineEpisodeRecord,
    TimelineReviewFlagCreate,
    TimelineReviewFlagRecord,
    TimelineTopicClusterCreate,
    TimelineTopicClusterRecord,
)
from codex_sdk_cli.domains.timelines.schemas import (
    TimelinePatchBlockSummaryResponse,
    TimelinePatchDiffResponse,
    TimelinePatchEpisodeSummaryResponse,
    TimelinePatchOperationRequest,
    TimelinePatchOperationResultResponse,
    TimelinePatchPublishSummaryResponse,
    TimelinePatchRequest,
    TimelinePatchResponse,
    TimelinePatchTopicClusterSummaryResponse,
)
from codex_sdk_cli.domains.transcript_cues.ports import (
    TranscriptCueRecord,
    TranscriptCueRepositoryPort,
)
from codex_sdk_cli.domains.videos.exceptions import VideoNotFound
from codex_sdk_cli.domains.videos.ports import VideoRepositoryPort


class TimelinePatchArchivePublisherPort(Protocol):
    async def publish(self, request: ArchivePublishRequest) -> object:
        """Publish archive artifacts for patched timelines."""


@dataclass(slots=True)
class _PatchState:
    display_title: str
    display_summary: str
    blocks: list[TimelineBlockCreate]
    episodes: list[TimelineEpisodeCreate]
    topic_clusters: list[TimelineTopicClusterCreate]
    review_flags: list[TimelineReviewFlagCreate]


@dataclass(slots=True)
class _MicroEventPatchContext:
    detail: MicroEventExtractionDetailRecord
    candidates_by_id: dict[int, MicroEventCandidateRecord]
    original_events_by_id: dict[int, str]
    events_by_id: dict[int, str]
    episode_id_by_candidate_id: dict[int, str]


class PatchTimelineUseCase:
    def __init__(
        self,
        *,
        videos: VideoRepositoryPort,
        timelines: TimelineCompositionRepositoryPort,
        micro_events: MicroEventExtractionRepositoryPort,
        transcript_cues: TranscriptCueRepositoryPort,
        events: OperationEventRecorderPort,
        archive_publish: TimelinePatchArchivePublisherPort,
    ) -> None:
        self._videos = videos
        self._timelines = timelines
        self._micro_events = micro_events
        self._transcript_cues = transcript_cues
        self._events = events
        self._archive_publish = archive_publish

    async def execute(
        self,
        *,
        video_id: int,
        video_task_id: int,
        request: TimelinePatchRequest,
    ) -> TimelinePatchResponse:
        video = await self._videos.get_video(video_id)
        if video is None:
            raise VideoNotFound("Video not found.")
        record = await self._timelines.get_composition(
            video_id=video_id,
            video_task_id=video_task_id,
        )
        if record is None:
            raise TimelineCompositionNotFound("Timeline composition not found.")

        state = _state_from_record(record)
        before = _diff_response(state)
        source_detail = await self._source_micro_event_detail_if_needed(record, request)
        episode_time_ranges = await self._episode_time_ranges_if_needed(
            record,
            request,
            source_detail,
        )
        micro_event_context = _micro_event_patch_context(record, request, source_detail)
        operation_results: list[TimelinePatchOperationResultResponse] = []
        for operation in request.operations:
            operation_results.append(
                _apply_operation(
                    state,
                    operation,
                    episode_time_ranges=episode_time_ranges,
                    micro_event_context=micro_event_context,
                )
            )
        _validate_patch_invariants(state)
        after = _diff_response(state)
        output_json = _patched_output_json(record, state)
        publish_result: JsonObject | None = None

        if not request.dry_run:
            updated = record
            if _has_timeline_edits(request):
                create = _composition_create(record, state, output_json=output_json)
                replaced = await self._timelines.replace_composition(create)
                if replaced is None:
                    raise TimelineCompositionPersistenceError(
                        "Timeline composition persistence failed."
                    )
                updated = replaced
            await self._apply_micro_event_updates(micro_event_context)
            publish_result = await self._publish_if_requested(record, request)
            await self._record_patch_applied(
                record=updated,
                request=request,
                operation_results=operation_results,
                before=before,
                after=after,
                publish_result=publish_result,
            )
            record = updated

        return TimelinePatchResponse(
            videoId=record.video_id,
            youtubeVideoId=record.youtube_video_id,
            videoTaskId=record.video_task_id,
            timelineCompositionId=record.id,
            sourceMicroEventTaskId=record.source_micro_event_task_id,
            dryRun=request.dry_run,
            applied=not request.dry_run,
            operations=operation_results,
            before=before,
            after=after,
            validationWarnings=record.validation_warnings,
            publishResult=publish_result,
            publishSummary=_publish_response_summary(publish_result),
        )

    async def _source_micro_event_detail_if_needed(
        self,
        record: TimelineCompositionRecord,
        request: TimelinePatchRequest,
    ) -> MicroEventExtractionDetailRecord | None:
        if not any(
            _operation_needs_source_micro_events(operation)
            for operation in request.operations
        ):
            return None
        detail = await self._micro_events.get_extraction(
            video_id=record.video_id,
            video_task_id=record.source_micro_event_task_id,
        )
        if detail is None:
            raise TimelinePatchInvalid("Source micro-event extraction not found.")
        return detail

    async def _episode_time_ranges_if_needed(
        self,
        record: TimelineCompositionRecord,
        request: TimelinePatchRequest,
        detail: MicroEventExtractionDetailRecord | None,
    ) -> dict[str, tuple[int, int]]:
        if not any(
            operation.anchor is not None and operation.anchor.timecode is not None
            for operation in request.operations
        ):
            return {}
        if detail is None:
            raise TimelinePatchInvalid("Source micro-event extraction not found.")
        if detail.transcript_id is None:
            raise TimelinePatchInvalid("Source micro-event extraction is missing transcript id.")
        cues = await self._transcript_cues.list_cues(detail.transcript_id)
        cue_by_id = {cue.cue_id: cue for cue in cues}
        candidate_by_id = {
            candidate.id: candidate
            for window in detail.windows
            for candidate in window.micro_events
        }
        return _episode_time_ranges(record, candidate_by_id, cue_by_id)

    async def _apply_micro_event_updates(
        self,
        context: _MicroEventPatchContext | None,
    ) -> None:
        if context is None:
            return
        for candidate_id in _edited_micro_event_candidate_ids(context):
            updated = await self._micro_events.update_candidate_event(
                video_task_id=context.detail.video_task_id,
                candidate_id=candidate_id,
                event=context.events_by_id[candidate_id],
            )
            if updated is None:
                raise TimelinePatchInvalid(
                    f"Micro-event candidate not found in source extraction: {candidate_id}"
                )

    async def _publish_if_requested(
        self,
        record: TimelineCompositionRecord,
        request: TimelinePatchRequest,
    ) -> JsonObject | None:
        if request.publish is None or not request.publish.enabled:
            return None
        response = await self._archive_publish.publish(
            ArchivePublishRequest(
                target="selected_videos",
                videoIds=[record.video_id],
                limit=1,
                environment=request.publish.environment,
                variant=request.publish.variant,
                schemaVersion=request.publish.schema_version,
                retryFailed=True,
                regenerateSucceeded=True,
            )
        )
        if hasattr(response, "model_dump"):
            return cast(JsonObject, response.model_dump(by_alias=True))
        return cast(JsonObject, response)

    async def _record_patch_applied(
        self,
        *,
        record: TimelineCompositionRecord,
        request: TimelinePatchRequest,
        operation_results: list[TimelinePatchOperationResultResponse],
        before: TimelinePatchDiffResponse,
        after: TimelinePatchDiffResponse,
        publish_result: JsonObject | None,
    ) -> None:
        await self._events.record_event(
            OperationEventCreate(
                event_type="timeline_patch.applied",
                severity="info",
                message="Timeline patch applied.",
                actor_type="manual_api",
                source="timeline.patch",
                video_task_id=record.video_task_id,
                video_id=record.video_id,
                subject_type="timeline_composition",
                subject_id=record.id,
                external_key=record.youtube_video_id,
                metadata_json={
                    "instruction": request.instruction,
                    "operationCount": len(operation_results),
                    "changedBlockIds": sorted(
                        {
                            block_id
                            for result in operation_results
                            for block_id in result.changed_block_ids
                        }
                    ),
                    "changedEpisodeIds": sorted(
                        {
                            episode_id
                            for result in operation_results
                            for episode_id in result.changed_episode_ids
                        }
                    ),
                    "changedTopicIds": sorted(
                        {
                            topic_id
                            for result in operation_results
                            for topic_id in result.changed_topic_ids
                        }
                    ),
                    "changedMicroEventCandidateIds": sorted(
                        {
                            candidate_id
                            for result in operation_results
                            for candidate_id in result.changed_micro_event_candidate_ids
                        }
                    ),
                    "microEventUpdates": _micro_event_event_updates(operation_results),
                    "before": _event_diff(before),
                    "after": _event_diff(after),
                    "publishResult": _publish_event_summary(publish_result),
                },
            )
        )


def _state_from_record(record: TimelineCompositionRecord) -> _PatchState:
    return _PatchState(
        display_title=record.display_title,
        display_summary=record.display_summary,
        blocks=[_block_create(block) for block in record.blocks],
        episodes=[_episode_create(episode) for episode in record.episodes],
        topic_clusters=[_topic_create(topic) for topic in record.topic_clusters],
        review_flags=[_flag_create(flag) for flag in record.review_flags],
    )


def _micro_event_patch_context(
    record: TimelineCompositionRecord,
    request: TimelinePatchRequest,
    detail: MicroEventExtractionDetailRecord | None,
) -> _MicroEventPatchContext | None:
    if not any(operation.operation == "edit_micro_event_copy" for operation in request.operations):
        return None
    if detail is None:
        raise TimelinePatchInvalid("Source micro-event extraction not found.")
    ordered_candidates = [
        candidate
        for window in sorted(detail.windows, key=lambda item: item.window_index)
        for candidate in sorted(window.micro_events, key=lambda item: item.candidate_index)
    ]
    candidates_by_id = {candidate.id: candidate for candidate in ordered_candidates}
    original_events_by_id = {
        candidate.id: candidate.event for candidate in ordered_candidates
    }
    return _MicroEventPatchContext(
        detail=detail,
        candidates_by_id=candidates_by_id,
        original_events_by_id=original_events_by_id,
        events_by_id=dict(original_events_by_id),
        episode_id_by_candidate_id=_episode_id_by_candidate_id(
            record,
            ordered_candidates,
        ),
    )


def _episode_id_by_candidate_id(
    record: TimelineCompositionRecord,
    ordered_candidates: list[MicroEventCandidateRecord],
) -> dict[int, str]:
    candidate_positions = {
        candidate.id: index for index, candidate in enumerate(ordered_candidates)
    }
    result: dict[int, str] = {}
    for episode in record.episodes:
        start_candidate_id = episode.start_micro_event_candidate_id
        end_candidate_id = episode.end_micro_event_candidate_id
        if start_candidate_id is None or end_candidate_id is None:
            continue
        start_position = candidate_positions.get(start_candidate_id)
        end_position = candidate_positions.get(end_candidate_id)
        if start_position is None or end_position is None or start_position > end_position:
            continue
        for candidate in ordered_candidates[start_position : end_position + 1]:
            result.setdefault(candidate.id, episode.episode_id)
    return result


def _operation_needs_source_micro_events(
    operation: TimelinePatchOperationRequest,
) -> bool:
    return operation.operation == "edit_micro_event_copy" or (
        operation.anchor is not None and operation.anchor.timecode is not None
    )


def _has_timeline_edits(request: TimelinePatchRequest) -> bool:
    return any(operation.operation != "edit_micro_event_copy" for operation in request.operations)


def _edited_micro_event_candidate_ids(context: _MicroEventPatchContext) -> list[int]:
    return [
        candidate_id
        for candidate_id in sorted(context.events_by_id)
        if context.events_by_id[candidate_id] != context.original_events_by_id[candidate_id]
    ]


def _apply_operation(
    state: _PatchState,
    operation: TimelinePatchOperationRequest,
    *,
    episode_time_ranges: dict[str, tuple[int, int]],
    micro_event_context: _MicroEventPatchContext | None,
) -> TimelinePatchOperationResultResponse:
    if operation.operation == "split_block_after_episode":
        return _split_block_after_episode(
            state,
            operation,
            episode_time_ranges=episode_time_ranges,
        )
    if operation.operation == "edit_micro_event_copy":
        return _edit_micro_event_copy(micro_event_context, operation)
    if operation.operation == "edit_topic_cluster_copy":
        return _edit_topic_cluster_copy(state, operation)
    return _edit_display_copy(state, operation)


def _split_block_after_episode(
    state: _PatchState,
    operation: TimelinePatchOperationRequest,
    *,
    episode_time_ranges: dict[str, tuple[int, int]],
) -> TimelinePatchOperationResultResponse:
    anchor_episode = _resolve_anchor_episode(state, operation, episode_time_ranges)
    block_index = _block_index_by_id(state, anchor_episode.parent_block_id)
    block = state.blocks[block_index]
    anchor_position = block.episode_ids.index(anchor_episode.episode_id)
    if anchor_position == len(block.episode_ids) - 1:
        raise TimelinePatchInvalid("Anchor episode is already the last episode in its block.")

    kept_episode_ids = block.episode_ids[: anchor_position + 1]
    moved_episode_ids = block.episode_ids[anchor_position + 1 :]
    moved_episodes = [
        episode for episode in state.episodes if episode.episode_id in set(moved_episode_ids)
    ]
    if not moved_episodes:
        raise TimelinePatchInvalid("No episodes remain after the anchor episode.")

    new_block_id = _next_block_id(state.blocks)
    first_moved = moved_episodes[0]
    new_block_request = operation.new_block
    new_block = TimelineBlockCreate(
        block_id=new_block_id,
        block_index=block.block_index + 1,
        block_type=(
            new_block_request.block_type
            if new_block_request is not None and new_block_request.block_type is not None
            else first_moved.program_mode
        ),
        title=(
            new_block_request.title
            if new_block_request is not None and new_block_request.title is not None
            else first_moved.title
        ),
        summary=(
            new_block_request.summary
            if new_block_request is not None and new_block_request.summary is not None
            else first_moved.summary
        ),
        display_title=(
            new_block_request.display_title
            if new_block_request is not None and new_block_request.display_title is not None
            else first_moved.display_title
        ),
        display_summary=(
            new_block_request.display_summary
            if new_block_request is not None and new_block_request.display_summary is not None
            else first_moved.display_summary
        ),
        episode_ids=list(moved_episode_ids),
    )
    state.blocks[block_index] = replace(block, episode_ids=list(kept_episode_ids))
    state.blocks.insert(block_index + 1, new_block)
    moved_episode_id_set = set(moved_episode_ids)
    state.episodes = [
        replace(episode, parent_block_id=new_block_id)
        if episode.episode_id in moved_episode_id_set
        else episode
        for episode in state.episodes
    ]
    state.blocks = [
        replace(item, block_index=index)
        for index, item in enumerate(state.blocks, start=1)
    ]
    return TimelinePatchOperationResultResponse(
        operation="split_block_after_episode",
        anchorEpisodeId=anchor_episode.episode_id,
        changedBlockIds=[block.block_id, new_block_id],
        changedEpisodeIds=list(moved_episode_ids),
        newBlockId=new_block_id,
        message=f"Split block {block.block_id} after {anchor_episode.episode_id}.",
    )


def _edit_display_copy(
    state: _PatchState,
    operation: TimelinePatchOperationRequest,
) -> TimelinePatchOperationResultResponse:
    target_type = operation.target_type
    if target_type == "video":
        state.display_title = operation.display_title or state.display_title
        state.display_summary = operation.display_summary or state.display_summary
        return TimelinePatchOperationResultResponse(
            operation="edit_display_copy",
            targetType="video",
            message="Edited video display copy.",
        )
    if target_type == "block":
        if operation.target_id is None:
            raise TimelinePatchInvalid("Block display edit requires targetId.")
        index = _block_index_by_id(state, operation.target_id)
        block = state.blocks[index]
        state.blocks[index] = replace(
            block,
            display_title=operation.display_title or block.display_title,
            display_summary=operation.display_summary or block.display_summary,
        )
        return TimelinePatchOperationResultResponse(
            operation="edit_display_copy",
            targetType="block",
            targetId=block.block_id,
            changedBlockIds=[block.block_id],
            message=f"Edited block {block.block_id} display copy.",
        )
    if target_type == "episode":
        if operation.target_id is None:
            raise TimelinePatchInvalid("Episode display edit requires targetId.")
        index = _episode_index_by_id(state, operation.target_id)
        episode = state.episodes[index]
        state.episodes[index] = replace(
            episode,
            display_title=operation.display_title or episode.display_title,
            display_summary=operation.display_summary or episode.display_summary,
        )
        return TimelinePatchOperationResultResponse(
            operation="edit_display_copy",
            targetType="episode",
            targetId=episode.episode_id,
            changedEpisodeIds=[episode.episode_id],
            message=f"Edited episode {episode.episode_id} display copy.",
        )
    raise TimelinePatchInvalid("Unsupported display copy target.")


def _edit_micro_event_copy(
    context: _MicroEventPatchContext | None,
    operation: TimelinePatchOperationRequest,
) -> TimelinePatchOperationResultResponse:
    if context is None:
        raise TimelinePatchInvalid("Source micro-event extraction not found.")
    candidate_id = operation.target_micro_event_candidate_id
    event = operation.event
    if candidate_id is None or event is None:
        raise TimelinePatchInvalid("Micro-event copy edit requires candidate id and event.")
    candidate = context.candidates_by_id.get(candidate_id)
    if candidate is None:
        raise TimelinePatchInvalid(
            f"Micro-event candidate not found in source extraction: {candidate_id}"
        )
    episode_id = context.episode_id_by_candidate_id.get(candidate_id)
    if episode_id is None:
        raise TimelinePatchInvalid(
            f"Micro-event candidate is not covered by timeline episodes: {candidate_id}"
        )
    if operation.expected_episode_id is not None and operation.expected_episode_id != episode_id:
        raise TimelinePatchInvalid(
            f"Micro-event candidate {candidate_id} belongs to {episode_id}, "
            f"not expected episode {operation.expected_episode_id}."
        )
    before = context.events_by_id[candidate.id]
    context.events_by_id[candidate.id] = event
    return TimelinePatchOperationResultResponse(
        operation="edit_micro_event_copy",
        targetMicroEventCandidateId=candidate.id,
        changedMicroEventCandidateIds=[candidate.id],
        beforeEvent=before,
        afterEvent=event,
        message=f"Edited micro-event candidate {candidate.id} event copy.",
    )


def _edit_topic_cluster_copy(
    state: _PatchState,
    operation: TimelinePatchOperationRequest,
) -> TimelinePatchOperationResultResponse:
    topic_id = operation.target_topic_id
    if topic_id is None:
        raise TimelinePatchInvalid("Topic cluster copy edit requires targetTopicId.")
    index = _topic_index_by_id(state, topic_id)
    topic = state.topic_clusters[index]
    state.topic_clusters[index] = replace(
        topic,
        summary=operation.summary or topic.summary,
        display_label=operation.display_label or topic.display_label,
    )
    return TimelinePatchOperationResultResponse(
        operation="edit_topic_cluster_copy",
        targetTopicId=topic.topic_id,
        changedTopicIds=[topic.topic_id],
        message=f"Edited topic cluster {topic.topic_id} copy.",
    )


def _resolve_anchor_episode(
    state: _PatchState,
    operation: TimelinePatchOperationRequest,
    episode_time_ranges: dict[str, tuple[int, int]],
) -> TimelineEpisodeCreate:
    if operation.anchor_episode_id is not None:
        return state.episodes[_episode_index_by_id(state, operation.anchor_episode_id)]
    if operation.anchor is None:
        raise TimelinePatchInvalid("Split operation requires an anchor.")
    matches = state.episodes
    if operation.anchor.timecode is not None:
        target_ms = _parse_timecode_ms(operation.anchor.timecode)
        matches = [
            episode
            for episode in matches
            if _time_range_contains(episode_time_ranges.get(episode.episode_id), target_ms)
        ]
    if operation.anchor.display_title is not None:
        expected = _normalized_text(operation.anchor.display_title)
        matches = [
            episode for episode in matches if _normalized_text(episode.display_title) == expected
        ]
    if operation.anchor.display_summary is not None:
        expected = _normalized_text(operation.anchor.display_summary)
        matches = [
            episode for episode in matches if _normalized_text(episode.display_summary) == expected
        ]
    if len(matches) != 1:
        raise TimelinePatchInvalid(f"Timeline patch anchor matched {len(matches)} episodes.")
    return matches[0]


def _validate_patch_invariants(state: _PatchState) -> None:
    episode_ids = [episode.episode_id for episode in state.episodes]
    if len(set(episode_ids)) != len(episode_ids):
        raise TimelinePatchInvalid("Timeline episodes must have unique episode ids.")
    block_ids = [block.block_id for block in state.blocks]
    if len(set(block_ids)) != len(block_ids):
        raise TimelinePatchInvalid("Timeline blocks must have unique block ids.")
    block_episode_ids = [episode_id for block in state.blocks for episode_id in block.episode_ids]
    if block_episode_ids != episode_ids:
        raise TimelinePatchInvalid("Timeline blocks must contain every episode exactly once.")
    episode_index_by_id = {episode_id: index for index, episode_id in enumerate(episode_ids)}
    for block in state.blocks:
        if not block.episode_ids:
            raise TimelinePatchInvalid("Timeline block cannot be empty.")
        indexes = [episode_index_by_id[episode_id] for episode_id in block.episode_ids]
        if indexes != list(range(indexes[0], indexes[-1] + 1)):
            raise TimelinePatchInvalid(
                f"Timeline block has non-contiguous episodes: {block.block_id}"
            )
        for episode_id in block.episode_ids:
            episode = state.episodes[episode_index_by_id[episode_id]]
            if episode.parent_block_id != block.block_id:
                raise TimelinePatchInvalid(f"Episode parent block mismatch: {episode.episode_id}")


def _composition_create(
    record: TimelineCompositionRecord,
    state: _PatchState,
    *,
    output_json: JsonObject,
) -> TimelineCompositionCreate:
    return TimelineCompositionCreate(
        video_task_id=record.video_task_id,
        video_id=record.video_id,
        source_micro_event_task_id=record.source_micro_event_task_id,
        source_micro_event_fingerprint=record.source_micro_event_fingerprint,
        copy_style=record.copy_style,
        model=record.model,
        reasoning_effort=record.reasoning_effort,
        title=record.title,
        summary=record.summary,
        display_title=state.display_title,
        display_summary=state.display_summary,
        main_topics=record.main_topics,
        output_json=output_json,
        validation_warnings=record.validation_warnings,
        source_job_id=record.source_job_id,
        source_job_attempt_id=record.source_job_attempt_id,
        codex_thread_id=record.codex_thread_id,
        codex_turn_id=record.codex_turn_id,
        raw_response_text=record.raw_response_text,
        blocks=state.blocks,
        episodes=state.episodes,
        topic_clusters=state.topic_clusters,
        review_flags=state.review_flags,
    )


def _patched_output_json(record: TimelineCompositionRecord, state: _PatchState) -> JsonObject:
    output: JsonObject = deepcopy(record.output_json)
    video_summary = cast(JsonObject, dict(_json_object(output.get("video_summary"))))
    video_summary.update(
        {
            "title": record.title,
            "summary": record.summary,
            "display_title": state.display_title,
            "display_summary": state.display_summary,
            "main_topics": record.main_topics,
        }
    )
    output["video_summary"] = video_summary
    output["blocks"] = [
        {
            "block_id": block.block_id,
            "block_type": block.block_type,
            "title": block.title,
            "summary": block.summary,
            "display_title": block.display_title,
            "display_summary": block.display_summary,
            "episode_ids": block.episode_ids,
        }
        for block in state.blocks
    ]
    existing_episode_json = _json_by_id(output.get("episodes"), "episode_id")
    output["episodes"] = [
        _patched_episode_json(episode, existing_episode_json.get(episode.episode_id))
        for episode in state.episodes
    ]
    output["topic_clusters"] = [
        {
            "topic_id": topic.topic_id,
            "label": topic.label,
            "summary": topic.summary,
            "display_label": topic.display_label,
            "episode_ids": topic.episode_ids,
        }
        for topic in state.topic_clusters
    ]
    return output


def _patched_episode_json(
    episode: TimelineEpisodeCreate,
    existing: JsonObject | None,
) -> JsonObject:
    item = dict(existing or {})
    item.update(
        {
            "episode_id": episode.episode_id,
            "parent_block_id": episode.parent_block_id,
            "program_mode": episode.program_mode,
            "primary_content_kind": episode.primary_content_kind,
            "title": episode.title,
            "summary": episode.summary,
            "display_title": episode.display_title,
            "display_summary": episode.display_summary,
            "topics": episode.topics,
            "viewer_tags": episode.viewer_tags,
            "highlight_micro_event_ids": item.get("highlight_micro_event_ids", []),
            "visibility": episode.visibility,
        }
    )
    return item


def _episode_time_ranges(
    record: TimelineCompositionRecord,
    candidate_by_id: dict[int, MicroEventCandidateRecord],
    cue_by_id: dict[str, TranscriptCueRecord],
) -> dict[str, tuple[int, int]]:
    ranges: dict[str, tuple[int, int]] = {}
    for episode in record.episodes:
        start_candidate = candidate_by_id.get(episode.start_micro_event_candidate_id or 0)
        end_candidate = candidate_by_id.get(episode.end_micro_event_candidate_id or 0)
        if start_candidate is None or end_candidate is None:
            continue
        start_cue = cue_by_id.get(start_candidate.start_cue_id)
        end_cue = cue_by_id.get(end_candidate.end_cue_id)
        if start_cue is None or end_cue is None:
            continue
        ranges[episode.episode_id] = (start_cue.start_ms, end_cue.end_ms)
    return ranges


def _diff_response(state: _PatchState) -> TimelinePatchDiffResponse:
    return TimelinePatchDiffResponse(
        blocks=[
            TimelinePatchBlockSummaryResponse(
                blockId=block.block_id,
                blockIndex=block.block_index,
                blockType=block.block_type,
                displayTitle=block.display_title,
                displaySummary=block.display_summary,
                episodeIds=block.episode_ids,
            )
            for block in state.blocks
        ],
        episodes=[
            TimelinePatchEpisodeSummaryResponse(
                episodeId=episode.episode_id,
                episodeIndex=episode.episode_index,
                parentBlockId=episode.parent_block_id,
                displayTitle=episode.display_title,
                displaySummary=episode.display_summary,
            )
            for episode in state.episodes
        ],
        topicClusters=[
            TimelinePatchTopicClusterSummaryResponse(
                topicId=topic.topic_id,
                topicIndex=topic.topic_index,
                displayLabel=topic.display_label,
                summary=topic.summary,
                episodeIds=topic.episode_ids,
            )
            for topic in state.topic_clusters
        ],
    )


def _event_diff(diff: TimelinePatchDiffResponse) -> JsonObject:
    return {
        "blocks": [
            {
                "blockId": block.block_id,
                "episodeIds": block.episode_ids,
                "displayTitle": block.display_title,
            }
            for block in diff.blocks
        ],
        "topicClusters": [
            {
                "topicId": topic.topic_id,
                "displayLabel": topic.display_label,
            }
            for topic in diff.topic_clusters
        ],
    }


def _micro_event_event_updates(
    operation_results: list[TimelinePatchOperationResultResponse],
) -> list[JsonObject]:
    return [
        {
            "candidateId": result.target_micro_event_candidate_id,
            "beforeEvent": result.before_event,
            "afterEvent": result.after_event,
        }
        for result in operation_results
        if result.operation == "edit_micro_event_copy"
        and result.target_micro_event_candidate_id is not None
    ]


def _publish_event_summary(publish_result: JsonObject | None) -> JsonObject | None:
    if publish_result is None:
        return None
    return {
        "publishedCount": publish_result.get("publishedCount"),
        "regeneratedCount": publish_result.get("regeneratedCount"),
        "failedCount": publish_result.get("failedCount"),
        "items": [
            {
                "videoId": item.get("videoId"),
                "status": item.get("status"),
                "reason": item.get("reason"),
                "artifactId": item.get("artifactId"),
                "publicUrl": item.get("publicUrl"),
            }
            for item in cast(list[JsonObject], publish_result.get("items", []))
            if isinstance(item, dict)
        ],
    }


def _publish_response_summary(
    publish_result: JsonObject | None,
) -> TimelinePatchPublishSummaryResponse | None:
    if publish_result is None:
        return None
    item: JsonObject = {}
    items = publish_result.get("items")
    if isinstance(items, list) and items and isinstance(items[0], dict):
        item = cast(JsonObject, items[0])
    return TimelinePatchPublishSummaryResponse(
        requestedCount=_int_or_none(publish_result.get("requestedCount")),
        publishedCount=_int_or_none(publish_result.get("publishedCount")),
        regeneratedCount=_int_or_none(publish_result.get("regeneratedCount")),
        failedCount=_int_or_none(publish_result.get("failedCount")),
        status=_str_or_none(item.get("status")),
        reason=_str_or_none(item.get("reason")),
        videoTaskId=_int_or_none(item.get("videoTaskId")),
        artifactId=_int_or_none(item.get("artifactId")),
        publicUrl=_str_or_none(item.get("publicUrl")),
        errorType=_str_or_none(item.get("errorType")),
        errorMessage=_str_or_none(item.get("errorMessage")),
    )


def _int_or_none(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _str_or_none(value: object) -> str | None:
    if isinstance(value, str):
        return value
    return None


def _block_create(record: TimelineBlockRecord) -> TimelineBlockCreate:
    return TimelineBlockCreate(
        block_id=record.block_id,
        block_index=record.block_index,
        block_type=record.block_type,
        title=record.title,
        summary=record.summary,
        display_title=record.display_title,
        display_summary=record.display_summary,
        episode_ids=list(record.episode_ids),
    )


def _episode_create(record: TimelineEpisodeRecord) -> TimelineEpisodeCreate:
    return TimelineEpisodeCreate(
        episode_id=record.episode_id,
        episode_index=record.episode_index,
        parent_block_id=record.parent_block_id,
        start_micro_event_candidate_id=record.start_micro_event_candidate_id,
        end_micro_event_candidate_id=record.end_micro_event_candidate_id,
        program_mode=record.program_mode,
        primary_content_kind=record.primary_content_kind,
        title=record.title,
        summary=record.summary,
        display_title=record.display_title,
        display_summary=record.display_summary,
        topics=list(record.topics),
        viewer_tags=list(record.viewer_tags),
        highlight_micro_event_candidate_ids=list(record.highlight_micro_event_candidate_ids),
        visibility=record.visibility,
    )


def _topic_create(record: TimelineTopicClusterRecord) -> TimelineTopicClusterCreate:
    return TimelineTopicClusterCreate(
        topic_id=record.topic_id,
        topic_index=record.topic_index,
        label=record.label,
        summary=record.summary,
        display_label=record.display_label,
        episode_ids=list(record.episode_ids),
    )


def _flag_create(record: TimelineReviewFlagRecord) -> TimelineReviewFlagCreate:
    return TimelineReviewFlagCreate(
        flag_index=record.flag_index,
        start_micro_event_candidate_id=record.start_micro_event_candidate_id,
        end_micro_event_candidate_id=record.end_micro_event_candidate_id,
        type=record.type,
        reason=record.reason,
    )


def _block_index_by_id(state: _PatchState, block_id: str) -> int:
    for index, block in enumerate(state.blocks):
        if block.block_id == block_id:
            return index
    raise TimelinePatchInvalid(f"Timeline block not found: {block_id}")


def _episode_index_by_id(state: _PatchState, episode_id: str) -> int:
    for index, episode in enumerate(state.episodes):
        if episode.episode_id == episode_id:
            return index
    raise TimelinePatchInvalid(f"Timeline episode not found: {episode_id}")


def _topic_index_by_id(state: _PatchState, topic_id: str) -> int:
    for index, topic in enumerate(state.topic_clusters):
        if topic.topic_id == topic_id:
            return index
    raise TimelinePatchInvalid(f"Timeline topic cluster not found: {topic_id}")


def _next_block_id(blocks: list[TimelineBlockCreate]) -> str:
    existing = {block.block_id for block in blocks}
    max_numeric_suffix = 0
    for block_id in existing:
        match = re.fullmatch(r"block_(\d+)", block_id)
        if match:
            max_numeric_suffix = max(max_numeric_suffix, int(match.group(1)))
    index = max_numeric_suffix + 1
    while True:
        candidate = f"block_{index:03d}"
        if candidate not in existing:
            return candidate
        index += 1


def _parse_timecode_ms(value: str) -> int:
    parts = value.strip().split(":")
    if not 1 <= len(parts) <= 3:
        raise TimelinePatchInvalid(f"Invalid timecode: {value}")
    try:
        numbers = [int(part) for part in parts]
    except ValueError as exc:
        raise TimelinePatchInvalid(f"Invalid timecode: {value}") from exc
    if len(numbers) == 1:
        hours, minutes, seconds = 0, 0, numbers[0]
    elif len(numbers) == 2:
        hours, minutes, seconds = 0, numbers[0], numbers[1]
    else:
        hours, minutes, seconds = numbers
    if minutes >= 60 or seconds >= 60:
        raise TimelinePatchInvalid(f"Invalid timecode: {value}")
    return ((hours * 60 + minutes) * 60 + seconds) * 1000


def _time_range_contains(time_range: tuple[int, int] | None, target_ms: int) -> bool:
    if time_range is None:
        return False
    start_ms, end_ms = time_range
    return start_ms <= target_ms <= end_ms


def _normalized_text(value: str) -> str:
    return " ".join(value.split())


def _json_object(value: object) -> JsonObject:
    return cast(JsonObject, value) if isinstance(value, dict) else {}


def _json_by_id(value: object, key: str) -> dict[str, JsonObject]:
    if not isinstance(value, list):
        return {}
    result: dict[str, JsonObject] = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        item_id = item.get(key)
        if isinstance(item_id, str):
            result[item_id] = cast(JsonObject, item)
    return result
