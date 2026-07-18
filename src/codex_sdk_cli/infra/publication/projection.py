from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from codex_sdk_cli.domains.archive_publish.ports import (
    ArchivePublicCatalogTimelineIndex,
    ArchivePublicCatalogTimelineIndexBlock,
    ArchivePublicCatalogTimelineIndexEpisode,
    ArchivePublicCatalogTimelineIndexMicroEvent,
    ArchivePublicCatalogTimelineIndexTopicCluster,
    ArchivePublicCatalogVideoRow,
    ArchiveVideoArtifactRecord,
)
from codex_sdk_cli.domains.video_tasks.ports import JsonObject


@dataclass(frozen=True, slots=True)
class DestinationIndexArtifact:
    object_key: str
    public_url: str
    payload_bytes: bytes
    sha256: str
    byte_size: int
    pointer_key: str
    pointer_public_url: str
    pointer_payload_bytes: bytes
    pointer_sha256: str
    pointer_byte_size: int
    video_count: int


def canonical_artifact_key(sha256: str) -> str:
    return f"artifacts/sha256/{sha256[:2]}/{sha256}.json"


def destination_artifact_key(
    artifact: ArchiveVideoArtifactRecord,
    *,
    key_prefix: str,
) -> str:
    prefix = key_prefix.strip("/")
    return (
        f"{prefix}/archive/v{artifact.schema_version}/videos/{artifact.video_id}/"
        f"timeline.{artifact.version}.{_clean_path_part(artifact.variant)}.json"
    )


