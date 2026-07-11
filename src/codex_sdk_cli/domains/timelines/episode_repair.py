from __future__ import annotations

import asyncio
import json
import time

from pydantic import ValidationError

from codex_sdk_cli.domains.llm_traces.ports import (
    LlmTraceRecorderPort,
    NoopLlmTraceRecorder,
)
from codex_sdk_cli.domains.micro_events.ports import MicroEventCandidateRecord
from codex_sdk_cli.domains.pipeline_jobs.ports import (
    JsonObject,
    PipelineJobAttemptRecord,
    PipelineJobRecord,
)
from codex_sdk_cli.domains.video_tasks.ports import VideoTaskRecord

from .constants import TIMELINE_COMPOSE_MAX_EPISODE_REPAIRS
from .exceptions import TimelineCompositionOutputInvalid
from .models import _ComposerInput, _TimelineEpisodeRepairOutput, _TimelineRawResponse
from .normalization import (
    _loads_output_json,
    _timeline_block_type,
    _timeline_content_kind,
    _timeline_viewer_tags,
    _timeline_visibility,
)
from .policies import _MAX_EPISODE_HIGHLIGHTS, _MAX_EPISODE_TOPICS
from .ports import (
    TimelineBlockCreate,
    TimelineComposerPort,
    TimelineEpisodeCreate,
    TimelineEpisodeRepairRequest,
    TimelineReviewFlagCreate,
    TimelineTopicClusterCreate,
)
from .semantic_repair import _append_review_flag, _is_overbroad_episode
from .task_inputs import _micro_event_input
from .tracing import _elapsed_ms, _raw_response, _timeline_trace_event
from .transforms import (
    _block_with,
    _episode_candidate_range,
    _episode_with,
    _synthetic_candidate_id,
)


