from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from codex_sdk_cli.api.dependencies import (
    get_transcript_cue_repository,
    get_youtube_transcript_client,
    get_youtube_transcript_repository,
    get_youtube_transcript_storage,
)
from codex_sdk_cli.api.main import create_app
from codex_sdk_cli.domains.transcript_cues.ports import (
    TranscriptCueCreate,
    TranscriptCueRecord,
    TranscriptCueRepositoryPort,
    TranscriptCueSummaryRecord,
)
from codex_sdk_cli.domains.youtube_transcripts.exceptions import (
    YouTubeTranscriptDomainError,
    YouTubeTranscriptForbidden,
    YouTubeTranscriptNotFound,
    YouTubeTranscriptPersistenceError,
    YouTubeTranscriptStorageError,
    YouTubeTranscriptUpstreamError,
)
from codex_sdk_cli.domains.youtube_transcripts.ports import (
    TranscriptStorageLocation,
    YouTubeTranscriptFetchRequest,
    YouTubeTranscriptFetchResult,
    YouTubeTranscriptMetadataFilters,
    YouTubeTranscriptMetadataRecord,
    YouTubeTranscriptPort,
    YouTubeTranscriptRecord,
    YouTubeTranscriptRepositoryPort,
    YouTubeTranscriptSegment,
    YouTubeTranscriptStoragePort,
    YouTubeTranscriptStorageReadRequest,
    YouTubeTranscriptStorageSaveRequest,
)

VIDEO_ID = "dQw4w9WgXcQ"
CREATED_AT = datetime(2026, 6, 15, 7, 0, tzinfo=UTC)
UPDATED_AT = datetime(2026, 6, 15, 7, 1, tzinfo=UTC)


class FakeYouTubeTranscriptClient(YouTubeTranscriptPort):
    def __init__(self) -> None:
        self.requests: list[YouTubeTranscriptFetchRequest] = []
        self.error: YouTubeTranscriptDomainError | None = None

    async def fetch_transcript(
        self,
        request: YouTubeTranscriptFetchRequest,
    ) -> YouTubeTranscriptFetchResult:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return YouTubeTranscriptFetchResult(
            video_id=request.video_id,
            language="Korean",
            language_code=request.languages[0],
            is_generated=True,
            segments=(
                YouTubeTranscriptSegment(text="first line", start=0.0, duration=1.25),
                YouTubeTranscriptSegment(text="second line", start=1.25, duration=2.5),
            ),
        )


class FakeYouTubeTranscriptStorage(YouTubeTranscriptStoragePort):
    def __init__(self) -> None:
        self.saves: list[YouTubeTranscriptStorageSaveRequest] = []
        self.reads: list[YouTubeTranscriptStorageReadRequest] = []
        self.objects: dict[str, bytes] = {}
        self.error: YouTubeTranscriptStorageError | None = None

    def location_for(self, object_name: str) -> TranscriptStorageLocation:
        return TranscriptStorageLocation(
            bucket="raw",
            object_name=object_name,
            uri=f"s3://raw/{object_name}",
        )

    async def save_transcript(
        self,
        request: YouTubeTranscriptStorageSaveRequest,
    ) -> TranscriptStorageLocation:
        self.saves.append(request)
        self.objects[request.object_name] = request.payload
        if self.error is not None:
            raise self.error
        return self.location_for(request.object_name)

    async def read_transcript(
        self,
        request: YouTubeTranscriptStorageReadRequest,
    ) -> bytes:
        self.reads.append(request)
        if self.error is not None:
            raise self.error
        return self.objects[request.object_name]


