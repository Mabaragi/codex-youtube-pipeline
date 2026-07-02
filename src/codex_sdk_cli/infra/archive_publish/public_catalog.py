from __future__ import annotations

import httpx

from codex_sdk_cli.domains.archive_publish.exceptions import (
    ArchivePublishCatalogSyncError,
)
from codex_sdk_cli.domains.archive_publish.ports import (
    ArchivePublicCatalogSyncPort,
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
        payload = {"videos": [_row_json(row)]}
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


def _response_error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:500]
    if isinstance(body, dict) and isinstance(body.get("error"), str):
        return body["error"]
    return str(body)[:500]
