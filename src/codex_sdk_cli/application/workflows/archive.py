from __future__ import annotations

from codex_sdk_cli.application.work.execution import (
    WorkExecutionContext,
    WorkExecutionResult,
    WorkExecutorPort,
)

from .ports import ArchivePublisherPort


class ArchivePublishExecutor(WorkExecutorPort):
    def __init__(self, publisher: ArchivePublisherPort) -> None:
        self._publisher = publisher

    async def execute(self, context: WorkExecutionContext) -> WorkExecutionResult:
        values = context.work_item.input_json
        published = await self._publisher.publish(
            work_item_id=context.work_item.id,
            work_attempt_id=context.attempt_id,
            video_id=_required_int(values, "videoId"),
            source_timeline_work_item_id=_required_int(
                values,
                "sourceTimelineWorkItemId",
            ),
            publish_mode=_required_str(values, "publishMode"),
            environment=_required_str(values, "environment"),
            variant=_required_str(values, "variant"),
            schema_version=_required_int(values, "schemaVersion"),
        )
        return WorkExecutionResult(
            output_json={
                "videoId": published.video_id,
                "artifactId": published.artifact_id,
                "publicUrl": published.public_url,
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
