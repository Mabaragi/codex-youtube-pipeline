from __future__ import annotations

from codex_sdk_cli.domains.micro_events.ports import MicroEventCandidateRecord

from .models import _BlockSegment, _ComposerInput
from .policies import (
    _CLOSING_TERMS,
    _GAME_RELATED_CONTENT_KINDS,
    _MAX_EPISODE_TOPICS,
    _OVERBROAD_LARGE_MICRO_EVENT_COUNT,
    _OVERBROAD_MICRO_EVENT_COUNT,
    _POST_GAME_DAILY_CONTENT_KINDS,
    _SHORT_BREAK_EPISODE_COUNT,
)
from .ports import (
    TimelineBlockCreate,
    TimelineEpisodeCreate,
    TimelineReviewFlagCreate,
    TimelineReviewFlagType,
)
from .transforms import _episode_candidate_range, _episode_with, _segment_with


def _repair_block_semantics(
    episodes: list[TimelineEpisodeCreate],
    blocks: list[TimelineBlockCreate],
    composer_input: _ComposerInput,
    warnings: list[str],
) -> tuple[list[TimelineBlockCreate], list[TimelineEpisodeCreate]]:
    segments = _block_semantic_segments(episodes, blocks, warnings)
    segments = _merge_short_break_segments(segments, warnings)
    segments = _split_post_game_segments(segments, warnings)
    segments = _split_closing_segments(segments, warnings)
    segments = _merge_adjacent_same_type_segments(segments)
    repaired_blocks: list[TimelineBlockCreate] = []
    repaired_episodes: list[TimelineEpisodeCreate] = []
    for block_index, segment in enumerate(segments, start=1):
        block_id = f"block_{block_index:03d}"
        segment_episodes = [
            _episode_with(
                episode,
                episode_index=len(repaired_episodes) + offset,
                parent_block_id=block_id,
            )
            for offset, episode in enumerate(segment.episodes, start=1)
        ]
        repaired_episodes.extend(segment_episodes)
        repaired_blocks.append(
            TimelineBlockCreate(
                block_id=block_id,
                block_index=block_index,
                block_type=segment.block_type,
                title=segment.title,
                summary=segment.summary,
                display_title=segment.display_title,
                display_summary=segment.display_summary,
                episode_ids=[episode.episode_id for episode in segment_episodes],
            )
        )
    return repaired_blocks, repaired_episodes


def _block_semantic_segments(
    episodes: list[TimelineEpisodeCreate],
    blocks: list[TimelineBlockCreate],
    warnings: list[str],
) -> list[_BlockSegment]:
    block_by_id = {block.block_id: block for block in blocks}
    episode_ids = {episode.episode_id for episode in episodes}
    block_episode_ids = [
        episode_id
        for block in blocks
        for episode_id in block.episode_ids
        if episode_id in episode_ids
    ]
    if block_episode_ids != [episode.episode_id for episode in episodes]:
        warnings.append("block semantic repair rebuilt block refs from episode order")

    block_id_by_episode_id: dict[str, str] = {}
    for block in blocks:
        for episode_id in block.episode_ids:
            if episode_id in episode_ids and episode_id not in block_id_by_episode_id:
                block_id_by_episode_id[episode_id] = block.block_id

    keyed_segments: list[tuple[str, _BlockSegment]] = []
    for episode in episodes:
        block = block_by_id.get(block_id_by_episode_id.get(episode.episode_id, ""))
        if block is None:
            block = block_by_id.get(episode.parent_block_id)
        segment_key = block.block_id if block is not None else episode.episode_id
        segment = (
            _BlockSegment(
                block_type=block.block_type,
                title=block.title,
                summary=block.summary,
                display_title=block.display_title,
                display_summary=block.display_summary,
                episodes=[episode],
            )
            if block is not None
            else _BlockSegment(
                block_type=episode.program_mode,
                title=episode.title,
                summary=episode.summary,
                display_title=episode.display_title,
                display_summary=episode.display_summary,
                episodes=[episode],
            )
        )
        if keyed_segments and keyed_segments[-1][0] == segment_key:
            previous_key, previous_segment = keyed_segments[-1]
            keyed_segments[-1] = (
                previous_key,
                _segment_with(
                    previous_segment,
                    episodes=[*previous_segment.episodes, episode],
                ),
            )
            continue
        keyed_segments.append((segment_key, segment))
    return [segment for _key, segment in keyed_segments]