async def _repair_overbroad_episodes(
    *,
    episodes: list[TimelineEpisodeCreate],
    blocks: list[TimelineBlockCreate],
    topics: list[TimelineTopicClusterCreate],
    flags: list[TimelineReviewFlagCreate],
    composer_input: _ComposerInput,
    task: VideoTaskRecord,
    job: PipelineJobRecord,
    attempt: PipelineJobAttemptRecord,
    composer: TimelineComposerPort,
    timeout_seconds: int,
    warnings: list[str],
    raw_responses: list[_TimelineRawResponse] | None = None,
    llm_traces: LlmTraceRecorderPort | None = None,
) -> tuple[
    list[TimelineEpisodeCreate],
    list[TimelineBlockCreate],
    list[TimelineTopicClusterCreate],
    list[TimelineReviewFlagCreate],
]:
    candidate_by_id = {candidate.id: candidate for candidate in composer_input.micro_events}
    candidate_ids = [candidate.id for candidate in composer_input.micro_events]
    candidate_index_by_id = {
        candidate_id: index for index, candidate_id in enumerate(candidate_ids)
    }
    repaired_episodes = list(episodes)
    repaired_blocks = list(blocks)
    repaired_topics = list(topics)
    repaired_flags = list(flags)
    repairs_attempted = 0
    for episode in episodes:
        if repairs_attempted >= TIMELINE_COMPOSE_MAX_EPISODE_REPAIRS:
            break
        range_info = _episode_candidate_range(
            episode,
            candidate_ids,
            candidate_index_by_id,
            candidate_by_id,
        )
        if range_info is None:
            continue
        candidates, _start_index, _end_index = range_info
        if not _is_overbroad_episode(episode, candidates):
            continue
        repairs_attempted += 1
        repair_prompt = _episode_repair_prompt(
            episode=episode,
            episodes=repaired_episodes,
            blocks=repaired_blocks,
            candidates=candidates,
            composer_input=composer_input,
        )
        trace_recorder = llm_traces or NoopLlmTraceRecorder()
        await trace_recorder.record_event(
            _timeline_trace_event(
                operation="repair_episode",
                phase="repair_requested",
                task=task,
                job=job,
                attempt=attempt,
                composer_input=composer_input,
                repair_index=repairs_attempted,
                target_episode_id=episode.episode_id,
                repair_reason="overbroad_episode",
                prompt_text=repair_prompt,
            )
        )
        started_at = time.monotonic()
        try:
            result = await asyncio.wait_for(
                composer.repair_episode(
                    TimelineEpisodeRepairRequest(
                        prompt=repair_prompt,
                        video_id=composer_input.video.id,
                        video_task_id=task.id,
                        job_id=job.id,
                        job_attempt_id=attempt.id,
                        source_micro_event_task_id=composer_input.source_task.id,
                        target_episode_id=episode.episode_id,
                        model=composer_input.model,
                        reasoning_effort=composer_input.reasoning_effort,
                    )
                ),
                timeout=timeout_seconds,
            )
            await trace_recorder.record_event(
                _timeline_trace_event(
                    operation="repair_episode",
                    phase="repair_response_received",
                    task=task,
                    job=job,
                    attempt=attempt,
                    composer_input=composer_input,
                    repair_index=repairs_attempted,
                    target_episode_id=episode.episode_id,
                    repair_reason="overbroad_episode",
                    result=result,
                    elapsed_ms=_elapsed_ms(started_at),
                    raw_response_text=result.final_response,
                )
            )
            if raw_responses is not None:
                raw_responses.append(
                    _raw_response(
                        "repair_episode",
                        result,
                        target_episode_id=episode.episode_id,
                    )
                )
            repair = _parse_episode_repair(result.final_response)
            replacement = _validated_repair_replacement(
                repair,
                target=episode,
                target_candidates=candidates,
                composer_input=composer_input,
                warnings=warnings,
            )
        except Exception as exc:
            await trace_recorder.record_event(
                _timeline_trace_event(
                    operation="repair_episode",
                    phase="repair_failed",
                    task=task,
                    job=job,
                    attempt=attempt,
                    composer_input=composer_input,
                    repair_index=repairs_attempted,
                    target_episode_id=episode.episode_id,
                    repair_reason="overbroad_episode",
                    elapsed_ms=_elapsed_ms(started_at),
                    error_type=exc.__class__.__name__,
                    error_message=str(exc) or exc.__class__.__name__,
                )
            )
            warnings.append(f"episode {episode.episode_id} repair failed: {exc.__class__.__name__}")
            repaired_flags = _append_review_flag(
                repaired_flags,
                start_id=episode.start_micro_event_candidate_id,
                end_id=episode.end_micro_event_candidate_id,
                flag_type="OVERBROAD_EPISODE",
                reason="Overbroad episode repair failed; original episode was kept.",
            )
            continue
        if replacement is None:
            await trace_recorder.record_event(
                _timeline_trace_event(
                    operation="repair_episode",
                    phase="repair_failed",
                    task=task,
                    job=job,
                    attempt=attempt,
                    composer_input=composer_input,
                    repair_index=repairs_attempted,
                    target_episode_id=episode.episode_id,
                    repair_reason="overbroad_episode",
                    result=result,
                    elapsed_ms=_elapsed_ms(started_at),
                    error_type="TimelineEpisodeRepairKeptOriginal",
                    error_message="Episode repair kept original episode.",
                )
            )
            warnings.append(f"episode {episode.episode_id} repair kept original episode")
            repaired_flags = _append_review_flag(
                repaired_flags,
                start_id=episode.start_micro_event_candidate_id,
                end_id=episode.end_micro_event_candidate_id,
                flag_type="OVERBROAD_EPISODE",
                reason="Episode still appears broad after repair KEEP decision.",
            )
            continue
        replacement_ids = [item.episode_id for item in replacement]
        repaired_episodes = _replace_episode(repaired_episodes, episode.episode_id, replacement)
        repaired_blocks = _replace_block_episode_refs(
            repaired_blocks,
            old_episode_id=episode.episode_id,
            new_episode_ids=replacement_ids,
        )
        repaired_topics = _replace_topic_episode_refs(
            repaired_topics,
            old_episode_id=episode.episode_id,
            new_episode_ids=replacement_ids,
        )
        await trace_recorder.record_event(
            _timeline_trace_event(
                operation="repair_episode",
                phase="repair_succeeded",
                task=task,
                job=job,
                attempt=attempt,
                composer_input=composer_input,
                repair_index=repairs_attempted,
                target_episode_id=episode.episode_id,
                repair_reason="overbroad_episode",
                result=result,
                elapsed_ms=_elapsed_ms(started_at),
                metadata={"replacementCount": len(replacement)},
            )
        )
        warnings.append(f"episode {episode.episode_id} repaired into {len(replacement)} episode(s)")
    return repaired_episodes, repaired_blocks, repaired_topics, repaired_flags


