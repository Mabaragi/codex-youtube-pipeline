from __future__ import annotations

import json
from typing import cast

from pydantic import ValidationError

from codex_sdk_cli.domains.pipeline_jobs.ports import JsonObject

from .exceptions import TimelineCompositionOutputInvalid
from .models import (
    _ComposerInput,
    _TimelineBlockOutput,
    _TimelineEpisodeOutput,
    _TimelineOutput,
    _TimelineReviewFlagOutput,
    _TimelineTopicClusterOutput,
    _VideoSummaryOutput,
)
from .policies import (
    _MAX_EPISODE_HIGHLIGHTS,
    _MAX_EPISODE_TOPICS,
    _TIMELINE_BLOCK_TYPES,
    _TIMELINE_CONTENT_KINDS,
    _TIMELINE_REVIEW_FLAG_TYPES,
    _TIMELINE_VIEWER_TAGS,
    _TIMELINE_VISIBILITIES,
    _VIEWER_TAG_CONTENT_KIND_ALIASES,
)
from .ports import (
    TimelineBlockCreate,
    TimelineBlockType,
    TimelineComposeResult,
    TimelineContentKind,
    TimelineEpisodeCreate,
    TimelineReviewFlagCreate,
    TimelineReviewFlagType,
    TimelineTopicClusterCreate,
    TimelineViewerTag,
    TimelineVisibility,
)
from .style import normalize_timeline_style_text
from .transforms import _episode_with


def _normalized_timeline_parts(
    composer_input: _ComposerInput,
    result: TimelineComposeResult,
) -> tuple[
    JsonObject,
    _VideoSummaryOutput,
    list[TimelineBlockCreate],
    list[TimelineEpisodeCreate],
    list[TimelineTopicClusterCreate],
    list[TimelineReviewFlagCreate],
    list[str],
]:
    final_response = result.final_response
    output_json = _loads_output_json(final_response)
    try:
        parsed = _TimelineOutput.model_validate(output_json)
    except ValidationError as exc:
        raise TimelineCompositionOutputInvalid(str(exc)) from exc
    if not parsed.episodes or not parsed.blocks:
        raise TimelineCompositionOutputInvalid(
            "Timeline output must include at least one episode and one block."
        )
    warnings: list[str] = []
    blocks = _normalized_blocks(parsed.blocks, warnings)
    episodes = _normalized_episodes(parsed.episodes, composer_input, warnings)
    episodes = _sort_episodes_by_range(episodes, composer_input, warnings)
    episode_ids = {episode.episode_id for episode in episodes}
    blocks = _sanitize_block_episode_ids(blocks, episode_ids, warnings)
    topics = _normalized_topics(parsed.topic_clusters, episode_ids, warnings)
    flags = _normalized_flags(parsed.review_flags, composer_input, warnings)
    return output_json, parsed.video_summary, blocks, episodes, topics, flags, warnings


