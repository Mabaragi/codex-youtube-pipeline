from __future__ import annotations

import hashlib
import json
from typing import cast

from codex_sdk_cli.domains.pipeline_jobs.ports import JsonObject
from codex_sdk_cli.domains.timelines.ports import TimelineCompositionRecord
from codex_sdk_cli.domains.video_tasks.exceptions import VideoTaskRetryNotAllowed
from codex_sdk_cli.domains.videos.ports import VideoRecord

from .constants import ARCHIVE_PUBLISH_TASK_VERSION
from .ports import RoutedArchivePublishContext
from .schemas import ArchivePublishModeLiteral


def _task_input_hash(
    *,
    video: VideoRecord,
    composition: TimelineCompositionRecord,
    publish_mode: ArchivePublishModeLiteral,
    environment: str,
    variant: str,
    schema_version: int,
    route_context: RoutedArchivePublishContext | None = None,
    stop_after_stage: str | None = None,
) -> str:
    payload = {
        "environment": environment,
        "publishMode": publish_mode,
        "schemaVersion": schema_version,
        "sourceMicroEventTaskId": composition.source_micro_event_task_id,
        "sourceTimelineCompositionId": composition.id,
        "sourceTimelineTaskId": composition.video_task_id,
        "taskVersion": ARCHIVE_PUBLISH_TASK_VERSION,
        "variant": variant,
        "videoId": video.id,
        "youtubeVideoId": video.youtube_video_id,
        "profileRevisionId": (
            route_context.profile_revision_id if route_context is not None else None
        ),
        "publishRouteId": route_context.route_id if route_context is not None else None,
        "stopAfterStage": stop_after_stage,
    }
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def _task_input_json(
    *,
    video: VideoRecord,
    composition: TimelineCompositionRecord,
    input_hash: str,
    publish_mode: ArchivePublishModeLiteral,
    environment: str,
    variant: str,
    schema_version: int,
    timeout_seconds: int,
    route_context: RoutedArchivePublishContext | None = None,
    stop_after_stage: str | None = None,
) -> JsonObject:
    payload: JsonObject = {
        "videoId": video.id,
        "youtubeVideoId": video.youtube_video_id,
        "sourceTimelineCompositionId": composition.id,
        "sourceTimelineTaskId": composition.video_task_id,
        "sourceMicroEventTaskId": composition.source_micro_event_task_id,
        "taskVersion": ARCHIVE_PUBLISH_TASK_VERSION,
        "inputHash": input_hash,
        "publishMode": publish_mode,
        "environment": environment,
        "variant": variant,
        "schemaVersion": schema_version,
        "timeoutSeconds": timeout_seconds,
    }
    if stop_after_stage is not None:
        payload["stopAfterStage"] = stop_after_stage
    if route_context is not None:
        payload["publicationRoute"] = {
            "profileId": route_context.profile_id,
            "profileKey": route_context.profile_key,
            "profileRevisionId": route_context.profile_revision_id,
            "routeId": route_context.route_id,
            "publishMode": route_context.publish_mode,
            "environment": route_context.environment,
            "primaryObjectBindingId": route_context.primary_object_binding_id,
            "primaryDestinationId": route_context.primary_destination_id,
            "primaryKeyPrefix": route_context.primary_key_prefix,
            "primaryPublicBaseUrl": route_context.primary_public_base_url,
        }
    return payload


def _routed_context_from_input(
    input_json: JsonObject,
) -> RoutedArchivePublishContext | None:
    value = input_json.get("publicationRoute")
    if not isinstance(value, dict):
        return None
    route = cast(JsonObject, value)
    return RoutedArchivePublishContext(
        profile_id=_required_int(route, "profileId"),
        profile_key=_required_str(route, "profileKey"),
        profile_revision_id=_required_int(route, "profileRevisionId"),
        route_id=_required_int(route, "routeId"),
        publish_mode=_required_str(route, "publishMode"),
        environment=_required_str(route, "environment"),
        primary_object_binding_id=_required_int(route, "primaryObjectBindingId"),
        primary_destination_id=_required_int(route, "primaryDestinationId"),
        primary_key_prefix=_required_str(route, "primaryKeyPrefix"),
        primary_public_base_url=_required_str(route, "primaryPublicBaseUrl"),
    )


def _int_output(input_json: JsonObject, key: str) -> int | None:
    value = input_json.get(key)
    return value if isinstance(value, int) else None


def _str_output(input_json: JsonObject, key: str) -> str | None:
    value = input_json.get(key)
    return value if isinstance(value, str) else None


def _publish_mode(input_json: JsonObject) -> ArchivePublishModeLiteral:
    return "dev" if _str_output(input_json, "publishMode") == "dev" else "prod"


def _required_str(input_json: JsonObject, key: str) -> str:
    value = input_json.get(key)
    if not isinstance(value, str) or not value:
        raise VideoTaskRetryNotAllowed(f"Task input is missing string '{key}'.")
    return value


def _required_int(input_json: JsonObject, key: str) -> int:
    value = input_json.get(key)
    if not isinstance(value, int):
        raise VideoTaskRetryNotAllowed(f"Task input is missing integer '{key}'.")
    return value
