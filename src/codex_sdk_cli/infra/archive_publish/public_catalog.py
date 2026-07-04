from __future__ import annotations

import httpx

from codex_sdk_cli.domains.archive_publish.exceptions import (
    ArchivePublishCatalogSyncError,
)
from codex_sdk_cli.domains.archive_publish.ports import (
    ArchivePublicCatalogSyncPort,
    ArchivePublicCatalogTimelineIndex,
    ArchivePublicCatalogVideoRow,
)


class HttpArchivePublicCatalogSync(ArchivePublicCatalogSyncPort):
    def __init__(
        self,
        *,
        url: str,
        token: str,
        timeout_seconds: float,
    ) -> None:
        self._url = url
        self._token = token
        self._timeout_seconds = timeout_seconds

    async def upsert_video(self, row: ArchivePublicCatalogVideoRow) -> None:
        payload: dict[str, object] = {"videos": [_row_json(row)]}
        if row.timeline_index is not None:
            payload["timelineIndex"] = _timeline_index_json(row.timeline_index)
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout_seconds)
            ) as client:
                response = await client.post(
                    self._url,
                    headers={"authorization": f"Bearer {self._token}"},
                    json=payload,
                )
        except httpx.HTTPError as exc:
            raise ArchivePublishCatalogSyncError(
                f"Public catalog sync request failed: {exc}"
            ) from exc

        if response.status_code < 200 or response.status_code >= 300:
            message = _response_error_message(response)
            raise ArchivePublishCatalogSyncError(
                f"Public catalog sync failed with HTTP {response.status_code}: {message}"
            )


def _row_json(row: ArchivePublicCatalogVideoRow) -> dict[str, object]:
    return {
        "environment": row.environment,
        "videoId": row.video_id,
        "youtubeVideoId": row.youtube_video_id,
        "title": row.title,
        "streamerId": row.streamer_id,
        "streamerName": row.streamer_name,
        "channelId": row.channel_id,
        "channelName": row.channel_name,
        "channelHandle": row.channel_handle,
        "youtubeChannelId": row.youtube_channel_id,
        "publishedAt": row.published_at,
        "durationText": row.duration_text,
        "durationSeconds": row.duration_seconds,
        "thumbnailUrl": row.thumbnail_url,
        "isEmbeddable": row.is_embeddable,
        "displayTitle": row.display_title,
        "displaySummary": row.display_summary,
        "mainTopics": row.main_topics,
        "episodeCount": row.episode_count,
        "microEventCount": row.micro_event_count,
        "topicClusterCount": row.topic_cluster_count,
        "blockCount": row.block_count,
        "variant": row.variant,
        "timelineVersion": row.timeline_version,
        "timelineUrl": row.timeline_url,
        "artifactSha256": row.artifact_sha256,
        "artifactByteSize": row.artifact_byte_size,
        "updatedAt": row.updated_at,
    }


def _timeline_index_json(index: ArchivePublicCatalogTimelineIndex) -> dict[str, object]:
    return {
        "environment": index.environment,
        "videoId": index.video_id,
        "variant": index.variant,
        "timelineVersion": index.timeline_version,
        "updatedAt": index.updated_at,
        "blocks": [
            {
                "blockId": block.block_id,
                "blockIndex": block.block_index,
                "blockType": block.block_type,
                "title": block.title,
                "displayTitle": block.display_title,
                "startMs": block.start_ms,
                "endMs": block.end_ms,
                "episodeCount": block.episode_count,
            }
            for block in index.blocks
        ],
        "episodes": [
            {
                "episodeId": episode.episode_id,
                "blockId": episode.block_id,
                "episodeIndex": episode.episode_index,
                "startMs": episode.start_ms,
                "endMs": episode.end_ms,
                "title": episode.title,
                "displayTitle": episode.display_title,
                "programMode": episode.program_mode,
                "contentKind": episode.content_kind,
                "visibility": episode.visibility,
                "topics": episode.topics,
                "viewerTags": episode.viewer_tags,
                "microEventCount": episode.micro_event_count,
            }
            for episode in index.episodes
        ],
        "microEvents": [
            {
                "microEventId": event.micro_event_id,
                "episodeId": event.episode_id,
                "eventIndex": event.event_index,
                "startMs": event.start_ms,
                "endMs": event.end_ms,
                "text": event.text,
                "programMode": event.program_mode,
                "contentKind": event.content_kind,
            }
            for event in index.micro_events
        ],
        "topicClusters": [
            {
                "topicId": topic.topic_id,
                "label": topic.label,
                "displayLabel": topic.display_label,
                "episodeIds": topic.episode_ids,
            }
            for topic in index.topic_clusters
        ],
    }


def _response_error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:500]
    if isinstance(body, dict) and isinstance(body.get("error"), str):
        return body["error"]
    return str(body)[:500]