def _normalize_timeline_style(
    *,
    summary: _VideoSummaryOutput,
    blocks: list[TimelineBlockCreate],
    episodes: list[TimelineEpisodeCreate],
    topics: list[TimelineTopicClusterCreate],
    flags: list[TimelineReviewFlagCreate],
    warnings: list[str],
) -> tuple[
    _VideoSummaryOutput,
    list[TimelineBlockCreate],
    list[TimelineEpisodeCreate],
    list[TimelineTopicClusterCreate],
    list[TimelineReviewFlagCreate],
]:
    unresolved: list[str] = []

    def normalize(value: str, path: str) -> str:
        normalized = normalize_timeline_style_text(value)
        if normalized.unresolved_endings:
            unresolved.append(f"{path}: {', '.join(normalized.unresolved_endings)}")
        return normalized.text

    normalized_summary = summary.model_copy(
        update={
            "title": normalize(summary.title, "video_summary.title"),
            "summary": normalize(summary.summary, "video_summary.summary"),
            "display_title": summary.display_title,
            "display_summary": summary.display_summary,
        }
    )
    normalized_blocks = [
        TimelineBlockCreate(
            block_id=block.block_id,
            block_index=block.block_index,
            block_type=block.block_type,
            title=normalize(block.title, f"block {block.block_id} title"),
            summary=normalize(block.summary, f"block {block.block_id} summary"),
            display_title=block.display_title,
            display_summary=block.display_summary,
            episode_ids=block.episode_ids,
        )
        for block in blocks
    ]
    normalized_episodes = [
        TimelineEpisodeCreate(
            episode_id=episode.episode_id,
            episode_index=episode.episode_index,
            parent_block_id=episode.parent_block_id,
            start_micro_event_candidate_id=episode.start_micro_event_candidate_id,
            end_micro_event_candidate_id=episode.end_micro_event_candidate_id,
            program_mode=episode.program_mode,
            primary_content_kind=episode.primary_content_kind,
            title=normalize(episode.title, f"episode {episode.episode_id} title"),
            summary=normalize(episode.summary, f"episode {episode.episode_id} summary"),
            display_title=episode.display_title,
            display_summary=episode.display_summary,
            topics=episode.topics,
            viewer_tags=episode.viewer_tags,
            highlight_micro_event_candidate_ids=episode.highlight_micro_event_candidate_ids,
            visibility=episode.visibility,
        )
        for episode in episodes
    ]
    normalized_topics = [
        TimelineTopicClusterCreate(
            topic_id=topic.topic_id,
            topic_index=topic.topic_index,
            label=normalize(topic.label, f"topic {topic.topic_id} label"),
            summary=normalize(topic.summary, f"topic {topic.topic_id} summary"),
            display_label=normalize(
                topic.display_label,
                f"topic {topic.topic_id} display_label",
            ),
            episode_ids=topic.episode_ids,
        )
        for topic in topics
    ]
    normalized_flags = [
        TimelineReviewFlagCreate(
            flag_index=flag.flag_index,
            start_micro_event_candidate_id=flag.start_micro_event_candidate_id,
            end_micro_event_candidate_id=flag.end_micro_event_candidate_id,
            type=flag.type,
            reason=normalize(flag.reason, f"review_flag {flag.flag_index} reason"),
        )
        for flag in flags
    ]
    warnings.extend(f"timeline style unresolved polite ending: {item}" for item in unresolved)
    return (
        normalized_summary,
        normalized_blocks,
        normalized_episodes,
        normalized_topics,
        normalized_flags,
    )


def _normalized_blocks(
    blocks: list[_TimelineBlockOutput],
    warnings: list[str],
) -> list[TimelineBlockCreate]:
    seen: set[str] = set()
    normalized: list[TimelineBlockCreate] = []
    for index, block in enumerate(blocks, start=1):
        block_id = block.block_id or f"block_{index:03d}"
        if block_id in seen:
            warnings.append(f"duplicate block_id removed: {block_id}")
            continue
        seen.add(block_id)
        normalized.append(
            TimelineBlockCreate(
                block_id=block_id,
                block_index=index,
                block_type=_timeline_block_type(
                    block.block_type,
                    warnings,
                    f"block {block_id} block_type",
                ),
                title=block.title,
                summary=block.summary,
                display_title=block.display_title or block.title,
                display_summary=block.display_summary or block.summary,
                episode_ids=block.episode_ids,
            )
        )
    return normalized


def _normalized_episodes(
    episodes: list[_TimelineEpisodeOutput],
    composer_input: _ComposerInput,
    warnings: list[str],
) -> list[TimelineEpisodeCreate]:
    seen: set[str] = set()
    normalized: list[TimelineEpisodeCreate] = []
    for index, episode in enumerate(episodes, start=1):
        episode_id = episode.episode_id or f"episode_{index:03d}"
        if episode_id in seen:
            warnings.append(f"duplicate episode_id removed: {episode_id}")
            continue
        seen.add(episode_id)
        start_id = composer_input.candidate_id_by_synthetic_id.get(episode.start_micro_event_id)
        end_id = composer_input.candidate_id_by_synthetic_id.get(episode.end_micro_event_id)
        if start_id is None or end_id is None:
            warnings.append(f"episode has invalid micro-event range: {episode_id}")
        if len(episode.highlight_micro_event_ids) > _MAX_EPISODE_HIGHLIGHTS:
            warnings.append(
                f"episode {episode_id} highlight_micro_event_ids truncated "
                f"to {_MAX_EPISODE_HIGHLIGHTS}"
            )
        if len(episode.topics) > _MAX_EPISODE_TOPICS:
            warnings.append(f"episode {episode_id} topics truncated to {_MAX_EPISODE_TOPICS}")
        highlights = [
            candidate_id
            for value in episode.highlight_micro_event_ids[:_MAX_EPISODE_HIGHLIGHTS]
            if (candidate_id := composer_input.candidate_id_by_synthetic_id.get(value)) is not None
        ]
        normalized.append(
            TimelineEpisodeCreate(
                episode_id=episode_id,
                episode_index=len(normalized) + 1,
                parent_block_id=episode.parent_block_id or "block_001",
                start_micro_event_candidate_id=start_id,
                end_micro_event_candidate_id=end_id,
                program_mode=_timeline_block_type(
                    episode.program_mode,
                    warnings,
                    f"episode {episode_id} program_mode",
                ),
                primary_content_kind=_timeline_content_kind(
                    episode.primary_content_kind,
                    warnings,
                    f"episode {episode_id} primary_content_kind",
                ),
                title=episode.title,
                summary=episode.summary,
                display_title=episode.display_title or episode.title,
                display_summary=episode.display_summary or episode.summary,
                topics=episode.topics[:_MAX_EPISODE_TOPICS],
                viewer_tags=_timeline_viewer_tags(
                    episode.viewer_tags,
                    warnings,
                    f"episode {episode_id} viewer_tags",
                ),
                highlight_micro_event_candidate_ids=highlights,
                visibility=_timeline_visibility(
                    episode.visibility,
                    warnings,
                    f"episode {episode_id} visibility",
                ),
            )
        )
    _coverage_warnings(normalized, composer_input, warnings)
    return normalized