class FakeYouTubeTranscriptRepository(YouTubeTranscriptRepositoryPort):
    def __init__(self) -> None:
        self.records: list[YouTubeTranscriptRecord] = []
        self.metadata_records: list[YouTubeTranscriptMetadataRecord] = [
            _metadata_record(id=1, video_id=VIDEO_ID, language_code="ko"),
            _metadata_record(id=2, video_id="abc123DEF45", language_code="en"),
        ]
        self.error: YouTubeTranscriptPersistenceError | None = None
        self.deleted_ids: list[int] = []

    async def save_transcript_record(
        self,
        record: YouTubeTranscriptRecord,
    ) -> YouTubeTranscriptMetadataRecord:
        self.records.append(record)
        if self.error is not None:
            raise self.error
        metadata = _metadata_record(
            id=max((item.id for item in self.metadata_records), default=0) + 1,
            video_id=record.video_id,
            language_code=record.language_code,
        )
        self.metadata_records.append(metadata)
        return metadata

    async def find_transcript_metadata_for_request(
        self,
        *,
        video_id: str,
        requested_languages: tuple[str, ...],
        preserve_formatting: bool,
    ) -> YouTubeTranscriptMetadataRecord | None:
        if self.error is not None:
            raise self.error
        return next(
            (
                record
                for record in reversed(self.metadata_records)
                if record.video_id == video_id
                and record.requested_languages == requested_languages
                and record.preserve_formatting == preserve_formatting
            ),
            None,
        )

    async def list_transcript_metadata(
        self,
        filters: YouTubeTranscriptMetadataFilters,
    ) -> list[YouTubeTranscriptMetadataRecord]:
        if self.error is not None:
            raise self.error
        records = self.metadata_records
        if filters.video_id is not None:
            records = [record for record in records if record.video_id == filters.video_id]
        if filters.language_code is not None:
            records = [
                record for record in records if record.language_code == filters.language_code
            ]
        return records[filters.offset : filters.offset + filters.limit]

    async def get_transcript_metadata(
        self,
        transcript_id: int,
    ) -> YouTubeTranscriptMetadataRecord | None:
        if self.error is not None:
            raise self.error
        return next(
            (record for record in self.metadata_records if record.id == transcript_id),
            None,
        )

    async def update_transcript_notes(
        self,
        transcript_id: int,
        notes: str | None,
    ) -> YouTubeTranscriptMetadataRecord | None:
        if self.error is not None:
            raise self.error
        for index, record in enumerate(self.metadata_records):
            if record.id == transcript_id:
                updated = _metadata_record(
                    id=record.id,
                    video_id=record.video_id,
                    language_code=record.language_code,
                    notes=notes,
                )
                self.metadata_records[index] = updated
                return updated
        return None

    async def delete_transcript_metadata(self, transcript_id: int) -> bool:
        if self.error is not None:
            raise self.error
        before_count = len(self.metadata_records)
        self.metadata_records = [
            record for record in self.metadata_records if record.id != transcript_id
        ]
        deleted = len(self.metadata_records) != before_count
        if deleted:
            self.deleted_ids.append(transcript_id)
        return deleted


class FakeTranscriptCueRepository(TranscriptCueRepositoryPort):
    def __init__(self) -> None:
        self.records: dict[int, list[TranscriptCueRecord]] = {
            1: [
                _cue_record(transcript_id=1, cue_index=1, text="first line"),
                _cue_record(transcript_id=1, cue_index=2, text="second line"),
            ]
        }
        self.replaced: list[TranscriptCueCreate] = []

    async def replace_cues(
        self,
        transcript_id: int,
        cues: list[TranscriptCueCreate],
    ) -> list[TranscriptCueRecord]:
        self.replaced = cues
        self.records[transcript_id] = [
            _cue_record(
                transcript_id=cue.transcript_id,
                cue_index=cue.cue_index,
                text=cue.text,
                source_job_id=cue.source_job_id,
                source_job_attempt_id=cue.source_job_attempt_id,
            )
            for cue in cues
        ]
        return self.records[transcript_id]

    async def list_cues(self, transcript_id: int) -> list[TranscriptCueRecord]:
        return self.records.get(transcript_id, [])

    async def summarize_cues(self, transcript_id: int) -> TranscriptCueSummaryRecord:
        records = await self.list_cues(transcript_id)
        return TranscriptCueSummaryRecord(
            transcript_id=transcript_id,
            cue_count=len(records),
            first_cue_id=records[0].cue_id if records else None,
            last_cue_id=records[-1].cue_id if records else None,
            source_job_id=records[0].source_job_id if records else None,
        )


def test_transcript_endpoint_normalizes_url_and_raw_video_id() -> None:
    fake = FakeYouTubeTranscriptClient()

    url_response = asyncio.run(
        _request(
            fake,
            json={"video": f"https://www.youtube.com/watch?v={VIDEO_ID}&list=ignored"},
        )
    )
    raw_response = asyncio.run(_request(fake, json={"video": VIDEO_ID}))

    assert url_response["videoId"] == VIDEO_ID
    assert raw_response["videoId"] == VIDEO_ID
    assert [request.video_id for request in fake.requests] == [VIDEO_ID, VIDEO_ID]


