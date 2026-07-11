from __future__ import annotations

import asyncio
import json
import time
from typing import cast

from codex_sdk_cli.domains.llm_traces.ports import (
    LlmTraceRecorderPort,
    NoopLlmTraceRecorder,
)
from codex_sdk_cli.domains.micro_events.ports import MicroEventCandidateRecord
from codex_sdk_cli.domains.pipeline_jobs.ports import (
    PipelineJobAttemptRecord,
    PipelineJobRecord,
)
from codex_sdk_cli.domains.video_tasks.ports import VideoTaskRecord

from .constants import TIMELINE_COMPOSE_MAX_COVERAGE_REPAIRS
from .episode_repair import _episode_prompt_json, _parse_episode_repair
from .exceptions import TimelineCompositionOutputInvalid
from .models import (
    _ComposerInput,
    _CoverageRepairPlan,
    _TimelineEpisodeRepairOutput,
    _TimelineRawResponse,
)
from .normalization import (
    _timeline_block_type,
    _timeline_content_kind,
    _timeline_viewer_tags,
    _timeline_visibility,
)
from .policies import (
    _DETERMINISTIC_COVERAGE_REPAIR_CHUNK_SIZE,
    _DETERMINISTIC_COVERAGE_REPAIR_LIMIT,
    _MAX_EPISODE_HIGHLIGHTS,
    _MAX_EPISODE_TOPICS,
    _TIMELINE_BLOCK_TYPES,
    _TIMELINE_CONTENT_KINDS,
    _TIMELINE_VIEWER_TAGS,
    _VIEWER_TAG_CONTENT_KIND_ALIASES,
)
from .ports import (
    TimelineBlockCreate,
    TimelineBlockType,
    TimelineComposerPort,
    TimelineContentKind,
    TimelineEpisodeCreate,
    TimelineEpisodeRepairRequest,
    TimelineReviewFlagCreate,
    TimelineTopicClusterCreate,
    TimelineViewerTag,
)
from .task_inputs import _micro_event_input
from .tracing import _elapsed_ms, _raw_response, _timeline_trace_event
from .transforms import _block_with, _episode_candidate_range, _episode_with