def _episode_repair_prompt(
    *,
    episode: TimelineEpisodeCreate,
    episodes: list[TimelineEpisodeCreate],
    blocks: list[TimelineBlockCreate],
    candidates: list[MicroEventCandidateRecord],
    composer_input: _ComposerInput,
) -> str:
    episode_index = next(
        (index for index, item in enumerate(episodes) if item.episode_id == episode.episode_id),
        -1,
    )
    previous_episode = episodes[episode_index - 1] if episode_index > 0 else None
    next_episode = episodes[episode_index + 1] if 0 <= episode_index < len(episodes) - 1 else None
    parent_block = next(
        (block for block in blocks if episode.episode_id in block.episode_ids),
        None,
    )
    input_json = {
        "video_metadata": {
            "video_id": composer_input.video.id,
            "youtube_video_id": composer_input.video.youtube_video_id,
            "title": composer_input.video.title,
            "streamer_name": composer_input.streamer_name,
            "copy_style": composer_input.copy_style,
        },
        "target_episode": _episode_prompt_json(episode, composer_input),
        "target_micro_events": [
            _micro_event_input(candidate, composer_input, seq=index)
            for index, candidate in enumerate(candidates, start=1)
        ],
        "previous_episode": (
            _episode_prompt_json(previous_episode, composer_input)
            if previous_episode is not None
            else None
        ),
        "next_episode": (
            _episode_prompt_json(next_episode, composer_input) if next_episode is not None else None
        ),
        "parent_block": (
            {
                "block_id": parent_block.block_id,
                "block_type": parent_block.block_type,
                "title": parent_block.title,
                "summary": parent_block.summary,
            }
            if parent_block is not None
            else None
        ),
    }
    return "\n\n".join(
        [
            composer_input.repair_prompt.body,
            "# INPUT_DATA",
            json.dumps(input_json, ensure_ascii=False),
        ]
    )


def _parse_episode_repair(text: str) -> _TimelineEpisodeRepairOutput:
    payload = _normalized_episode_repair_payload(_loads_output_json(text))
    try:
        return _TimelineEpisodeRepairOutput.model_validate(payload)
    except ValidationError as exc:
        raise TimelineCompositionOutputInvalid(str(exc)) from exc


def _normalized_episode_repair_payload(payload: JsonObject) -> JsonObject:
    if "replacement_episodes" in payload or "episodes" not in payload:
        return payload
    episodes = payload["episodes"]
    if not isinstance(episodes, list):
        return payload
    return {
        **payload,
        "action": payload.get("action") or "SPLIT",
        "target_episode_id": payload.get("target_episode_id") or "",
        "replacement_episodes": episodes,
    }


def _validated_repair_replacement(
    repair: _TimelineEpisodeRepairOutput,
    *,
    target: TimelineEpisodeCreate,
    target_candidates: list[MicroEventCandidateRecord],
    composer_input: _ComposerInput,
    warnings: list[str],
) -> list[TimelineEpisodeCreate] | None:
    if repair.target_episode_id and repair.target_episode_id != target.episode_id:
        raise TimelineCompositionOutputInvalid("Repair target_episode_id does not match.")
    action = repair.action.strip().upper()
    if action == "KEEP":
        return None
    if action != "SPLIT":
        raise TimelineCompositionOutputInvalid(f"Unknown repair action: {repair.action}")
    if len(repair.replacement_episodes) < 2:
        return None
    target_ids = [candidate.id for candidate in target_candidates]
    candidate_index_by_id = {candidate_id: index for index, candidate_id in enumerate(target_ids)}
    covered: list[int] = []
    replacement: list[TimelineEpisodeCreate] = []
    for index, episode in enumerate(repair.replacement_episodes, start=1):
        start_id = composer_input.candidate_id_by_synthetic_id.get(episode.start_micro_event_id)
        end_id = composer_input.candidate_id_by_synthetic_id.get(episode.end_micro_event_id)
        if start_id is None or end_id is None:
            raise TimelineCompositionOutputInvalid("Repair episode has invalid range.")
        start_index = candidate_index_by_id.get(start_id)
        end_index = candidate_index_by_id.get(end_id)
        if start_index is None or end_index is None or end_index < start_index:
            raise TimelineCompositionOutputInvalid("Repair episode range is outside target.")
        covered.extend(target_ids[start_index : end_index + 1])
        episode_id = target.episode_id if index == 1 else f"{target.episode_id}_split_{index:03d}"
        replacement.append(
            TimelineEpisodeCreate(
                episode_id=episode_id,
                episode_index=target.episode_index + index - 1,
                parent_block_id=target.parent_block_id,
                start_micro_event_candidate_id=start_id,
                end_micro_event_candidate_id=end_id,
                program_mode=_timeline_block_type(
                    episode.program_mode,
                    warnings,
                    f"repair episode {episode_id} program_mode",
                ),
                primary_content_kind=_timeline_content_kind(
                    episode.primary_content_kind,
                    warnings,
                    f"repair episode {episode_id} primary_content_kind",
                ),
                title=episode.title,
                summary=episode.summary,
                display_title=episode.display_title or episode.title,
                display_summary=episode.display_summary or episode.summary,
                topics=episode.topics[:_MAX_EPISODE_TOPICS],
                viewer_tags=_timeline_viewer_tags(
                    episode.viewer_tags,
                    warnings,
                    f"repair episode {episode_id} viewer_tags",
                ),
                highlight_micro_event_candidate_ids=[
                    candidate_id
                    for value in episode.highlight_micro_event_ids[:_MAX_EPISODE_HIGHLIGHTS]
                    if (candidate_id := composer_input.candidate_id_by_synthetic_id.get(value))
                    is not None
                ],
                visibility=_timeline_visibility(
                    episode.visibility,
                    warnings,
                    f"repair episode {episode_id} visibility",
                ),
            )
        )
    if covered != target_ids:
        raise TimelineCompositionOutputInvalid(
            "Repair replacement does not exactly cover target micro-events."
        )
    return replacement


