from __future__ import annotations

from typing import Protocol

from codex_sdk_cli.domains.segments.models import SegmentSource


class SegmentSourceReaderPort(Protocol):
    async def load(self, video_id: int, timeline_work_item_id: int) -> SegmentSource: ...


class SegmentResultStorePort(Protocol):
    async def save(
        self,
        *,
        work_item_id: int,
        work_attempt_id: int,
        input_json: dict[str, object],
        segments: list[dict[str, object]],
        raw_response: str,
    ) -> int: ...


class SegmentInputPlannerPort(Protocol):
    async def prepare(
        self,
        *,
        video_id: int,
        timeline_work_item_id: int,
        model: str,
        reasoning_effort: str,
        prompt_version_id: int | None,
        taxonomy_version: str,
    ) -> dict[str, object]: ...


class SegmentPublishedTimelineReaderPort(Protocol):
    async def latest(
        self, *, video_id: int, environment: str, variant: str, schema_version: int
    ) -> int | None: ...