async def _repair_episode_coverage(
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
    repaired_episodes = list(episodes)
    repaired_blocks = list(blocks)
    repaired_topics = list(topics)
    repaired_flags = list(flags)
    for repair_index in range(1, TIMELINE_COMPOSE_MAX_COVERAGE_REPAIRS + 1):
        plan = _coverage_repair_plan(
            repaired_episodes,
            repaired_blocks,
            composer_input,
            repair_index=repair_index,
        )
        if plan is None:
            break
        repair_prompt = _coverage_repair_prompt(
            plan=plan,
            episodes=repaired_episodes,
            blocks=repaired_blocks,
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
                repair_index=repair_index,
                target_episode_id=plan.target_episode.episode_id,
                repair_reason="coverage_repair",
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
                        target_episode_id=plan.target_episode.episode_id,
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
                    repair_index=repair_index,
                    target_episode_id=plan.target_episode.episode_id,
                    repair_reason="coverage_repair",
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
                        target_episode_id=plan.target_episode.episode_id,
                    )
                )
            repair = _parse_episode_repair(result.final_response)
            replacement = _validated_coverage_repair_replacement(
                repair,
                target=plan.target_episode,
                target_candidates=plan.target_candidates,
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
                    repair_index=repair_index,
                    target_episode_id=plan.target_episode.episode_id,
                    repair_reason="coverage_repair",
                    elapsed_ms=_elapsed_ms(started_at),
                    error_type=exc.__class__.__name__,
                    error_message=str(exc) or exc.__class__.__name__,
                )
            )
            warnings.append(
                f"coverage repair {plan.target_episode.episode_id} failed: {exc.__class__.__name__}"
            )
            break
        if replacement is None:
            await trace_recorder.record_event(
                _timeline_trace_event(
                    operation="repair_episode",
                    phase="repair_failed",
                    task=task,
                    job=job,
                    attempt=attempt,
                    composer_input=composer_input,
                    repair_index=repair_index,
                    target_episode_id=plan.target_episode.episode_id,
                    repair_reason="coverage_repair",
                    result=result,
                    elapsed_ms=_elapsed_ms(started_at),
                    error_type="TimelineEpisodeRepairKeptInvalidCoverage",
                    error_message="Coverage repair kept invalid coverage.",
                )
            )
            warnings.append(
                f"coverage repair {plan.target_episode.episode_id} kept invalid coverage"
            )
            break
        repaired_episodes, repaired_blocks, repaired_topics = _apply_coverage_repair(
            episodes=repaired_episodes,
            blocks=repaired_blocks,
            topics=repaired_topics,
            plan=plan,
            replacement=replacement,
        )
        warnings.append(
            f"coverage repair {plan.target_episode.episode_id} inserted "
            f"{len(replacement)} episode(s)"
        )
        await trace_recorder.record_event(
            _timeline_trace_event(
                operation="repair_episode",
                phase="repair_succeeded",
                task=task,
                job=job,
                attempt=attempt,
                composer_input=composer_input,
                repair_index=repair_index,
                target_episode_id=plan.target_episode.episode_id,
                repair_reason="coverage_repair",
                result=result,
                elapsed_ms=_elapsed_ms(started_at),
                metadata={"replacementCount": len(replacement)},
            )
        )
    for fallback_index in range(1, _DETERMINISTIC_COVERAGE_REPAIR_LIMIT + 1):
        plan = _coverage_repair_plan(
            repaired_episodes,
            repaired_blocks,
            composer_input,
            repair_index=TIMELINE_COMPOSE_MAX_COVERAGE_REPAIRS + fallback_index,
        )
        if plan is None:
            break
        replacement = _deterministic_coverage_repair_replacement(
            plan,
            fallback_index=fallback_index,
        )
        repaired_episodes, repaired_blocks, repaired_topics = _apply_coverage_repair(
            episodes=repaired_episodes,
            blocks=repaired_blocks,
            topics=repaired_topics,
            plan=plan,
            replacement=replacement,
        )
        warnings.append(
            f"deterministic coverage repair {plan.target_episode.episode_id} inserted "
            f"{len(replacement)} episode(s)"
        )
    return repaired_episodes, repaired_blocks, repaired_topics, repaired_flags


def _deterministic_coverage_repair_replacement(
    plan: _CoverageRepairPlan,
    *,
    fallback_index: int,
) -> list[TimelineEpisodeCreate]:
    replacement: list[TimelineEpisodeCreate] = []
    for chunk_index, start in enumerate(
        range(0, len(plan.target_candidates), _DETERMINISTIC_COVERAGE_REPAIR_CHUNK_SIZE),
        start=1,
    ):
        candidates = plan.target_candidates[
            start : start + _DETERMINISTIC_COVERAGE_REPAIR_CHUNK_SIZE
        ]
        first_candidate = candidates[0]
        last_candidate = candidates[-1]
        episode_id = (
            plan.target_episode.episode_id
            if chunk_index == 1
            else f"{plan.target_episode.episode_id}_coverage_{fallback_index:03d}_{chunk_index:03d}"
        )
        program_mode = _candidate_timeline_block_type(candidates)
        primary_content_kind = _candidate_timeline_content_kind(candidates)
        title = _deterministic_coverage_title(candidates)
        summary = _deterministic_coverage_summary(candidates)
        replacement.append(
            TimelineEpisodeCreate(
                episode_id=episode_id,
                episode_index=plan.target_episode.episode_index + chunk_index - 1,
                parent_block_id=plan.target_episode.parent_block_id,
                start_micro_event_candidate_id=first_candidate.id,
                end_micro_event_candidate_id=last_candidate.id,
                program_mode=program_mode,
                primary_content_kind=primary_content_kind,
                title=title,
                summary=summary,
                display_title=title,
                display_summary=summary,
                topics=_candidate_topics(candidates),
                viewer_tags=_candidate_viewer_tags(primary_content_kind),
                highlight_micro_event_candidate_ids=[first_candidate.id],
                visibility="DEFAULT",
            )
        )
    return replacement


