from __future__ import annotations

from codex_sdk_cli.domains.llm_traces.ports import (
    LlmTraceRecorderPort,
    NoopLlmTraceRecorder,
)
from codex_sdk_cli.domains.pipeline_jobs.ports import (
    JsonObject,
    PipelineJobAttemptRecord,
    PipelineJobRecord,
)
from codex_sdk_cli.domains.video_tasks.ports import VideoTaskRecord

from .coverage_repair import _repair_episode_coverage
from .episode_repair import _repair_overbroad_episodes
from .invariants import _validate_timeline_invariants
from .models import _ComposerInput, _TimelineRawResponse, _VideoSummaryOutput
from .normalization import _normalize_timeline_style, _normalized_timeline_parts
from .ports import (
    TimelineBlockCreate,
    TimelineComposeResult,
    TimelineComposerPort,
    TimelineCompositionCreate,
    TimelineEpisodeCreate,
    TimelineReviewFlagCreate,
    TimelineTopicClusterCreate,
)
from .semantic_repair import _repair_block_semantics, _soft_verifier_flags
from .serialization import _timeline_output_json
from .task_inputs import _required_str


def _composition_create(
    composer_input: _ComposerInput,
    result: TimelineComposeResult,
    *,
    task: VideoTaskRecord,
    job: PipelineJobRecord,
    attempt: PipelineJobAttemptRecord,
) -> TimelineCompositionCreate:
    output_json, summary, blocks, episodes, topics, flags, warnings = _normalized_timeline_parts(
        composer_input, result
    )
    blocks, episodes = _repair_block_semantics(episodes, blocks, composer_input, warnings)
    flags = _soft_verifier_flags(
        episodes=episodes,
        blocks=blocks,
        composer_input=composer_input,
        existing_flags=flags,
        warnings=warnings,
    )
    summary, blocks, episodes, topics, flags = _normalize_timeline_style(
        summary=summary,
        blocks=blocks,
        episodes=episodes,
        topics=topics,
        flags=flags,
        warnings=warnings,
    )
    _validate_timeline_invariants(episodes, blocks, composer_input)
    output_json = _timeline_output_json(
        summary=summary,
        blocks=blocks,
        episodes=episodes,
        topics=topics,
        flags=flags,
        composer_input=composer_input,
    )
    return _composition_create_from_parts(
        composer_input,
        result,
        output_json=output_json,
        summary=summary,
        blocks=blocks,
        episodes=episodes,
        topics=topics,
        flags=flags,
        warnings=warnings,
        task=task,
        job=job,
        attempt=attempt,
    )


def _empty_composition_create(
    composer_input: _ComposerInput,
    *,
    task: VideoTaskRecord,
    job: PipelineJobRecord,
    attempt: PipelineJobAttemptRecord,
) -> TimelineCompositionCreate:
    message = "분석 가능한 마이크로 이벤트가 없습니다."
    block = TimelineBlockCreate(
        block_id="block_001",
        block_index=1,
        block_type="MIXED",
        title="안내",
        summary=message,
        display_title="안내",
        display_summary=message,
        episode_ids=["episode_001"],
    )
    episode = TimelineEpisodeCreate(
        episode_id="episode_001",
        episode_index=1,
        parent_block_id=block.block_id,
        start_micro_event_candidate_id=None,
        end_micro_event_candidate_id=None,
        program_mode="MIXED",
        primary_content_kind="OTHER",
        title="분석 가능한 이벤트 없음",
        summary=message,
        display_title="분석 가능한 이벤트 없음",
        display_summary=message,
        topics=[],
        viewer_tags=[],
        highlight_micro_event_candidate_ids=[],
        visibility="DEFAULT",
    )
    output_json: JsonObject = {
        "timeline_state": "empty",
        "empty_reason": "no_micro_events",
        "generation_mode": "deterministic_empty",
        "video_summary": {
            "title": composer_input.video.title,
            "summary": message,
            "display_title": composer_input.video.title,
            "display_summary": message,
            "main_topics": [],
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
        ],
        "episodes": [
            {
                "episode_id": episode.episode_id,
                "parent_block_id": episode.parent_block_id,
                "start_micro_event_id": None,
                "end_micro_event_id": None,
                "program_mode": episode.program_mode,
                "primary_content_kind": episode.primary_content_kind,
                "title": episode.title,
                "summary": episode.summary,
                "display_title": episode.display_title,
                "display_summary": episode.display_summary,
                "topics": [],
                "viewer_tags": [],
                "highlight_micro_event_ids": [],
                "visibility": episode.visibility,
            }
        ],
        "topic_clusters": [],
        "review_flags": [],
    }
    return TimelineCompositionCreate(
        video_task_id=task.id,
        video_id=composer_input.video.id,
        source_micro_event_task_id=composer_input.source_task.id,
        source_micro_event_fingerprint=_required_str(
            composer_input.input_json,
            "sourceMicroEventFingerprint",
        ),
        copy_style=composer_input.copy_style,
        model=None,
        reasoning_effort=None,
        title=composer_input.video.title,
        summary=message,
        display_title=composer_input.video.title,
        display_summary=message,
        main_topics=[],
        output_json=output_json,
        validation_warnings=[],
        source_job_id=job.id,
        source_job_attempt_id=attempt.id,
        codex_thread_id=None,
        codex_turn_id=None,
        raw_response_text=None,
        blocks=[block],
        episodes=[episode],
        topic_clusters=[],
        review_flags=[],
    )


