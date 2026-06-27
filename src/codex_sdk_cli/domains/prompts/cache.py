from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

from .constants import PromptKey
from .ports import ResolvedPrompt


class Clock(Protocol):
    def __call__(self) -> float:
        """Return monotonic seconds."""


@dataclass(frozen=True, slots=True)
class PromptCacheEntry:
    prompt: ResolvedPrompt
    expires_at: float


class PromptCache:
    def __init__(self, *, clock: Clock = time.monotonic) -> None:
        self._clock = clock
        self._entries: dict[PromptKey, PromptCacheEntry] = {}

    def get(self, prompt_key: PromptKey) -> ResolvedPrompt | None:
        entry = self._entries.get(prompt_key)
        if entry is None:
            return None
        if entry.expires_at <= self._clock():
            self._entries.pop(prompt_key, None)
            return None
        return entry.prompt

    def set(self, prompt: ResolvedPrompt, *, ttl_seconds: int) -> ResolvedPrompt:
        self._entries[prompt.key] = PromptCacheEntry(
            prompt=prompt,
            expires_at=self._clock() + ttl_seconds,
        )
        return prompt

    def invalidate(self, prompt_key: PromptKey | None = None) -> int:
        if prompt_key is None:
            count = len(self._entries)
            self._entries.clear()
            return count
        return 1 if self._entries.pop(prompt_key, None) is not None else 0