def _soft_verifier_flags(
    *,
    episodes: list[TimelineEpisodeCreate],
    blocks: list[TimelineBlockCreate],
    composer_input: _ComposerInput,
    existing_flags: list[TimelineReviewFlagCreate],
    warnings: list[str],
) -> list[TimelineReviewFlagCreate]:
    normalized = list(existing_flags)
    existing_keys = {
        (flag.start_micro_event_candidate_id, flag.end_micro_event_candidate_id, flag.type)
        for flag in normalized
    }
    episode_by_id = {episode.episode_id: episode for episode in episodes}
    candidate_by_id = {candidate.id: candidate for candidate in composer_input.micro_events}
    candidate_ids = [candidate.id for candidate in composer_input.micro_events]
    candidate_index_by_id = {
        candidate_id: index for index, candidate_id in enumerate(candidate_ids)
    }

    def append_flag(
        *,
        start_id: int | None,
        end_id: int | None,
        flag_type: TimelineReviewFlagType,
        reason: str,
    ) -> None:
        if start_id is None or end_id is None:
            return
        key = (start_id, end_id, flag_type)
        if key in existing_keys:
            return
        existing_keys.add(key)
        normalized.append(
            TimelineReviewFlagCreate(
                flag_index=len(normalized) + 1,
                start_micro_event_candidate_id=start_id,
                end_micro_event_candidate_id=end_id,
                type=flag_type,
                reason=reason,
            )
        )

    mixed_count = sum(1 for block in blocks if block.block_type == "MIXED")
    if len(blocks) >= 4 and mixed_count / len(blocks) >= 0.3:
        warnings.append(f"timeline has many MIXED blocks: {mixed_count}/{len(blocks)}")

    for episode in episodes:
        range_info = _episode_candidate_range(
            episode,
            candidate_ids,
            candidate_index_by_id,
            candidate_by_id,
        )
        if range_info is None:
            continue
        candidates, start_index, _end_index = range_info
        if _is_overbroad_episode(episode, candidates):
            append_flag(
                start_id=episode.start_micro_event_candidate_id,
                end_id=episode.end_micro_event_candidate_id,
                flag_type="OVERBROAD_EPISODE",
                reason=(
                    "Episode spans many micro-events with mixed subjects; "
                    "consider splitting if separate user-searchable topics are present."
                ),
            )
        if _is_late_broadcast_start_risk(
            episode,
            candidates,
            start_index=start_index,
            total_count=len(candidate_ids),
        ):
            append_flag(
                start_id=episode.start_micro_event_candidate_id,
                end_id=episode.end_micro_event_candidate_id,
                flag_type="ASR_SEMANTIC_RISK",
                reason=(
                    "Late-stream wording mentions starting or scheduling a broadcast; "
                    "verify whether this is an ASR confusion with ending the broadcast."
                ),
            )

    for index, block in enumerate(blocks):
        if (
            block.block_type != "BREAK"
            or len(block.episode_ids) > _SHORT_BREAK_EPISODE_COUNT
            or index == 0
            or index == len(blocks) - 1
        ):
            continue
        block_episodes = [
            episode
            for episode_id in block.episode_ids
            if (episode := episode_by_id.get(episode_id)) is not None
        ]
        if not block_episodes:
            continue
        append_flag(
            start_id=block_episodes[0].start_micro_event_candidate_id,
            end_id=block_episodes[-1].end_micro_event_candidate_id,
            flag_type="BOUNDARY_AMBIGUOUS",
            reason=(
                "Short BREAK appears as a separate top-level block; "
                "consider keeping it as a collapsed episode inside the neighboring flow."
            ),
        )
    return normalized


def _is_overbroad_episode(
    episode: TimelineEpisodeCreate,
    candidates: list[MicroEventCandidateRecord],
) -> bool:
    program_modes = {candidate.program_mode for candidate in candidates if candidate.program_mode}
    content_kinds = {candidate.content_kind for candidate in candidates if candidate.content_kind}
    return (
        len(candidates) >= _OVERBROAD_MICRO_EVENT_COUNT
        and (
            len(episode.topics) >= _MAX_EPISODE_TOPICS
            or len(program_modes) >= 3
            or len(content_kinds) >= 3
        )
    ) or (len(candidates) >= _OVERBROAD_LARGE_MICRO_EVENT_COUNT and len(content_kinds) >= 2)


def _append_review_flag(
    flags: list[TimelineReviewFlagCreate],
    *,
    start_id: int | None,
    end_id: int | None,
    flag_type: TimelineReviewFlagType,
    reason: str,
) -> list[TimelineReviewFlagCreate]:
    if start_id is None or end_id is None:
        return flags
    key = (start_id, end_id, flag_type)
    existing = {
        (
            flag.start_micro_event_candidate_id,
            flag.end_micro_event_candidate_id,
            flag.type,
        )
        for flag in flags
    }
    if key in existing:
        return flags
    return [
        *flags,
        TimelineReviewFlagCreate(
            flag_index=len(flags) + 1,
            start_micro_event_candidate_id=start_id,
            end_micro_event_candidate_id=end_id,
            type=flag_type,
            reason=reason,
        ),
    ]


