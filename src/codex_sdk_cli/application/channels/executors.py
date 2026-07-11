from __future__ import annotations

from codex_sdk_cli.application.work.execution import (
    WorkExecutionContext,
    WorkExecutionResult,
    WorkExecutorPort,
)

from .ports import ChannelResolverPort


class ChannelResolveExecutor(WorkExecutorPort):
    def __init__(self, resolver: ChannelResolverPort) -> None:
        self._resolver = resolver

    async def execute(self, context: WorkExecutionContext) -> WorkExecutionResult:
        values = context.work_item.input_json
        result = await self._resolver.resolve(
            streamer_id=_required_int(values, "streamerId"),
            handle=_required_str(values, "handle"),
            work_item_id=context.work_item.id,
            work_attempt_id=context.attempt_id,
        )
        return WorkExecutionResult(
            output_json={
                "channelId": result.channel_id,
                "streamerId": result.streamer_id,
                "handle": result.handle,
                "name": result.name,
                "youtubeChannelId": result.youtube_channel_id,
                "uploadsPlaylistId": result.uploads_playlist_id,
            }
        )


def _required_int(values: dict[str, object], key: str) -> int:
    value = values.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise ValueError(f"{key} must be an integer.")


def _required_str(values: dict[str, object], key: str) -> str:
    value = values.get(key)
    if isinstance(value, str) and value:
        return value
    raise ValueError(f"{key} must be a non-empty string.")
