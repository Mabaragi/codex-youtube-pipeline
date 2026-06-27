from __future__ import annotations

import hashlib
from functools import lru_cache
from importlib import resources

from .constants import (
    MICRO_EVENT_EXTRACT_PROMPT_KEY,
    TIMELINE_COMPOSE_PROMPT_KEY,
    TIMELINE_EPISODE_REPAIR_PROMPT_KEY,
    PromptKey,
)
from .exceptions import PromptNotFound
from .ports import ResolvedPrompt

_RESOURCE_PACKAGE = f"{__package__}.resources"
_FALLBACK_FILES: dict[PromptKey, tuple[str, str]] = {
    MICRO_EVENT_EXTRACT_PROMPT_KEY: (
        "micro-event-extract-v3",
        "micro_event_extract_v3.md",
    ),
    TIMELINE_COMPOSE_PROMPT_KEY: (
        "timeline-compose-v3",
        "timeline_compose_v3.md",
    ),
    TIMELINE_EPISODE_REPAIR_PROMPT_KEY: (
        "timeline-episode-repair-v1",
        "episode_repair_v1.md",
    ),
}


def fallback_prompt(prompt_key: PromptKey) -> ResolvedPrompt:
    version_label, _ = _fallback_file(prompt_key)
    body = fallback_prompt_text(prompt_key)
    return ResolvedPrompt(
        key=prompt_key,
        version_id=None,
        version_label=version_label,
        body=body,
        body_sha256=hashlib.sha256(body.encode("utf-8")).hexdigest(),
        source="fallback",
    )


@lru_cache(maxsize=len(_FALLBACK_FILES))
def fallback_prompt_text(prompt_key: PromptKey) -> str:
    _, file_name = _fallback_file(prompt_key)
    return resources.files(_RESOURCE_PACKAGE).joinpath(file_name).read_text(
        encoding="utf-8"
    )


def _fallback_file(prompt_key: PromptKey) -> tuple[str, str]:
    item = _FALLBACK_FILES.get(prompt_key)
    if item is None:
        raise PromptNotFound(f"Unknown prompt key: {prompt_key}")
    return item