def _merge_short_break_segments(
    segments: list[_BlockSegment],
    warnings: list[str],
) -> list[_BlockSegment]:
    result: list[_BlockSegment] = []
    index = 0
    while index < len(segments):
        segment = segments[index]
        if (
            segment.block_type == "BREAK"
            and len(segment.episodes) <= _SHORT_BREAK_EPISODE_COUNT
            and index > 0
            and index < len(segments) - 1
        ):
            break_episodes = [
                _episode_with(
                    episode,
                    program_mode="BREAK",
                    primary_content_kind="BREAK_TIME",
                    visibility="COLLAPSED",
                )
                for episode in segment.episodes
            ]
            if result:
                previous = result[-1]
                result[-1] = _segment_with(
                    previous,
                    episodes=[*previous.episodes, *break_episodes],
                )
            else:
                next_segment = segments[index + 1]
                segments[index + 1] = _segment_with(
                    next_segment,
                    episodes=[*break_episodes, *next_segment.episodes],
                )
            warnings.append("short BREAK block merged into neighboring block")
            index += 1
            continue
        result.append(segment)
        index += 1
    return result


def _split_post_game_segments(
    segments: list[_BlockSegment],
    warnings: list[str],
) -> list[_BlockSegment]:
    result: list[_BlockSegment] = []
    for segment in segments:
        if segment.block_type != "POST_GAME":
            result.append(segment)
            continue
        split_index = _first_daily_post_game_run(segment.episodes)
        if split_index is None:
            result.append(segment)
            continue
        before = segment.episodes[:split_index]
        after = [
            _episode_with(episode, program_mode="JUST_CHATTING")
            for episode in segment.episodes[split_index:]
        ]
        if before:
            result.append(_segment_with(segment, episodes=before))
        result.append(_segment_with(segment, block_type="JUST_CHATTING", episodes=after))
        warnings.append("POST_GAME block split when unrelated daily chat started")
    return result


def _split_closing_segments(
    segments: list[_BlockSegment],
    warnings: list[str],
) -> list[_BlockSegment]:
    result: list[_BlockSegment] = []
    for segment in segments:
        if segment.block_type != "CLOSING":
            result.append(segment)
            continue
        first_closing = next(
            (
                index
                for index, episode in enumerate(segment.episodes)
                if _is_explicit_closing_episode(episode)
            ),
            None,
        )
        if first_closing is None:
            result.append(
                _segment_with(
                    segment,
                    block_type="JUST_CHATTING",
                    episodes=[
                        _episode_with(episode, program_mode="JUST_CHATTING")
                        for episode in segment.episodes
                    ],
                )
            )
            warnings.append("CLOSING block changed to JUST_CHATTING without closing terms")
            continue
        if first_closing == 0:
            result.append(segment)
            continue
        result.append(
            _segment_with(
                segment,
                block_type="JUST_CHATTING",
                episodes=[
                    _episode_with(episode, program_mode="JUST_CHATTING")
                    for episode in segment.episodes[:first_closing]
                ],
            )
        )
        result.append(_segment_with(segment, episodes=segment.episodes[first_closing:]))
        warnings.append("CLOSING block split after non-closing daily chat prefix")
    return result


def _merge_adjacent_same_type_segments(
    segments: list[_BlockSegment],
) -> list[_BlockSegment]:
    merged: list[_BlockSegment] = []
    for segment in segments:
        if merged and merged[-1].block_type == segment.block_type:
            previous = merged[-1]
            merged[-1] = _segment_with(
                previous,
                episodes=[*previous.episodes, *segment.episodes],
            )
            continue
        merged.append(segment)
    return merged


def _first_daily_post_game_run(
    episodes: list[TimelineEpisodeCreate],
) -> int | None:
    for index in range(len(episodes) - 1):
        if _is_daily_chat_after_game(episodes[index]) and _is_daily_chat_after_game(
            episodes[index + 1]
        ):
            return index
    return None


def _is_daily_chat_after_game(episode: TimelineEpisodeCreate) -> bool:
    if episode.primary_content_kind not in _POST_GAME_DAILY_CONTENT_KINDS:
        return False
    if episode.primary_content_kind in _GAME_RELATED_CONTENT_KINDS:
        return False
    if episode.program_mode in {"GAMEPLAY", "GAME_SETUP"}:
        return False
    text = _episode_text(episode).casefold()
    return not any(token in text for token in ("게임", "엔딩", "스토리", "플레이", "game"))


def _is_explicit_closing_episode(episode: TimelineEpisodeCreate) -> bool:
    text = _episode_text(episode).casefold()
    return any(term in text for term in _CLOSING_TERMS)


def _episode_text(episode: TimelineEpisodeCreate) -> str:
    return " ".join(
        [
            episode.title,
            episode.summary,
            episode.display_title,
            episode.display_summary,
            *episode.topics,
        ]
    )


def _is_late_broadcast_start_risk(
    episode: TimelineEpisodeCreate,
    candidates: list[MicroEventCandidateRecord],
    *,
    start_index: int,
    total_count: int,
) -> bool:
    if total_count <= 0 or start_index < int(total_count * 0.65):
        return False
    text = " ".join(
        [
            episode.title,
            episode.summary,
            episode.display_title,
            episode.display_summary,
            *(candidate.event for candidate in candidates),
        ]
    )
    if "방종" in text:
        return False
    return any(
        phrase in text
        for phrase in (
            "방송할 예정",
            "방송 예정",
            "방송 시작",
            "방송을 시작",
            "방송하면",
            "방송한다",
        )
    )