def _candidate_timeline_block_type(
    candidates: list[MicroEventCandidateRecord],
) -> TimelineBlockType:
    first_candidate = candidates[0]
    program_modes = {candidate.program_mode for candidate in candidates}
    if (
        len(program_modes) == 1
        and first_candidate.program_mode is not None
        and first_candidate.program_mode in _TIMELINE_BLOCK_TYPES
    ):
        return cast(TimelineBlockType, first_candidate.program_mode)
    return "MIXED"


def _candidate_timeline_content_kind(
    candidates: list[MicroEventCandidateRecord],
) -> TimelineContentKind:
    first_candidate = candidates[0]
    content_kinds = {candidate.content_kind for candidate in candidates}
    if (
        len(content_kinds) == 1
        and first_candidate.content_kind is not None
        and first_candidate.content_kind in _TIMELINE_CONTENT_KINDS
    ):
        return cast(TimelineContentKind, first_candidate.content_kind)
    return "OTHER"


def _candidate_topics(candidates: list[MicroEventCandidateRecord]) -> list[str]:
    topics = [
        topic for candidate in candidates for topic in (candidate.topics or []) if topic.strip()
    ]
    return list(dict.fromkeys(topics))[:_MAX_EPISODE_TOPICS]


def _candidate_viewer_tags(
    primary_content_kind: TimelineContentKind,
) -> list[TimelineViewerTag]:
    if primary_content_kind in _TIMELINE_VIEWER_TAGS:
        return [cast(TimelineViewerTag, primary_content_kind)]
    replacement = _VIEWER_TAG_CONTENT_KIND_ALIASES.get(primary_content_kind)
    if replacement is None:
        return []
    return [replacement]


def _deterministic_coverage_title(
    candidates: list[MicroEventCandidateRecord],
) -> str:
    return _short_text(candidates[0].event, max_length=35)


def _deterministic_coverage_summary(
    candidates: list[MicroEventCandidateRecord],
) -> str:
    if len(candidates) == 1:
        return _short_text(candidates[0].event, max_length=120)
    return _short_text(
        f"{candidates[0].event} / {candidates[-1].event}",
        max_length=120,
    )


def _short_text(value: str, *, max_length: int) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= max_length:
        return normalized
    return f"{normalized[: max(0, max_length - 3)].rstrip()}..."