def _sanitize_block_episode_ids(
    blocks: list[TimelineBlockCreate],
    episode_ids: set[str],
    warnings: list[str],
) -> list[TimelineBlockCreate]:
    sanitized: list[TimelineBlockCreate] = []
    for block in blocks:
        ids = [episode_id for episode_id in block.episode_ids if episode_id in episode_ids]
        if len(ids) != len(block.episode_ids):
            warnings.append(f"block has invalid episode refs: {block.block_id}")
        sanitized.append(
            TimelineBlockCreate(
                block_id=block.block_id,
                block_index=block.block_index,
                block_type=block.block_type,
                title=block.title,
                summary=block.summary,
                display_title=block.display_title,
                display_summary=block.display_summary,
                episode_ids=ids,
            )
        )
    return sanitized


def _normalized_topics(
    clusters: list[_TimelineTopicClusterOutput],
    episode_ids: set[str],
    warnings: list[str],
) -> list[TimelineTopicClusterCreate]:
    normalized: list[TimelineTopicClusterCreate] = []
    for index, cluster in enumerate(clusters, start=1):
        ids = [episode_id for episode_id in cluster.episode_ids if episode_id in episode_ids]
        if len(ids) < 2:
            warnings.append(f"topic cluster removed because it has fewer than two refs: {index}")
            continue
        topic_id = cluster.topic_id or f"topic_{index:03d}"
        label = cluster.label or cluster.display_label or topic_id
        display_label = cluster.display_label or label
        if not cluster.label:
            warnings.append(f"topic cluster label filled from fallback: {topic_id}")
        normalized.append(
            TimelineTopicClusterCreate(
                topic_id=topic_id,
                topic_index=len(normalized) + 1,
                label=label,
                summary=cluster.summary,
                display_label=display_label,
                episode_ids=ids,
            )
        )
    return normalized


def _normalized_flags(
    flags: list[_TimelineReviewFlagOutput],
    composer_input: _ComposerInput,
    warnings: list[str],
) -> list[TimelineReviewFlagCreate]:
    normalized: list[TimelineReviewFlagCreate] = []
    for flag in flags:
        start_id = composer_input.candidate_id_by_synthetic_id.get(flag.start_micro_event_id)
        end_id = composer_input.candidate_id_by_synthetic_id.get(flag.end_micro_event_id)
        if start_id is None or end_id is None:
            warnings.append("review flag removed because micro-event refs are invalid")
            continue
        normalized.append(
            TimelineReviewFlagCreate(
                flag_index=len(normalized) + 1,
                start_micro_event_candidate_id=start_id,
                end_micro_event_candidate_id=end_id,
                type=_timeline_review_flag_type(
                    flag.type,
                    warnings,
                    "review flag type",
                ),
                reason=flag.reason,
            )
        )
    return normalized


def _sort_episodes_by_range(
    episodes: list[TimelineEpisodeCreate],
    composer_input: _ComposerInput,
    warnings: list[str],
) -> list[TimelineEpisodeCreate]:
    candidate_ids = [candidate.id for candidate in composer_input.micro_events]
    candidate_index_by_id = {
        candidate_id: index for index, candidate_id in enumerate(candidate_ids)
    }

    def key(episode: TimelineEpisodeCreate) -> int:
        if episode.start_micro_event_candidate_id is None:
            return len(candidate_ids)
        return candidate_index_by_id.get(
            episode.start_micro_event_candidate_id,
            len(candidate_ids),
        )

    sorted_episodes = sorted(episodes, key=key)
    if [episode.episode_id for episode in sorted_episodes] != [
        episode.episode_id for episode in episodes
    ]:
        warnings.append("episodes sorted by micro-event range")
    return [
        _episode_with(episode, episode_index=index)
        for index, episode in enumerate(sorted_episodes, start=1)
    ]


