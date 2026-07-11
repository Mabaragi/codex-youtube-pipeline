from __future__ import annotations

from codex_sdk_cli.domains.pipeline_jobs.ports import JsonObject

from .models import _ComposerInput, _VideoSummaryOutput
from .ports import (
    TimelineBlockCreate,
    TimelineEpisodeCreate,
    TimelineReviewFlagCreate,
    TimelineTopicClusterCreate,
)
from .transforms import _synthetic_candidate_id


def _timeline_output_json(
    *,
    summary: _VideoSummaryOutput,
    blocks: list[TimelineBlockCreate],
    episodes: list[TimelineEpisodeCreate],
    topics: list[TimelineTopicClusterCreate],
    flags: list[TimelineReviewFlagCreate],
    composer_input: _ComposerInput,
) -> JsonObject:
    return {
        "video_summary": {
            "title": summary.title or composer_input.video.title,
            "summary": summary.summary,
            "display_title": summary.display_title or summary.title or composer_input.video.title,
            "display_summary": summary.display_summary or summary.summary,
            "main_topics": summary.main_topics,
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
                "highlight_micro_event_ids": [
                    synthetic_id
                    for candidate_id in episode.highlight_micro_event_candidate_ids
                    if (
                        synthetic_id := _synthetic_candidate_id(
                            composer_input,
                            candidate_id,
                        )
                    )
                    is not None
                ],
                "visibility": episode.visibility,
            }
            for episode in episodes
        ],
        "topic_clusters": [
            {
                "topic_id": topic.topic_id,
                "label": topic.label,
                "summary": topic.summary,
                "display_label": topic.display_label,
                "episode_ids": topic.episode_ids,
            }
            for topic in topics
        ],
        "review_flags": [
            {
                "start_micro_event_id": _synthetic_candidate_id(
                    composer_input,
                    flag.start_micro_event_candidate_id,
                ),
                "end_micro_event_id": _synthetic_candidate_id(
                    composer_input,
                    flag.end_micro_event_candidate_id,
                ),
                "type": flag.type,
                "reason": flag.reason,
            }
            for flag in flags
        ],
    }
