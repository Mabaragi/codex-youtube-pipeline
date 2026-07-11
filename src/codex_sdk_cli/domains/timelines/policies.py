from __future__ import annotations

from typing import get_args

from .ports import (
    TimelineBlockType,
    TimelineContentKind,
    TimelineReviewFlagType,
    TimelineViewerTag,
    TimelineVisibility,
)

_TIMELINE_BLOCK_TYPES = frozenset(get_args(TimelineBlockType))

_TIMELINE_CONTENT_KINDS = frozenset(get_args(TimelineContentKind))

_TIMELINE_VISIBILITIES = frozenset(get_args(TimelineVisibility))

_TIMELINE_VIEWER_TAGS = frozenset(get_args(TimelineViewerTag))

_TIMELINE_REVIEW_FLAG_TYPES = frozenset(get_args(TimelineReviewFlagType))

_VIEWER_TAG_CONTENT_KIND_ALIASES: dict[str, TimelineViewerTag | None] = {
    "OPINION": "INFORMATION",
    "TECHNICAL_SETUP": "INFORMATION",
    "OTHER": "INFORMATION",
    "PERSONAL_STORY": "STORY",
    "META_CHAT": "META",
    "COMMUNITY_REVIEW": "COMMUNITY",
    "MEDIA_REVIEW": "MEDIA",
    "BREAK_TIME": None,
}

_MAX_EPISODE_TOPICS = 6

_MAX_EPISODE_HIGHLIGHTS = 3

_OVERBROAD_MICRO_EVENT_COUNT = 9

_OVERBROAD_LARGE_MICRO_EVENT_COUNT = 12

_DETERMINISTIC_COVERAGE_REPAIR_CHUNK_SIZE = 4

_DETERMINISTIC_COVERAGE_REPAIR_LIMIT = 32

_SHORT_BREAK_EPISODE_COUNT = 2

_POST_GAME_DAILY_CONTENT_KINDS = frozenset({"PERSONAL_STORY", "OPINION", "QNA", "META_CHAT"})

_GAME_RELATED_CONTENT_KINDS = frozenset({"GAME_PROGRESS", "GAME_DISCUSSION"})

_GAME_RELATED_MODES = frozenset({"GAMEPLAY", "GAME_SETUP", "POST_GAME"})

_CLOSING_TERMS = (
    "방종",
    "마무리",
    "종료",
    "안내",
    "인사",
    "고마워",
    "감사",
    "수고",
    "다음",
    "오늘",
    "closing",
    "goodbye",
)