def test_transcript_endpoint_applies_default_languages_and_formatting() -> None:
    fake = FakeYouTubeTranscriptClient()

    response = asyncio.run(_request(fake, json={"video": f"https://youtu.be/{VIDEO_ID}?t=10"}))

    assert response["languageCode"] == "ko"
    assert fake.requests == [
        YouTubeTranscriptFetchRequest(
            video_id=VIDEO_ID,
            languages=("ko", "en"),
            preserve_formatting=False,
        )
    ]


def test_transcript_endpoint_passes_custom_languages_and_formatting() -> None:
    fake = FakeYouTubeTranscriptClient()

    response = asyncio.run(
        _request(
            fake,
            json={
                "video": f"https://www.youtube.com/shorts/{VIDEO_ID}?feature=share",
                "languages": ["ja", "en"],
                "preserveFormatting": True,
            },
        )
    )

    assert response["languageCode"] == "ja"
    assert fake.requests == [
        YouTubeTranscriptFetchRequest(
            video_id=VIDEO_ID,
            languages=("ja", "en"),
            preserve_formatting=True,
        )
    ]


def test_transcript_endpoint_returns_text_segments_and_camel_case_metadata() -> None:
    fake = FakeYouTubeTranscriptClient()

    response = asyncio.run(
        _request(fake, json={"video": f"https://www.youtube.com/embed/{VIDEO_ID}"})
    )

    assert response["videoId"] == VIDEO_ID
    assert response["language"] == "Korean"
    assert response["languageCode"] == "ko"
    assert response["isGenerated"] is True
    assert response["text"] == "first line\nsecond line"
    assert response["segments"] == [
        {"text": "first line", "start": 0.0, "duration": 1.25},
        {"text": "second line", "start": 1.25, "duration": 2.5},
    ]
    assert response["storage"]["bucket"] == "raw"
    assert response["storage"]["objectName"].startswith("youtube/transcripts/")
    assert response["storage"]["objectName"].endswith(".json")
    assert response["storage"]["uri"] == f"s3://raw/{response['storage']['objectName']}"


def test_old_transcript_endpoint_is_not_registered() -> None:
    fake = FakeYouTubeTranscriptClient()

    response = asyncio.run(
        _request(
            fake,
            path="/youtube/transcripts",
            json={"video": VIDEO_ID},
            expected_status=404,
        )
    )

    assert response["detail"] == "Not Found"
    assert fake.requests == []


def test_openapi_uses_youtube_transcripts_tag() -> None:
    app = create_app()
    schema = app.openapi()

    path_items = schema["paths"]["/youtube-transcripts"]

    assert path_items["post"]["tags"] == ["youtube-transcripts"]
    assert path_items["get"]["tags"] == ["youtube-transcripts"]
    assert schema["paths"]["/youtube-transcripts/{transcript_id}/content"]["get"][
        "tags"
    ] == ["youtube-transcripts"]
    assert schema["paths"]["/youtube-transcripts/{transcript_id}/cues"]["get"][
        "tags"
    ] == ["youtube-transcripts"]
    assert schema["paths"]["/youtube-transcripts/{transcript_id}/prompt-cues"]["get"][
        "tags"
    ] == ["youtube-transcripts"]
    assert schema["paths"]["/youtube-transcripts/{transcript_id}/cues/generate"]["post"][
        "tags"
    ] == ["youtube-transcripts"]


def test_transcript_endpoint_rejects_extra_fields() -> None:
    fake = FakeYouTubeTranscriptClient()

    response = asyncio.run(
        _request(
            fake,
            json={"video": VIDEO_ID, "format": "srt"},
            expected_status=422,
        )
    )

    assert fake.requests == []
    assert response["detail"][0]["type"] == "extra_forbidden"
    assert response["detail"][0]["loc"] == ["body", "format"]


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (YouTubeTranscriptNotFound("No transcript."), 404),
        (YouTubeTranscriptForbidden("Age restricted."), 403),
        (YouTubeTranscriptUpstreamError("Blocked upstream."), 502),
    ],
)
def test_transcript_endpoint_maps_domain_errors(
    error: YouTubeTranscriptDomainError,
    expected_status: int,
) -> None:
    fake = FakeYouTubeTranscriptClient()
    fake.error = error

    response = asyncio.run(
        _request(fake, json={"video": VIDEO_ID}, expected_status=expected_status)
    )

    assert response == {"detail": error.message}