def _coverage_repair_plan(
    episodes: list[TimelineEpisodeCreate],
    blocks: list[TimelineBlockCreate],
    composer_input: _ComposerInput,
    *,
    repair_index: int,
) -> _CoverageRepairPlan | None:
    candidate_ids = [candidate.id for candidate in composer_input.micro_events]
    if not candidate_ids:
        return None
    candidate_by_id = {candidate.id: candidate for candidate in composer_input.micro_events}
    candidate_index_by_id = {
        candidate_id: index for index, candidate_id in enumerate(candidate_ids)
    }
    valid_ranges: list[tuple[int, int, int]] = []
    next_candidate_index = 0
    for episode_index, episode in enumerate(episodes):
        range_info = _episode_candidate_range(
            episode,
            candidate_ids,
            candidate_index_by_id,
            candidate_by_id,
        )
        if range_info is None:
            next_start = _next_valid_episode_start_index(
                episodes,
                episode_index + 1,
                candidate_ids,
                candidate_index_by_id,
                candidate_by_id,
            )
            target_start_index = min(next_candidate_index, len(candidate_ids) - 1)
            target_end_index = (
                len(candidate_ids) - 1
                if next_start is None
                else max(target_start_index, next_start - 1)
            )
            return _coverage_repair_plan_for_range(
                candidate_ids=candidate_ids,
                candidate_by_id=candidate_by_id,
                episodes=episodes,
                blocks=blocks,
                composer_input=composer_input,
                target_start_index=target_start_index,
                target_end_index=target_end_index,
                replace_start_index=episode_index,
                replace_end_index=episode_index + 1,
                repair_index=repair_index,
            )
        _candidates, start_index, end_index = range_info
        if start_index > next_candidate_index:
            return _coverage_repair_plan_for_range(
                candidate_ids=candidate_ids,
                candidate_by_id=candidate_by_id,
                episodes=episodes,
                blocks=blocks,
                composer_input=composer_input,
                target_start_index=next_candidate_index,
                target_end_index=start_index - 1,
                replace_start_index=episode_index,
                replace_end_index=episode_index,
                repair_index=repair_index,
            )
        if start_index < next_candidate_index:
            overlapping_ranges = [item for item in valid_ranges if item[2] >= start_index]
            if overlapping_ranges:
                replace_start_index, target_start_index, previous_end_index = overlapping_ranges[0]
            else:
                replace_start_index = episode_index
                target_start_index = start_index
                previous_end_index = next_candidate_index - 1
            return _coverage_repair_plan_for_range(
                candidate_ids=candidate_ids,
                candidate_by_id=candidate_by_id,
                episodes=episodes,
                blocks=blocks,
                composer_input=composer_input,
                target_start_index=target_start_index,
                target_end_index=max(end_index, previous_end_index),
                replace_start_index=replace_start_index,
                replace_end_index=episode_index + 1,
                repair_index=repair_index,
            )
        next_candidate_index = end_index + 1
        valid_ranges.append((episode_index, start_index, end_index))
    if next_candidate_index < len(candidate_ids):
        return _coverage_repair_plan_for_range(
            candidate_ids=candidate_ids,
            candidate_by_id=candidate_by_id,
            episodes=episodes,
            blocks=blocks,
            composer_input=composer_input,
            target_start_index=next_candidate_index,
            target_end_index=len(candidate_ids) - 1,
            replace_start_index=len(episodes),
            replace_end_index=len(episodes),
            repair_index=repair_index,
        )
    return None


def _coverage_repair_plan_for_range(
    *,
    candidate_ids: list[int],
    candidate_by_id: dict[int, MicroEventCandidateRecord],
    episodes: list[TimelineEpisodeCreate],
    blocks: list[TimelineBlockCreate],
    composer_input: _ComposerInput,
    target_start_index: int,
    target_end_index: int,
    replace_start_index: int,
    replace_end_index: int,
    repair_index: int,
) -> _CoverageRepairPlan:
    target_candidates = [
        candidate_by_id[candidate_id]
        for candidate_id in candidate_ids[target_start_index : target_end_index + 1]
    ]
    parent_block_id = _coverage_repair_parent_block_id(
        episodes,
        blocks,
        replace_start_index=replace_start_index,
    )
    target_episode_id = (
        episodes[replace_start_index].episode_id
        if replace_start_index < replace_end_index
        else _coverage_repair_episode_id(episodes, repair_index)
    )
    first_candidate = target_candidates[0]
    program_modes = {candidate.program_mode for candidate in target_candidates}
    content_kinds = {candidate.content_kind for candidate in target_candidates}
    program_mode = (
        cast(TimelineBlockType, first_candidate.program_mode)
        if len(program_modes) == 1 and first_candidate.program_mode in _TIMELINE_BLOCK_TYPES
        else "MIXED"
    )
    primary_content_kind = (
        cast(TimelineContentKind, first_candidate.content_kind)
        if len(content_kinds) == 1 and first_candidate.content_kind in _TIMELINE_CONTENT_KINDS
        else "OTHER"
    )
    topics = list(
        dict.fromkeys(
            topic for candidate in target_candidates for topic in (candidate.topics or [])
        )
    )[:_MAX_EPISODE_TOPICS]
    return _CoverageRepairPlan(
        target_episode=TimelineEpisodeCreate(
            episode_id=target_episode_id,
            episode_index=replace_start_index + 1,
            parent_block_id=parent_block_id,
            start_micro_event_candidate_id=target_candidates[0].id,
            end_micro_event_candidate_id=target_candidates[-1].id,
            program_mode=program_mode,
            primary_content_kind=primary_content_kind,
            title="Coverage recovery segment",
            summary="Repair this segment so timeline episodes cover each micro-event once.",
            display_title="Coverage recovery segment",
            display_summary=(
                "Repair this segment so timeline episodes cover each micro-event once."
            ),
            topics=topics,
            viewer_tags=[],
            highlight_micro_event_candidate_ids=[target_candidates[0].id],
            visibility="DEFAULT",
        ),
        target_candidates=target_candidates,
        replace_start_index=replace_start_index,
        replace_end_index=replace_end_index,
        insert_before_episode_id=(
            episodes[replace_start_index].episode_id
            if replace_start_index == replace_end_index and replace_start_index < len(episodes)
            else None
        ),
    )


