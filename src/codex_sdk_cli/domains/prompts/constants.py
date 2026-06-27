from __future__ import annotations

from typing import Literal

PromptKey = Literal[
    "micro_event_extract",
    "timeline_compose",
    "timeline_episode_repair",
]
PromptStatus = Literal["DRAFT", "PUBLISHED", "ARCHIVED"]
PromptSource = Literal["database", "fallback"]

MICRO_EVENT_EXTRACT_PROMPT_KEY: PromptKey = "micro_event_extract"
TIMELINE_COMPOSE_PROMPT_KEY: PromptKey = "timeline_compose"
TIMELINE_EPISODE_REPAIR_PROMPT_KEY: PromptKey = "timeline_episode_repair"

KNOWN_PROMPT_KEYS: tuple[PromptKey, ...] = (
    MICRO_EVENT_EXTRACT_PROMPT_KEY,
    TIMELINE_COMPOSE_PROMPT_KEY,
    TIMELINE_EPISODE_REPAIR_PROMPT_KEY,
)
