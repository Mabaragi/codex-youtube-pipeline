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
