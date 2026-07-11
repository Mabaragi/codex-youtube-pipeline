from __future__ import annotations

from codex_sdk_cli.application.work.execution import (
    WorkExecutionContext,
    WorkExecutionResult,
    WorkExecutorPort,
)

from .ports import VideoCollectorPort


class VideoCollectExecutor(WorkExecutorPort):
    def __init__(self, collector: VideoCollectorPort, *, actor_type: str = "system") -> None:
        self._collector = collector
        self._actor_type = actor_type

    async def execute(self, context: WorkExecutionContext) -> WorkExecutionResult:
        channel_id = _required_int(context.work_item.input_json, "channelId")
        result = await self._collector.collect(
            channel_id=channel_id,
            work_item_id=context.work_item.id,
            work_attempt_id=context.attempt_id,
            actor_type=self._actor_type,
        )
        return WorkExecutionResult(output_json=result.output_json)


def _required_int(values: dict[str, object], key: str) -> int:
    value = values.get(key)
    if not isinstance(value, int):
        raise ValueError(f"Work item input {key} must be an integer.")
    return value