def _timeline_block_type(
    value: str,
    warnings: list[str],
    context: str,
) -> TimelineBlockType:
    normalized = value.strip().upper()
    if normalized in _TIMELINE_BLOCK_TYPES:
        return cast(TimelineBlockType, normalized)
    warnings.append(f"{context} had unknown value '{value}', replaced with MIXED")
    return "MIXED"


def _timeline_content_kind(
    value: str,
    warnings: list[str],
    context: str,
) -> TimelineContentKind:
    normalized = value.strip().upper()
    if normalized in _TIMELINE_CONTENT_KINDS:
        return cast(TimelineContentKind, normalized)
    warnings.append(f"{context} had unknown value '{value}', replaced with OTHER")
    return "OTHER"


def _timeline_visibility(
    value: str,
    warnings: list[str],
    context: str,
) -> TimelineVisibility:
    normalized = value.strip().upper()
    if normalized in _TIMELINE_VISIBILITIES:
        return cast(TimelineVisibility, normalized)
    warnings.append(f"{context} had unknown value '{value}', replaced with DEFAULT")
    return "DEFAULT"


def _timeline_viewer_tags(
    values: list[str],
    warnings: list[str],
    context: str,
) -> list[TimelineViewerTag]:
    normalized: list[TimelineViewerTag] = []
    seen: set[str] = set()
    for value in values:
        tag = value.strip().upper()
        if tag not in _TIMELINE_VIEWER_TAGS:
            replacement = _VIEWER_TAG_CONTENT_KIND_ALIASES.get(tag)
            if replacement is None:
                if tag in _VIEWER_TAG_CONTENT_KIND_ALIASES:
                    warnings.append(
                        f"{context} removed content kind value from viewer_tags: {value}"
                    )
                else:
                    warnings.append(f"{context} removed unknown viewer tag: {value}")
                continue
            warnings.append(
                f"{context} mapped content kind value in viewer_tags: {value} -> {replacement}"
            )
            tag = replacement
        if tag in seen:
            warnings.append(f"{context} duplicate viewer tag removed: {tag}")
            continue
        seen.add(tag)
        normalized.append(cast(TimelineViewerTag, tag))
    return normalized


def _timeline_review_flag_type(
    value: str,
    warnings: list[str],
    context: str,
) -> TimelineReviewFlagType:
    normalized = value.strip().upper()
    if normalized == "OVERBROAD_MICRO_EVENT":
        warnings.append(f"{context} migrated OVERBROAD_MICRO_EVENT to OVERBROAD_EPISODE")
        return "OVERBROAD_EPISODE"
    if normalized in _TIMELINE_REVIEW_FLAG_TYPES:
        return cast(TimelineReviewFlagType, normalized)
    warnings.append(f"{context} had unknown value '{value}', replaced with BOUNDARY_AMBIGUOUS")
    return "BOUNDARY_AMBIGUOUS"


def _coverage_warnings(
    episodes: list[TimelineEpisodeCreate],
    composer_input: _ComposerInput,
    warnings: list[str],
) -> None:
    ids = [candidate.id for candidate in composer_input.micro_events]
    covered: list[int] = []
    for episode in episodes:
        if (
            episode.start_micro_event_candidate_id is None
            or episode.end_micro_event_candidate_id is None
        ):
            continue
        try:
            start = ids.index(episode.start_micro_event_candidate_id)
            end = ids.index(episode.end_micro_event_candidate_id)
        except ValueError:
            continue
        if end < start:
            warnings.append(f"episode range is reversed: {episode.episode_id}")
            continue
        covered.extend(ids[start : end + 1])
    missing = sorted(set(ids) - set(covered))
    if missing:
        warnings.append(f"micro-events missing from episodes: {len(missing)}")
    if len(covered) != len(set(covered)):
        warnings.append("micro-events duplicated across episodes")


def _loads_output_json(text: str) -> JsonObject:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.removeprefix("```json").removeprefix("```").strip()
        stripped = stripped.removesuffix("```").strip()
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise TimelineCompositionOutputInvalid("Composer returned invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise TimelineCompositionOutputInvalid("Composer output must be a JSON object.")
    return cast(JsonObject, payload)