def test_transcript_endpoint_maps_invalid_domain_to_bad_request() -> None:
    fake = FakeYouTubeTranscriptClient()

    response = asyncio.run(
        _request(
            fake,
            json={"video": f"https://example.com/watch?v={VIDEO_ID}"},
            expected_status=400,
        )
    )

    assert fake.requests == []
    assert response == {"detail": "Video must be a supported YouTube URL or video ID."}


def test_transcript_endpoint_maps_storage_errors_to_unavailable() -> None:
    fake = FakeYouTubeTranscriptClient()
    storage = FakeYouTubeTranscriptStorage()
    storage.error = YouTubeTranscriptStorageError("Storage unavailable.")

    response = asyncio.run(
        _request(
            fake,
            youtube_storage=storage,
            json={"video": VIDEO_ID},
            expected_status=503,
        )
    )

    assert response == {"detail": "Storage unavailable."}
    assert len(fake.requests) == 1
    assert len(storage.saves) == 1


def test_transcript_endpoint_maps_repository_errors_to_unavailable() -> None:
    fake = FakeYouTubeTranscriptClient()
    storage = FakeYouTubeTranscriptStorage()
    repository = FakeYouTubeTranscriptRepository()
    repository.error = YouTubeTranscriptPersistenceError("Metadata unavailable.")

    response = asyncio.run(
        _request(
            fake,
            youtube_storage=storage,
            youtube_repository=repository,
            json={"video": VIDEO_ID},
            expected_status=503,
        )
    )

    assert response == {"detail": "Metadata unavailable."}
    assert len(fake.requests) == 1
    assert len(storage.saves) == 1
    assert len(repository.records) == 1


def test_transcript_endpoint_does_not_store_when_fetch_fails() -> None:
    fake = FakeYouTubeTranscriptClient()
    fake.error = YouTubeTranscriptUpstreamError("Blocked upstream.")
    storage = FakeYouTubeTranscriptStorage()

    response = asyncio.run(
        _request(
            fake,
            youtube_storage=storage,
            json={"video": VIDEO_ID},
            expected_status=502,
        )
    )

    assert response == {"detail": "Blocked upstream."}
    assert storage.saves == []


def test_transcript_endpoint_does_not_persist_when_storage_fails() -> None:
    fake = FakeYouTubeTranscriptClient()
    storage = FakeYouTubeTranscriptStorage()
    storage.error = YouTubeTranscriptStorageError("Storage unavailable.")
    repository = FakeYouTubeTranscriptRepository()

    response = asyncio.run(
        _request(
            fake,
            youtube_storage=storage,
            youtube_repository=repository,
            json={"video": VIDEO_ID},
            expected_status=503,
        )
    )

    assert response == {"detail": "Storage unavailable."}
    assert repository.records == []


def test_list_transcript_metadata_filters_and_paginates() -> None:
    fake = FakeYouTubeTranscriptClient()
    repository = FakeYouTubeTranscriptRepository()

    response = asyncio.run(
        _request(
            fake,
            youtube_repository=repository,
            method="GET",
            path="/youtube-transcripts?videoId=dQw4w9WgXcQ&languageCode=ko&limit=1&offset=0",
        )
    )

    assert response == [_expected_metadata_response(id=1, language_code="ko")]
    assert fake.requests == []


def test_get_transcript_metadata_by_id() -> None:
    fake = FakeYouTubeTranscriptClient()

    response = asyncio.run(
        _request(fake, method="GET", path="/youtube-transcripts/1")
    )

    assert response == _expected_metadata_response(id=1, language_code="ko")


def test_get_transcript_content_reads_stored_payload_without_refetch() -> None:
    fake = FakeYouTubeTranscriptClient()
    storage = FakeYouTubeTranscriptStorage()
    object_name = f"youtube/transcripts/2026/06/15/{VIDEO_ID}-hash.json"
    storage.objects[object_name] = (
        b'{"videoId":"dQw4w9WgXcQ","language":"Korean","languageCode":"ko",'
        b'"isGenerated":true,"text":"first line\\nsecond line",'
        b'"segments":[{"text":"first line","start":0.0,"duration":1.25}],'
        b'"storage":{"bucket":"raw","objectName":"youtube/transcripts/2026/06/15/'
        b'dQw4w9WgXcQ-hash.json","uri":"s3://raw/youtube/transcripts/2026/06/15/'
        b'dQw4w9WgXcQ-hash.json"}}'
    )

    response = asyncio.run(
        _request(
            fake,
            youtube_storage=storage,
            method="GET",
            path="/youtube-transcripts/1/content",
        )
    )

    assert response["text"] == "first line\nsecond line"
    assert response["segments"][0]["text"] == "first line"
    assert storage.reads == [
        YouTubeTranscriptStorageReadRequest(object_name=object_name)
    ]
    assert fake.requests == []