def _next_valid_episode_start_index(
    episodes: list[TimelineEpisodeCreate],
    start_episode_index: int,
    candidate_ids: list[int],
    candidate_index_by_id: dict[int, int],
    candidate_by_id: dict[int, MicroEventCandidateRecord],
) -> int | None:
    for episode in episodes[start_episode_index:]:
        range_info = _episode_candidate_range(
            episode,
            candidate_ids,
            candidate_index_by_id,
            candidate_by_id,
        )
        if range_info is None:
            continue
        _candidates, start_index, _end_index = range_info
        return start_index
    return None


def _coverage_repair_parent_block_id(
    episodes: list[TimelineEpisodeCreate],
    blocks: list[TimelineBlockCreate],
    *,
    replace_start_index: int,
) -> str:
    if replace_start_index < len(episodes):
        return episodes[replace_start_index].parent_block_id
    if episodes:
        return episodes[-1].parent_block_id
    if blocks:
        return blocks[-1].block_id
    return "block_001"


def _coverage_repair_episode_id(
    episodes: list[TimelineEpisodeCreate],
    repair_index: int,
) -> str:
    existing = {episode.episode_id for episode in episodes}
    candidate = f"episode_recovery_{repair_index:03d}"
    while candidate in existing:
        repair_index += 1
        candidate = f"episode_recovery_{repair_index:03d}"
    return candidate


def _coverage_repair_prompt(
    *,
    plan: _CoverageRepairPlan,
    episodes: list[TimelineEpisodeCreate],
    blocks: list[TimelineBlockCreate],
    composer_input: _ComposerInput,
) -> str:
    before = episodes[max(0, plan.replace_start_index - 2) : plan.replace_start_index]
    after = episodes[plan.replace_end_index : min(len(episodes), plan.replace_end_index + 2)]
    input_json = {
        "video_metadata": {
            "video_id": composer_input.video.id,
            "youtube_video_id": composer_input.video.youtube_video_id,
            "title": composer_input.video.title,
            "streamer_name": composer_input.streamer_name,
            "copy_style": composer_input.copy_style,
        },
        "repair_reason": (
            "The current timeline has a micro-event coverage gap, duplicate, "
            "overlap, or invalid episode range. Rewrite only target_micro_events."
        ),
        "target_episode": _episode_prompt_json(plan.target_episode, composer_input),
        "target_micro_events": [
            _micro_event_input(candidate, composer_input, seq=index)
            for index, candidate in enumerate(plan.target_candidates, start=1)
        ],
        "current_episodes_before_target": [
            _episode_prompt_json(episode, composer_input) for episode in before
        ],
        "current_episodes_replaced_by_target": [
            _episode_prompt_json(episode, composer_input)
            for episode in episodes[plan.replace_start_index : plan.replace_end_index]
        ],
        "current_episodes_after_target": [
            _episode_prompt_json(episode, composer_input) for episode in after
        ],
        "blocks": [
            {
                "block_id": block.block_id,
                "block_type": block.block_type,
                "episode_ids": block.episode_ids,
            }
            for block in blocks
        ],
        "output_rules": {
            "target_episode_id": plan.target_episode.episode_id,
            "action": "SPLIT",
            "coverage": (
                "replacement_episodes must cover every target_micro_events item "
                "exactly once, in input order, using only provided micro_event_id values."
            ),
            "single_episode_allowed": True,
        },
    }
    recovery_instructions = """
# COVERAGE_RECOVERY_TASK

Repair only the target_micro_events segment. Return the same JSON shape as the
episode repair task.

- Set action to "SPLIT".
- replacement_episodes may contain one or more episodes.
- The first replacement must start at the first target_micro_events item.
- The final replacement must end at the final target_micro_events item.
- Adjacent replacements must be contiguous with no gap, overlap, duplicate, or reorder.
- Do not invent micro_event_id values.
- Do not include markdown fences or explanatory text.
""".strip()
    return "\n\n".join(
        [
            composer_input.repair_prompt.body,
            recovery_instructions,
            "# INPUT_DATA",
            json.dumps(input_json, ensure_ascii=False),
        ]
    )


