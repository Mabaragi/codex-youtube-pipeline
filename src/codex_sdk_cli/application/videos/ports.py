from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from codex_sdk_cli.domains.work.models import JsonObject


@dataclass(frozen=True, slots=True)
class VideoCollectionResult:
    created_count: int
    output_json: JsonObject


class VideoCollectorPort(Protocol):
    async def collect(
        self,
        *,
        channel_id: int,
        work_item_id: int,
        work_attempt_id: int,
        actor_type: str,
    ) -> VideoCollectionResult: ...