def test_list_transcript_cues_returns_timing_payload() -> None:
    fake = FakeYouTubeTranscriptClient()
    cue_repository = FakeTranscriptCueRepository()

    response = asyncio.run(
        _request(
            fake,
            transcript_cue_repository=cue_repository,
            method="GET",
            path="/youtube-transcripts/1/cues",
        )
    )

    assert response["transcriptId"] == 1
    assert response["cueCount"] == 2
    assert response["items"][0]["cueId"] == "tr1-c000001"
    assert response["items"][0]["startMs"] == 0
    assert response["items"][1]["endMs"] == 3750


def test_get_transcript_prompt_cues_omits_timing() -> None:
    fake = FakeYouTubeTranscriptClient()

    response = asyncio.run(
        _request(fake, method="GET", path="/youtube-transcripts/1/prompt-cues")
    )

    assert response == {
        "transcriptId": 1,
        "cueCount": 2,
        "promptText": "[tr1-c000001] first line\n[tr1-c000002] second line",
        "cues": [
            {"cueId": "tr1-c000001", "cueIndex": 1, "text": "first line"},
            {"cueId": "tr1-c000002", "cueIndex": 2, "text": "second line"},
        ],
    }


def test_get_transcript_content_maps_missing_metadata_to_not_found() -> None:
    fake = FakeYouTubeTranscriptClient()

    response = asyncio.run(
        _request(
            fake,
            method="GET",
            path="/youtube-transcripts/999/content",
            expected_status=404,
        )
    )

    assert response == {"detail": "Transcript metadata not found."}


def test_get_transcript_content_maps_storage_error_to_unavailable() -> None:
    fake = FakeYouTubeTranscriptClient()
    storage = FakeYouTubeTranscriptStorage()
    storage.error = YouTubeTranscriptStorageError("Stored transcript unavailable.")

    response = asyncio.run(
        _request(
            fake,
            youtube_storage=storage,
            method="GET",
            path="/youtube-transcripts/1/content",
            expected_status=503,
        )
    )

    assert response == {"detail": "Stored transcript unavailable."}
    assert fake.requests == []


def test_get_transcript_metadata_maps_missing_row_to_not_found() -> None:
    fake = FakeYouTubeTranscriptClient()

    response = asyncio.run(
        _request(
            fake,
            method="GET",
            path="/youtube-transcripts/999",
            expected_status=404,
        )
    )

    assert response == {"detail": "Transcript metadata not found."}


def test_patch_transcript_metadata_sets_and_clears_notes() -> None:
    fake = FakeYouTubeTranscriptClient()
    repository = FakeYouTubeTranscriptRepository()

    set_response = asyncio.run(
        _request(
            fake,
            youtube_repository=repository,
            method="PATCH",
            path="/youtube-transcripts/1",
            json={"notes": "reviewed"},
        )
    )
    clear_response = asyncio.run(
        _request(
            fake,
            youtube_repository=repository,
            method="PATCH",
            path="/youtube-transcripts/1",
            json={"notes": None},
        )
    )

    assert set_response["notes"] == "reviewed"
    assert clear_response["notes"] is None


def test_patch_transcript_metadata_rejects_empty_body() -> None:
    fake = FakeYouTubeTranscriptClient()

    response = asyncio.run(
        _request(
            fake,
            method="PATCH",
            path="/youtube-transcripts/1",
            json={},
            expected_status=422,
        )
    )

    assert response["detail"][0]["msg"] == "Value error, notes must be provided."


def test_patch_transcript_metadata_maps_missing_row_to_not_found() -> None:
    fake = FakeYouTubeTranscriptClient()

    response = asyncio.run(
        _request(
            fake,
            method="PATCH",
            path="/youtube-transcripts/999",
            json={"notes": "missing"},
            expected_status=404,
        )
    )

    assert response == {"detail": "Transcript metadata not found."}