def _validated_coverage_repair_replacement(
    repair: _TimelineEpisodeRepairOutput,
    *,
    target: TimelineEpisodeCreate,
    target_candidates: list[MicroEventCandidateRecord],
    composer_input: _ComposerInput,
    warnings: list[str],
) -> list[TimelineEpisodeCreate] | None:
    if repair.target_episode_id and repair.target_episode_id != target.episode_id:
        raise TimelineCompositionOutputInvalid("Coverage repair target_episode_id does not match.")
    action = repair.action.strip().upper()
    if action == "KEEP":
        return None
    if action not in {"SPLIT", "REPLACE"}:
        raise TimelineCompositionOutputInvalid(f"Unknown coverage repair action: {repair.action}")
    if not repair.replacement_episodes:
        return None
    target_ids = [candidate.id for candidate in target_candidates]
    candidate_index_by_id = {candidate_id: index for index, candidate_id in enumerate(target_ids)}
    covered: list[int] = []
    replacement: list[TimelineEpisodeCreate] = []
    for index, episode in enumerate(repair.replacement_episodes, start=1):
        start_id = composer_input.candidate_id_by_synthetic_id.get(episode.start_micro_event_id)
        end_id = composer_input.candidate_id_by_synthetic_id.get(episode.end_micro_event_id)
        if start_id is None or end_id is None:
            raise TimelineCompositionOutputInvalid("Coverage repair episode has invalid range.")
        start_index = candidate_index_by_id.get(start_id)
        end_index = candidate_index_by_id.get(end_id)
        if start_index is None or end_index is None or end_index < start_index:
            raise TimelineCompositionOutputInvalid(
                "Coverage repair episode range is outside target."
            )
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
                    f"coverage repair episode {episode_id} program_mode",
                ),
                primary_content_kind=_timeline_content_kind(
                    episode.primary_content_kind,
                    warnings,
                    f"coverage repair episode {episode_id} primary_content_kind",
                ),
                title=episode.title,
                summary=episode.summary,
                display_title=episode.display_title or episode.title,
                display_summary=episode.display_summary or episode.summary,
                topics=episode.topics[:_MAX_EPISODE_TOPICS],
                viewer_tags=_timeline_viewer_tags(
                    episode.viewer_tags,
                    warnings,
                    f"coverage repair episode {episode_id} viewer_tags",
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
                    f"coverage repair episode {episode_id} visibility",
                ),
            )
        )
    if covered != target_ids:
        raise TimelineCompositionOutputInvalid(
            "Coverage repair replacement does not exactly cover target micro-events."
        )
    return replacement


