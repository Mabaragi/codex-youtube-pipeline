from __future__ import annotations

from codex_sdk_cli.domains.micro_events.ports import MicroEventCandidateRecord

from .models import _BlockSegment, _ComposerInput
from .ports import (
    TimelineBlockCreate,
    TimelineBlockType,
    TimelineContentKind,
    TimelineEpisodeCreate,
    TimelineVisibility,
)


def _synthetic_candidate_id(
    composer_input: _ComposerInput,
    candidate_id: int | None,
) -> str | None:
    if candidate_id is None:
        return None
    return composer_input.synthetic_id_by_candidate_id.get(candidate_id)


def _segment_with(
    segment: _BlockSegment,
    *,
    block_type: TimelineBlockType | None = None,
    episodes: list[TimelineEpisodeCreate] | None = None,
) -> _BlockSegment:
    return _BlockSegment(
        block_type=block_type or segment.block_type,
        title=segment.title,
        summary=segment.summary,
        display_title=segment.display_title,
        display_summary=segment.display_summary,
        episodes=episodes if episodes is not None else segment.episodes,
    )


def _block_with(
    block: TimelineBlockCreate,
    *,
    episode_ids: list[str],
) -> TimelineBlockCreate:
    return TimelineBlockCreate(
        block_id=block.block_id,
        block_index=block.block_index,
        block_type=block.block_type,
        title=block.title,
        summary=block.summary,
        display_title=block.display_title,
        display_summary=block.display_summary,
        episode_ids=episode_ids,
    )


def _episode_with(
    episode: TimelineEpisodeCreate,
    *,
    episode_index: int | None = None,
    parent_block_id: str | None = None,
    program_mode: TimelineBlockType | None = None,
    primary_content_kind: TimelineContentKind | None = None,
    visibility: TimelineVisibility | None = None,
) -> TimelineEpisodeCreate:
    return TimelineEpisodeCreate(
        episode_id=episode.episode_id,
        episode_index=(episode_index if episode_index is not None else episode.episode_index),
        parent_block_id=parent_block_id or episode.parent_block_id,
        start_micro_event_candidate_id=episode.start_micro_event_candidate_id,
        end_micro_event_candidate_id=episode.end_micro_event_candidate_id,
        program_mode=program_mode or episode.program_mode,
        primary_content_kind=primary_content_kind or episode.primary_content_kind,
        title=episode.title,
        summary=episode.summary,
        display_title=episode.display_title,
        display_summary=episode.display_summary,
        topics=episode.topics,
        viewer_tags=episode.viewer_tags,
        highlight_micro_event_candidate_ids=episode.highlight_micro_event_candidate_ids,
        visibility=visibility or episode.visibility,
    )


def _episode_candidate_range(
    episode: TimelineEpisodeCreate,
    candidate_ids: list[int],
    candidate_index_by_id: dict[int, int],
    candidate_by_id: dict[int, MicroEventCandidateRecord],
) -> tuple[list[MicroEventCandidateRecord], int, int] | None:
    if (
        episode.start_micro_event_candidate_id is None
        or episode.end_micro_event_candidate_id is None
    ):
        return None
    start_index = candidate_index_by_id.get(episode.start_micro_event_candidate_id)
    end_index = candidate_index_by_id.get(episode.end_micro_event_candidate_id)
    if start_index is None or end_index is None or end_index < start_index:
        return None
    candidate_range = [
        candidate_by_id[candidate_id]
        for candidate_id in candidate_ids[start_index : end_index + 1]
        if candidate_id in candidate_by_id
    ]
    return candidate_range, start_index, end_index