def test_delete_transcript_metadata_deletes_database_row_only() -> None:
    fake = FakeYouTubeTranscriptClient()
    storage = FakeYouTubeTranscriptStorage()
    repository = FakeYouTubeTranscriptRepository()

    response = asyncio.run(
        _request(
            fake,
            youtube_storage=storage,
            youtube_repository=repository,
            method="DELETE",
            path="/youtube-transcripts/1",
        )
    )

    assert response == {"success": True}
    assert repository.deleted_ids == [1]
    assert storage.saves == []


def test_delete_transcript_metadata_maps_missing_row_to_not_found() -> None:
    fake = FakeYouTubeTranscriptClient()

    response = asyncio.run(
        _request(
            fake,
            method="DELETE",
            path="/youtube-transcripts/999",
            expected_status=404,
        )
    )

    assert response == {"detail": "Transcript metadata not found."}


async def _request(
    youtube_client: FakeYouTubeTranscriptClient,
    *,
    youtube_storage: FakeYouTubeTranscriptStorage | None = None,
    youtube_repository: FakeYouTubeTranscriptRepository | None = None,
    transcript_cue_repository: FakeTranscriptCueRepository | None = None,
    method: str = "POST",
    path: str = "/youtube-transcripts",
    json: dict[str, Any] | None = None,
    expected_status: int = 200,
) -> Any:
    app = create_app()
    storage = youtube_storage or FakeYouTubeTranscriptStorage()
    repository = youtube_repository or FakeYouTubeTranscriptRepository()
    cue_repository = transcript_cue_repository or FakeTranscriptCueRepository()
    app.dependency_overrides[get_youtube_transcript_client] = lambda: youtube_client
    app.dependency_overrides[get_youtube_transcript_storage] = lambda: storage
    app.dependency_overrides[get_youtube_transcript_repository] = lambda: repository
    app.dependency_overrides[get_transcript_cue_repository] = lambda: cue_repository

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.request(method, path, json=json)

    assert response.status_code == expected_status, response.text
    return response.json()


def _metadata_record(
    *,
    id: int,
    video_id: str,
    language_code: str,
    notes: str | None = None,
) -> YouTubeTranscriptMetadataRecord:
    return YouTubeTranscriptMetadataRecord(
        id=id,
        video_id=video_id,
        language="Korean" if language_code == "ko" else "English",
        language_code=language_code,
        is_generated=True,
        requested_languages=(language_code, "en"),
        preserve_formatting=False,
        storage_bucket="raw",
        storage_object_name=f"youtube/transcripts/2026/06/15/{video_id}-hash.json",
        storage_uri=f"s3://raw/youtube/transcripts/2026/06/15/{video_id}-hash.json",
        response_sha256="a" * 64,
        segment_count=2,
        text_length=22,
        notes=notes,
        created_at=CREATED_AT,
        updated_at=UPDATED_AT,
    )


def _expected_metadata_response(
    *,
    id: int,
    language_code: str,
) -> dict[str, Any]:
    video_id = VIDEO_ID if id == 1 else "abc123DEF45"
    return {
        "id": id,
        "videoId": video_id,
        "language": "Korean" if language_code == "ko" else "English",
        "languageCode": language_code,
        "isGenerated": True,
        "requestedLanguages": [language_code, "en"],
        "preserveFormatting": False,
        "storage": {
            "bucket": "raw",
            "objectName": f"youtube/transcripts/2026/06/15/{video_id}-hash.json",
            "uri": f"s3://raw/youtube/transcripts/2026/06/15/{video_id}-hash.json",
        },
        "responseSha256": "a" * 64,
        "segmentCount": 2,
        "textLength": 22,
        "notes": None,
        "createdAt": "2026-06-15T07:00:00Z",
        "updatedAt": "2026-06-15T07:01:00Z",
    }


def _cue_record(
    *,
    transcript_id: int,
    cue_index: int,
    text: str,
    source_job_id: int | None = None,
    source_job_attempt_id: int | None = None,
) -> TranscriptCueRecord:
    start_ms = 0 if cue_index == 1 else 1250
    duration_ms = 1250 if cue_index == 1 else 2500
    return TranscriptCueRecord(
        id=cue_index,
        transcript_id=transcript_id,
        cue_id=f"tr{transcript_id}-c{cue_index:06d}",
        cue_index=cue_index,
        text=text,
        start_ms=start_ms,
        end_ms=start_ms + duration_ms,
        duration_ms=duration_ms,
        source_segment_index=cue_index - 1,
        source_job_id=source_job_id,
        source_job_attempt_id=source_job_attempt_id,
        created_at=CREATED_AT,
        updated_at=UPDATED_AT,
    )