def _apply_coverage_repair(
    *,
    episodes: list[TimelineEpisodeCreate],
    blocks: list[TimelineBlockCreate],
    topics: list[TimelineTopicClusterCreate],
    plan: _CoverageRepairPlan,
    replacement: list[TimelineEpisodeCreate],
) -> tuple[
    list[TimelineEpisodeCreate],
    list[TimelineBlockCreate],
    list[TimelineTopicClusterCreate],
]:
    removed_episode_ids = [
        episode.episode_id
        for episode in episodes[plan.replace_start_index : plan.replace_end_index]
    ]
    replacement_episode_ids = [episode.episode_id for episode in replacement]
    updated_episodes = [
        *episodes[: plan.replace_start_index],
        *replacement,
        *episodes[plan.replace_end_index :],
    ]
    updated_blocks = _apply_coverage_repair_to_blocks(
        blocks=blocks,
        plan=plan,
        removed_episode_ids=removed_episode_ids,
        replacement_episode_ids=replacement_episode_ids,
    )
    updated_topics = _apply_coverage_repair_to_topics(
        topics,
        removed_episode_ids=removed_episode_ids,
        replacement_episode_ids=replacement_episode_ids,
    )
    return (
        [
            _episode_with(episode, episode_index=index)
            for index, episode in enumerate(updated_episodes, start=1)
        ],
        updated_blocks,
        updated_topics,
    )


def _apply_coverage_repair_to_blocks(
    *,
    blocks: list[TimelineBlockCreate],
    plan: _CoverageRepairPlan,
    removed_episode_ids: list[str],
    replacement_episode_ids: list[str],
) -> list[TimelineBlockCreate]:
    if not blocks:
        return [
            TimelineBlockCreate(
                block_id=plan.target_episode.parent_block_id,
                block_index=1,
                block_type=plan.target_episode.program_mode,
                title=plan.target_episode.title,
                summary=plan.target_episode.summary,
                display_title=plan.target_episode.display_title,
                display_summary=plan.target_episode.display_summary,
                episode_ids=replacement_episode_ids,
            )
        ]
    removed = set(removed_episode_ids)
    first_removed_id = removed_episode_ids[0] if removed_episode_ids else None
    inserted = False
    updated: list[TimelineBlockCreate] = []
    for block in blocks:
        episode_ids: list[str] = []
        for episode_id in block.episode_ids:
            if first_removed_id is not None and episode_id == first_removed_id:
                episode_ids.extend(replacement_episode_ids)
                inserted = True
                continue
            if episode_id in removed:
                continue
            if (
                first_removed_id is None
                and plan.insert_before_episode_id is not None
                and episode_id == plan.insert_before_episode_id
            ):
                episode_ids.extend(replacement_episode_ids)
                inserted = True
            episode_ids.append(episode_id)
        if (
            not inserted
            and first_removed_id is None
            and plan.insert_before_episode_id is None
            and block.block_id == plan.target_episode.parent_block_id
        ):
            episode_ids.extend(replacement_episode_ids)
            inserted = True
        updated.append(_block_with(block, episode_ids=episode_ids))
    if not inserted:
        updated[-1] = _block_with(
            updated[-1],
            episode_ids=[*updated[-1].episode_ids, *replacement_episode_ids],
        )
    return updated


def _apply_coverage_repair_to_topics(
    topics: list[TimelineTopicClusterCreate],
    *,
    removed_episode_ids: list[str],
    replacement_episode_ids: list[str],
) -> list[TimelineTopicClusterCreate]:
    if not removed_episode_ids:
        return topics
    removed = set(removed_episode_ids)
    first_removed_id = removed_episode_ids[0]
    updated: list[TimelineTopicClusterCreate] = []
    for topic in topics:
        episode_ids: list[str] = []
        for episode_id in topic.episode_ids:
            if episode_id == first_removed_id:
                episode_ids.extend(replacement_episode_ids)
                continue
            if episode_id in removed:
                continue
            episode_ids.append(episode_id)
        deduped = list(dict.fromkeys(episode_ids))
        if len(deduped) < 2:
            continue
        updated.append(
            TimelineTopicClusterCreate(
                topic_id=topic.topic_id,
                topic_index=len(updated) + 1,
                label=topic.label,
                summary=topic.summary,
                display_label=topic.display_label,
                episode_ids=deduped,
            )
        )
    return updated