def _replace_episode(
    episodes: list[TimelineEpisodeCreate],
    old_episode_id: str,
    replacement: list[TimelineEpisodeCreate],
) -> list[TimelineEpisodeCreate]:
    updated: list[TimelineEpisodeCreate] = []
    for episode in episodes:
        if episode.episode_id == old_episode_id:
            updated.extend(replacement)
        else:
            updated.append(episode)
    return [
        _episode_with(episode, episode_index=index)
        for index, episode in enumerate(updated, start=1)
    ]


def _replace_block_episode_refs(
    blocks: list[TimelineBlockCreate],
    *,
    old_episode_id: str,
    new_episode_ids: list[str],
) -> list[TimelineBlockCreate]:
    updated: list[TimelineBlockCreate] = []
    for block in blocks:
        episode_ids: list[str] = []
        for episode_id in block.episode_ids:
            if episode_id == old_episode_id:
                episode_ids.extend(new_episode_ids)
            else:
                episode_ids.append(episode_id)
        updated.append(_block_with(block, episode_ids=episode_ids))
    return updated


def _replace_topic_episode_refs(
    topics: list[TimelineTopicClusterCreate],
    *,
    old_episode_id: str,
    new_episode_ids: list[str],
) -> list[TimelineTopicClusterCreate]:
    updated: list[TimelineTopicClusterCreate] = []
    for topic in topics:
        episode_ids: list[str] = []
        for episode_id in topic.episode_ids:
            if episode_id == old_episode_id:
                episode_ids.extend(new_episode_ids)
            else:
                episode_ids.append(episode_id)
        updated.append(
            TimelineTopicClusterCreate(
                topic_id=topic.topic_id,
                topic_index=topic.topic_index,
                label=topic.label,
                summary=topic.summary,
                display_label=topic.display_label,
                episode_ids=list(dict.fromkeys(episode_ids)),
            )
        )
    return updated


def _episode_prompt_json(
    episode: TimelineEpisodeCreate,
    composer_input: _ComposerInput,
) -> JsonObject:
    return {
        "episode_id": episode.episode_id,
        "start_micro_event_id": _synthetic_candidate_id(
            composer_input,
            episode.start_micro_event_candidate_id,
        ),
        "end_micro_event_id": _synthetic_candidate_id(
            composer_input,
            episode.end_micro_event_candidate_id,
        ),
        "program_mode": episode.program_mode,
        "primary_content_kind": episode.primary_content_kind,
        "title": episode.title,
        "summary": episode.summary,
        "display_title": episode.display_title,
        "display_summary": episode.display_summary,
        "topics": episode.topics,
        "viewer_tags": episode.viewer_tags,
        "visibility": episode.visibility,
    }
