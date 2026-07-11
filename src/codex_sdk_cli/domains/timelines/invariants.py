from __future__ import annotations

from .exceptions import TimelineCompositionOutputInvalid
from .models import _ComposerInput
from .ports import TimelineBlockCreate, TimelineEpisodeCreate
from .transforms import _episode_candidate_range


def _validate_timeline_invariants(
    episodes: list[TimelineEpisodeCreate],
    blocks: list[TimelineBlockCreate],
    composer_input: _ComposerInput,
) -> None:
    _validate_episode_coverage(episodes, composer_input)
    _validate_block_membership(episodes, blocks)


def _validate_episode_coverage(
    episodes: list[TimelineEpisodeCreate],
    composer_input: _ComposerInput,
) -> None:
    candidate_ids = [candidate.id for candidate in composer_input.micro_events]
    candidate_by_id = {candidate.id: candidate for candidate in composer_input.micro_events}
    candidate_index_by_id = {
        candidate_id: index for index, candidate_id in enumerate(candidate_ids)
    }
    next_candidate_index = 0
    for episode in episodes:
        range_info = _episode_candidate_range(
            episode,
            candidate_ids,
            candidate_index_by_id,
            candidate_by_id,
        )
        if range_info is None:
            raise TimelineCompositionOutputInvalid(
                f"Episode has invalid micro-event range: {episode.episode_id}"
            )
        _candidates, start_index, end_index = range_info
        if start_index != next_candidate_index:
            raise TimelineCompositionOutputInvalid(
                "Timeline episodes must cover every micro-event exactly once in order."
            )
        next_candidate_index = end_index + 1
    if next_candidate_index != len(candidate_ids):
        raise TimelineCompositionOutputInvalid("Timeline episodes do not cover all micro-events.")

def _validate_block_membership(
    episodes: list[TimelineEpisodeCreate],
    blocks: list[TimelineBlockCreate],
) -> None:
    episode_ids = [episode.episode_id for episode in episodes]
    block_episode_ids = [episode_id for block in blocks for episode_id in block.episode_ids]
    if block_episode_ids != episode_ids:
        raise TimelineCompositionOutputInvalid(
            "Timeline blocks must contain every episode exactly once in order."
        )
    episode_index_by_id = {episode_id: index for index, episode_id in enumerate(episode_ids)}
    for block in blocks:
        _validate_block(block, episodes, episode_index_by_id)


def _validate_block(
    block: TimelineBlockCreate,
    episodes: list[TimelineEpisodeCreate],
    episode_index_by_id: dict[str, int],
) -> None:
    indexes = [episode_index_by_id[episode_id] for episode_id in block.episode_ids]
    if not indexes:
        raise TimelineCompositionOutputInvalid("Timeline block cannot be empty.")
    expected = list(range(indexes[0], indexes[-1] + 1))
    if indexes != expected:
        raise TimelineCompositionOutputInvalid(
            f"Timeline block has non-contiguous episodes: {block.block_id}"
        )
    mismatches = [
        episodes[episode_index_by_id[episode_id]]
        for episode_id in block.episode_ids
        if episodes[episode_index_by_id[episode_id]].parent_block_id != block.block_id
    ]
    if mismatches:
        raise TimelineCompositionOutputInvalid(
            f"Episode parent block mismatch: {mismatches[0].episode_id}"
        )