def parse_timeline_payload(payload_bytes: bytes) -> JsonObject:
    try:
        value = json.loads(payload_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Canonical timeline artifact is not valid UTF-8 JSON.") from exc
    if not isinstance(value, dict):
        raise ValueError("Canonical timeline artifact must be a JSON object.")
    return cast(JsonObject, value)


def catalog_row_from_timeline(
    *,
    artifact: ArchiveVideoArtifactRecord,
    payload: JsonObject,
    timeline_url: str,
) -> ArchivePublicCatalogVideoRow:
    video = _object(payload.get("video"))
    streamer = _object(video.get("streamer"))
    channel = _object(video.get("channel"))
    updated_at = _now_iso()
    return ArchivePublicCatalogVideoRow(
        environment=artifact.environment,
        video_id=artifact.video_id,
        youtube_video_id=_string(payload.get("youtubeVideoId"), ""),
        title=_string(video.get("title"), ""),
        streamer_id=_public_streamer_id(streamer=streamer, channel=channel),
        streamer_name=_optional_string(streamer.get("name")),
        channel_id=_optional_int(channel.get("id")),
        channel_name=_optional_string(channel.get("name")),
        channel_handle=_optional_string(channel.get("handle")),
        youtube_channel_id=_optional_string(channel.get("youtubeChannelId")),
        published_at=_optional_string(video.get("publishedAt")),
        duration_text=_optional_string(video.get("duration")),
        duration_seconds=_optional_float(video.get("durationSec")),
        thumbnail_url=_optional_string(video.get("thumbnailUrl")),
        is_embeddable=_optional_bool(video.get("isEmbeddable")),
        display_title=_optional_string(video.get("displayTitle")),
        display_summary=_optional_string(video.get("displaySummary")),
        main_topics=_string_list(video.get("mainTopics")),
        episode_count=artifact.episode_count,
        micro_event_count=artifact.micro_event_count,
        topic_cluster_count=artifact.topic_cluster_count,
        block_count=artifact.block_count,
        variant=artifact.variant,
        timeline_version=artifact.version,
        timeline_url=timeline_url,
        artifact_sha256=artifact.sha256,
        artifact_byte_size=artifact.byte_size,
        updated_at=updated_at,
        timeline_index=_timeline_index(
            artifact=artifact,
            payload=payload,
            updated_at=updated_at,
        ),
    )


def build_destination_index(
    *,
    artifacts: tuple[tuple[ArchiveVideoArtifactRecord, JsonObject, str], ...],
    key_prefix: str,
    public_url: Callable[[str], str],
    environment: str,
    schema_version: int,
    version: str,
    generated_at: str | None = None,
) -> DestinationIndexArtifact:
    prefix = key_prefix.strip("/")
    object_key = f"{prefix}/archive/v{schema_version}/index.{version}.json"
    pointer_key = f"{prefix}/channels/{_clean_path_part(environment)}.json"
    videos_by_id: dict[int, JsonObject] = {}
    for artifact, timeline, timeline_url in artifacts:
        video = _object(timeline.get("video"))
        existing = videos_by_id.setdefault(
            artifact.video_id,
            {
                "id": artifact.video_id,
                "youtubeId": _string(timeline.get("youtubeVideoId"), ""),
                "title": _string(video.get("title"), ""),
                "streamer": _object(video.get("streamer")),
                "channel": _object(video.get("channel")),
                "publishedAt": _string(video.get("publishedAt"), ""),
                "durationText": _optional_string(video.get("duration")),
                "isEmbeddable": _optional_bool(video.get("isEmbeddable")),
                "episodeCount": artifact.episode_count,
                "eventCount": artifact.micro_event_count,
                "thumbnailUrl": _optional_string(video.get("thumbnailUrl")),
                "timelineVariants": [],
            },
        )
        variants = existing["timelineVariants"]
        if isinstance(variants, list):
            variants.append(
                {
                    "key": artifact.variant,
                    "url": timeline_url,
                    "version": artifact.version,
                }
            )
    videos = list(videos_by_id.values())
    videos.sort(
        key=lambda item: (
            str(item.get("publishedAt", "")),
            int(item.get("id", 0)),
        ),
        reverse=True,
    )
    generated_at = generated_at or _now_iso()
    index_payload: JsonObject = {
        "schemaVersion": schema_version,
        "environment": environment,
        "generatedAt": generated_at,
        "version": version,
        "videos": videos,
    }
    index_url = public_url(object_key)
    pointer_payload: JsonObject = {
        "schemaVersion": schema_version,
        "environment": environment,
        "generatedAt": generated_at,
        "currentIndexUrl": index_url,
        "currentIndexVersion": version,
        "videoCount": len(videos),
    }
    index_bytes = _json_bytes(index_payload)
    pointer_bytes = _json_bytes(pointer_payload)
    return DestinationIndexArtifact(
        object_key=object_key,
        public_url=index_url,
        payload_bytes=index_bytes,
        sha256=_sha256(index_bytes),
        byte_size=len(index_bytes),
        pointer_key=pointer_key,
        pointer_public_url=public_url(pointer_key),
        pointer_payload_bytes=pointer_bytes,
        pointer_sha256=_sha256(pointer_bytes),
        pointer_byte_size=len(pointer_bytes),
        video_count=len(videos),
    )


def membership_sha256(artifact_ids: tuple[int, ...]) -> str:
    payload = ",".join(str(value) for value in artifact_ids).encode()
    return _sha256(payload)


def _timeline_index(
    *,
    artifact: ArchiveVideoArtifactRecord,
    payload: JsonObject,
    updated_at: str,
) -> ArchivePublicCatalogTimelineIndex:
    episodes = _object_list(payload.get("episodes"))
    episodes_by_id = {_string(episode.get("episodeId"), ""): episode for episode in episodes}
    return ArchivePublicCatalogTimelineIndex(
        environment=artifact.environment,
        video_id=artifact.video_id,
        variant=artifact.variant,
        timeline_version=artifact.version,
        updated_at=updated_at,
        blocks=[
            _block_index(block, episodes_by_id=episodes_by_id)
            for block in _object_list(payload.get("blocks"))
        ],
        episodes=[_episode_index(episode) for episode in episodes],
        micro_events=[event for episode in episodes for event in _micro_event_indexes(episode)],
        topic_clusters=[
            ArchivePublicCatalogTimelineIndexTopicCluster(
                topic_id=_string(topic.get("topicId"), "topic_unknown"),
                label=_string(topic.get("label"), "Topic"),
                display_label=_optional_string(topic.get("displayLabel")),
                episode_ids=_string_list(topic.get("episodeIds")),
            )
            for topic in _object_list(payload.get("topicClusters"))
        ],
    )


def _block_index(
    block: JsonObject,
    *,
    episodes_by_id: dict[str, JsonObject],
) -> ArchivePublicCatalogTimelineIndexBlock:
    episode_ids = _string_list(block.get("episodeIds"))
    episodes = [episodes_by_id[value] for value in episode_ids if value in episodes_by_id]
    start_ms = _int(episodes[0].get("startMs"), 0) if episodes else 0
    end_ms = _int(episodes[-1].get("endMs"), start_ms) if episodes else start_ms
    return ArchivePublicCatalogTimelineIndexBlock(
        block_id=_string(block.get("blockId"), "block_unknown"),
        block_index=_int(block.get("blockIndex"), 0),
        block_type=_string(block.get("blockType"), "UNKNOWN"),
        title=_string(block.get("title"), "Timeline block"),
        display_title=_optional_string(block.get("displayTitle")),
        start_ms=start_ms,
        end_ms=end_ms,
        episode_count=len(episodes),
    )


def _episode_index(episode: JsonObject) -> ArchivePublicCatalogTimelineIndexEpisode:
    events = _object_list(episode.get("microEvents"))
    return ArchivePublicCatalogTimelineIndexEpisode(
        episode_id=_string(episode.get("episodeId"), "episode_unknown"),
        block_id=_string(episode.get("parentBlockId"), "block_unknown"),
        episode_index=_int(episode.get("episodeIndex"), 0),
        start_ms=_int(episode.get("startMs"), 0),
        end_ms=_int(episode.get("endMs"), 0),
        title=_string(episode.get("title"), "Timeline episode"),
        display_title=_optional_string(episode.get("displayTitle")),
        program_mode=_string(episode.get("programMode"), "UNKNOWN"),
        content_kind=_string(episode.get("primaryContentKind"), "UNKNOWN"),
        visibility=_string(episode.get("visibility"), "DEFAULT"),
        topics=_string_list(episode.get("topics")),
        viewer_tags=_string_list(episode.get("viewerTags")),
        micro_event_count=len(events),
    )


def _micro_event_indexes(
    episode: JsonObject,
) -> list[ArchivePublicCatalogTimelineIndexMicroEvent]:
    episode_id = _string(episode.get("episodeId"), "episode_unknown")
    return [
        ArchivePublicCatalogTimelineIndexMicroEvent(
            micro_event_id=_string(event.get("id"), f"{episode_id}-event-{index:03d}"),
            episode_id=episode_id,
            event_index=index,
            start_ms=_int(event.get("startMs"), 0),
            end_ms=_int(event.get("endMs"), 0),
            text=_string(event.get("event"), ""),
            program_mode=_string(event.get("programMode"), "UNKNOWN"),
            content_kind=_string(event.get("contentKind"), "UNKNOWN"),
        )
        for index, event in enumerate(_object_list(episode.get("microEvents")), start=1)
    ]


def _public_streamer_id(*, streamer: JsonObject, channel: JsonObject) -> str | None:
    by_handle = {
        "@nagzziholoen": "nagi",
        "@mayuzumirei": "rei",
        "@cocomine_chichi": "chichi",
        "@panyachannel": "panya",
    }
    by_youtube_id = {
        "UCRVIMEcKHurG42oTo4DQT5g": "nagi",
        "UCfI0o-TiJknTPbDhjblPhzg": "rei",
        "UCdQhiIMOTSoLdNjeQaeyFiA": "chichi",
        "UC_0he5K-1W8sZTooz0tUoiA": "panya",
    }
    handle = _string(channel.get("handle"), "").removeprefix("@").lower()
    mapped = by_handle.get(f"@{handle}") or by_youtube_id.get(
        _string(channel.get("youtubeChannelId"), "")
    )
    if mapped is not None:
        return mapped
    value = streamer.get("id")
    return str(value) if isinstance(value, (str, int)) else None


def _json_bytes(value: JsonObject) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _clean_path_part(value: str) -> str:
    cleaned = "".join(
        character if character.isalnum() or character in {"-", "_"} else "-" for character in value
    )
    return cleaned.strip("-_") or "default"


def _object(value: object) -> JsonObject:
    return cast(JsonObject, value) if isinstance(value, dict) else {}


def _object_list(value: object) -> list[JsonObject]:
    if not isinstance(value, list):
        return []
    return [cast(JsonObject, item) for item in value if isinstance(item, dict)]


def _string(value: object, default: str) -> str:
    return value if isinstance(value, str) else default


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _string_list(value: object) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _int(value: object, default: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _optional_float(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _optional_bool(value: object) -> bool | None:
    return value if isinstance(value, bool) else None
