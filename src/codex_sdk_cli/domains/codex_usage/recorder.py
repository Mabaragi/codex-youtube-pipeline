from __future__ import annotations

import logging

from .ports import CodexUsageCreate, CodexUsageRecorderPort, CodexUsageRepositoryPort

logger = logging.getLogger(__name__)


class BestEffortCodexUsageRecorder(CodexUsageRecorderPort):
    def __init__(self, repository: CodexUsageRepositoryPort) -> None:
        self._repository = repository

    async def record_usage(self, usage: CodexUsageCreate) -> None:
        try:
            await self._repository.create_usage(usage)
        except Exception:
            logger.exception("Failed to record Codex usage.")