async def _composition_create_with_repairs(
    composer_input: _ComposerInput,
    result: TimelineComposeResult,
    *,
    task: VideoTaskRecord,
    job: PipelineJobRecord,
    attempt: PipelineJobAttemptRecord,
    composer: TimelineComposerPort,
    timeout_seconds: int,
    raw_responses: list[_TimelineRawResponse] | None = None,
    llm_traces: LlmTraceRecorderPort | None = None,
) -> TimelineCompositionCreate:
    trace_recorder = llm_traces or NoopLlmTraceRecorder()
    output_json, summary, blocks, episodes, topics, flags, warnings = _normalized_timeline_parts(
        composer_input, result
    )
    episodes, blocks, topics, flags = await _repair_overbroad_episodes(
        episodes=episodes,
        blocks=blocks,
        topics=topics,
        flags=flags,
        composer_input=composer_input,
        task=task,
        job=job,
        attempt=attempt,
        composer=composer,
        timeout_seconds=timeout_seconds,
        warnings=warnings,
        raw_responses=raw_responses,
        llm_traces=trace_recorder,
    )
    episodes, blocks, topics, flags = await _repair_episode_coverage(
        episodes=episodes,
        blocks=blocks,
        topics=topics,
        flags=flags,
        composer_input=composer_input,
        task=task,
        job=job,
        attempt=attempt,
        composer=composer,
        timeout_seconds=timeout_seconds,
        warnings=warnings,
        raw_responses=raw_responses,
        llm_traces=trace_recorder,
    )
    blocks, episodes = _repair_block_semantics(episodes, blocks, composer_input, warnings)
    episodes, blocks, topics, flags = await _repair_episode_coverage(
        episodes=episodes,
        blocks=blocks,
        topics=topics,
        flags=flags,
        composer_input=composer_input,
        task=task,
        job=job,
        attempt=attempt,
        composer=composer,
        timeout_seconds=timeout_seconds,
        warnings=warnings,
        raw_responses=raw_responses,
        llm_traces=trace_recorder,
    )
    blocks, episodes = _repair_block_semantics(episodes, blocks, composer_input, warnings)
    flags = _soft_verifier_flags(
        episodes=episodes,
        blocks=blocks,
        composer_input=composer_input,
        existing_flags=flags,
        warnings=warnings,
    )
    summary, blocks, episodes, topics, flags = _normalize_timeline_style(
        summary=summary,
        blocks=blocks,
        episodes=episodes,
        topics=topics,
        flags=flags,
        warnings=warnings,
    )
    _validate_timeline_invariants(episodes, blocks, composer_input)
    output_json = _timeline_output_json(
        summary=summary,
        blocks=blocks,
        episodes=episodes,
        topics=topics,
        flags=flags,
        composer_input=composer_input,
    )
    return _composition_create_from_parts(
        composer_input,
        result,
        output_json=output_json,
        summary=summary,
        blocks=blocks,
        episodes=episodes,
        topics=topics,
        flags=flags,
        warnings=warnings,
        task=task,
        job=job,
        attempt=attempt,
    )


def _composition_create_from_parts(
    composer_input: _ComposerInput,
    result: TimelineComposeResult,
    *,
    output_json: JsonObject,
    summary: _VideoSummaryOutput,
    blocks: list[TimelineBlockCreate],
    episodes: list[TimelineEpisodeCreate],
    topics: list[TimelineTopicClusterCreate],
    flags: list[TimelineReviewFlagCreate],
    warnings: list[str],
    task: VideoTaskRecord,
    job: PipelineJobRecord,
    attempt: PipelineJobAttemptRecord,
) -> TimelineCompositionCreate:
    return TimelineCompositionCreate(
        video_task_id=task.id,
        video_id=composer_input.video.id,
        source_micro_event_task_id=composer_input.source_task.id,
        source_micro_event_fingerprint=_required_str(
            composer_input.input_json,
            "sourceMicroEventFingerprint",
        ),
        copy_style=composer_input.copy_style,
        model=composer_input.model,
        reasoning_effort=composer_input.reasoning_effort,
        title=summary.title or composer_input.video.title,
        summary=summary.summary,
        display_title=summary.display_title or summary.title or composer_input.video.title,
        display_summary=summary.display_summary or summary.summary,
        main_topics=summary.main_topics,
        output_json=output_json,
        validation_warnings=warnings,
        source_job_id=job.id,
        source_job_attempt_id=attempt.id,
        codex_thread_id=result.thread_id,
        codex_turn_id=result.turn_id,
        raw_response_text=result.final_response,
        blocks=blocks,
        episodes=episodes,
        topic_clusters=topics,
        review_flags=flags,
    )
