from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from httpx import ASGITransport, AsyncClient

from codex_sdk_cli.api.dependencies import (
    get_pipeline_job_repository,
    get_settings,
    get_streamer_repository,
    get_youtube_data_client,
)
from codex_sdk_cli.api.main import create_app
from codex_sdk_cli.domains.pipeline_jobs.ports import (
    JsonObject,
    PipelineJobAttemptRecord,
    PipelineJobAttemptStatus,
    PipelineJobCreate,
    PipelineJobRecord,
    PipelineJobRepositoryPort,
    PipelineJobStatus,
)
from codex_sdk_cli.domains.streamers.ports import (
    ChannelCreate,
    ChannelRecord,
    ChannelUpdate,
    StreamerRecord,
    StreamerRepositoryPort,
)
from codex_sdk_cli.domains.youtube_data.exceptions import (
    YouTubeDataChannelNotFound,
    YouTubeDataDomainError,
    YouTubeDataUpstreamError,
)
from codex_sdk_cli.domains.youtube_data.ports import (
    YouTubeChannelResolution,
    YouTubeDataClientPort,
)
from codex_sdk_cli.settings import CliSettings


class FakeYouTubeDataClient(YouTubeDataClientPort):
    def __init__(self) -> None:
        self.requests: list[tuple[str, int | None]] = []
        self.error: YouTubeDataDomainError | None = None
        self.youtube_channel_id = "UC_x5XG1OV2P6uZZ5FSM9Ttw"
        self.title = "Google for Developers"

    async def resolve_youtube_channel_by_handle(
        self,
        handle: str,
        *,
        pipeline_job_attempt_id: int | None = None,
    ) -> YouTubeChannelResolution:
        self.requests.append((handle, pipeline_job_attempt_id))
        if self.error is not None:
            raise self.error
        return YouTubeChannelResolution(
            handle=handle,
            youtube_channel_id=self.youtube_channel_id,
            title=self.title,
            source_api_call_id=42,
        )


class FakePipelineJobRepository(PipelineJobRepositoryPort):
    def __init__(self) -> None:
        self.jobs: dict[int, PipelineJobRecord] = {}
        self.attempts: dict[int, PipelineJobAttemptRecord] = {}
        self.next_job_id = 1
        self.next_attempt_id = 1

    async def create_job(self, job: PipelineJobCreate) -> PipelineJobRecord:
        now = datetime.now(UTC)
        record = PipelineJobRecord(
            id=self.next_job_id,
            step=job.step,
            status=job.status,
            subject_type=job.subject_type,
            subject_id=job.subject_id,
            external_key=job.external_key,
            input_json=job.input_json,
            input_hash=job.input_hash,
            parent_job_id=job.parent_job_id,
            created_at=now,
            updated_at=now,
            completed_at=None,
        )
        self.jobs[record.id] = record
        self.next_job_id += 1
        return record

    async def create_attempt(
        self,
        *,
        job_id: int,
        worker_id: str | None = None,
    ) -> PipelineJobAttemptRecord:
        now = datetime.now(UTC)
        attempt_no = sum(attempt.job_id == job_id for attempt in self.attempts.values()) + 1
        record = PipelineJobAttemptRecord(
            id=self.next_attempt_id,
            job_id=job_id,
            attempt_no=attempt_no,
            status="running",
            started_at=now,
            finished_at=None,
            worker_id=worker_id,
            error_type=None,
            error_message=None,
            output_json=None,
        )
        self.attempts[record.id] = record
        self.next_attempt_id += 1
        return record

    async def mark_attempt_succeeded(
        self,
        attempt_id: int,
        *,
        output_json: JsonObject,
    ) -> PipelineJobAttemptRecord:
        return self._update_attempt(
            attempt_id,
            status="succeeded",
            output_json=output_json,
            error_type=None,
            error_message=None,
        )

    async def mark_attempt_failed(
        self,
        attempt_id: int,
        *,
        error_type: str,
        error_message: str,
    ) -> PipelineJobAttemptRecord:
        return self._update_attempt(
            attempt_id,
            status="failed",
            output_json=None,
            error_type=error_type,
            error_message=error_message,
        )

    async def mark_job_succeeded(self, job_id: int) -> PipelineJobRecord:
        return self._update_job(job_id, status="succeeded")

    async def mark_job_failed(self, job_id: int) -> PipelineJobRecord:
        return self._update_job(job_id, status="failed")

    def _update_attempt(
        self,
        attempt_id: int,
        *,
        status: PipelineJobAttemptStatus,
        output_json: JsonObject | None,
        error_type: str | None,
        error_message: str | None,
    ) -> PipelineJobAttemptRecord:
        record = self.attempts[attempt_id]
        updated = replace(
            record,
            status=status,
            finished_at=datetime.now(UTC),
            output_json=output_json,
            error_type=error_type,
            error_message=error_message,
        )
        self.attempts[attempt_id] = updated
        return updated

    def _update_job(self, job_id: int, *, status: PipelineJobStatus) -> PipelineJobRecord:
        record = self.jobs[job_id]
        now = datetime.now(UTC)
        updated = replace(record, status=status, updated_at=now, completed_at=now)
        self.jobs[job_id] = updated
        return updated


class FakeStreamerRepository(StreamerRepositoryPort):
    def __init__(self) -> None:
        self.streamers: dict[int, StreamerRecord] = {}
        self.channels: dict[int, ChannelRecord] = {}
        self.next_streamer_id = 1
        self.next_channel_id = 1

    async def create_streamer(self, *, name: str) -> StreamerRecord:
        record = StreamerRecord(id=self.next_streamer_id, name=name)
        self.streamers[record.id] = record
        self.next_streamer_id += 1
        return record

    async def list_streamers(self) -> list[StreamerRecord]:
        return list(self.streamers.values())

    async def get_streamer(self, streamer_id: int) -> StreamerRecord | None:
        return self.streamers.get(streamer_id)

    async def update_streamer(self, streamer_id: int, *, name: str) -> StreamerRecord | None:
        record = self.streamers.get(streamer_id)
        if record is None:
            return None
        updated = replace(record, name=name)
        self.streamers[streamer_id] = updated
        return updated

    async def delete_streamer(self, streamer_id: int) -> bool:
        return self.streamers.pop(streamer_id, None) is not None

    async def create_channel(self, channel: ChannelCreate) -> ChannelRecord:
        record = ChannelRecord(
            id=self.next_channel_id,
            streamer_id=channel.streamer_id,
            handle=channel.handle,
            name=channel.name,
            youtube_channel_id=channel.youtube_channel_id,
            source_api_call_id=channel.source_api_call_id,
            source_job_id=channel.source_job_id,
        )
        self.channels[record.id] = record
        self.next_channel_id += 1
        return record

    async def list_channels(self, *, streamer_id: int | None = None) -> list[ChannelRecord]:
        records = list(self.channels.values())
        if streamer_id is None:
            return records
        return [record for record in records if record.streamer_id == streamer_id]

    async def get_channel(self, channel_id: int) -> ChannelRecord | None:
        return self.channels.get(channel_id)

    async def update_channel(
        self,
        channel_id: int,
        update: ChannelUpdate,
    ) -> ChannelRecord | None:
        record = self.channels.get(channel_id)
        if record is None:
            return None
        updated = replace(
            record,
            streamer_id=update.streamer_id if update.streamer_id else record.streamer_id,
            handle=update.handle if update.handle is not None else record.handle,
            name=update.name if update.name is not None else record.name,
            youtube_channel_id=(
                update.youtube_channel_id
                if update.youtube_channel_id_set
                else record.youtube_channel_id
            ),
        )
        self.channels[channel_id] = updated
        return updated

    async def delete_channel(self, channel_id: int) -> bool:
        return self.channels.pop(channel_id, None) is not None


def test_youtube_data_resolve_creates_one_channel_for_streamer() -> None:
    client = FakeYouTubeDataClient()
    repository = FakeStreamerRepository()
    pipeline_jobs = FakePipelineJobRepository()
    repository.streamers[1] = StreamerRecord(id=1, name="Google")

    response = asyncio.run(
        _request(
            client,
            repository,
            pipeline_jobs=pipeline_jobs,
            json={"streamerId": 1, "handle": " @GoogleDevelopers "},
            expected_status=201,
        )
    )

    assert response == {
        "channelId": 1,
        "streamerId": 1,
        "handle": "@GoogleDevelopers",
        "name": "Google for Developers",
        "youtubeChannelId": "UC_x5XG1OV2P6uZZ5FSM9Ttw",
        "sourceApiCallId": 42,
        "jobId": 1,
        "jobAttemptId": 1,
    }
    assert client.requests == [("@GoogleDevelopers", 1)]
    assert repository.channels[1] == ChannelRecord(
        id=1,
        streamer_id=1,
        handle="@GoogleDevelopers",
        name="Google for Developers",
        youtube_channel_id="UC_x5XG1OV2P6uZZ5FSM9Ttw",
        source_api_call_id=42,
        source_job_id=1,
    )
    assert pipeline_jobs.jobs[1].status == "succeeded"
    assert pipeline_jobs.jobs[1].step == "channel_resolve"
    assert pipeline_jobs.jobs[1].input_json == {
        "streamerId": 1,
        "handle": "@GoogleDevelopers",
    }
    assert pipeline_jobs.attempts[1].status == "succeeded"
    assert pipeline_jobs.attempts[1].output_json == response


def test_youtube_data_resolve_rejects_request_youtube_channel_id() -> None:
    client = FakeYouTubeDataClient()
    repository = FakeStreamerRepository()
    pipeline_jobs = FakePipelineJobRepository()
    repository.streamers[1] = StreamerRecord(id=1, name="Google")

    response = asyncio.run(
        _request(
            client,
            repository,
            pipeline_jobs=pipeline_jobs,
            json={
                "streamerId": 1,
                "handle": "@GoogleDevelopers",
                "youtubeChannelId": "UC-other",
            },
            expected_status=422,
        )
    )

    assert response["detail"][0]["type"] == "extra_forbidden"
    assert response["detail"][0]["loc"] == ["body", "youtubeChannelId"]
    assert repository.channels == {}
    assert pipeline_jobs.jobs == {}


def test_youtube_data_resolve_maps_missing_streamer_to_not_found() -> None:
    pipeline_jobs = FakePipelineJobRepository()

    response = asyncio.run(
        _request(
            FakeYouTubeDataClient(),
            FakeStreamerRepository(),
            pipeline_jobs=pipeline_jobs,
            json={"streamerId": 404, "handle": "@GoogleDevelopers"},
            expected_status=404,
        )
    )

    assert response == {"detail": "Streamer not found."}
    assert pipeline_jobs.jobs == {}


def test_youtube_data_resolve_maps_missing_channel_to_not_found() -> None:
    client = FakeYouTubeDataClient()
    client.error = YouTubeDataChannelNotFound("YouTube channel was not found for this handle.")
    repository = FakeStreamerRepository()
    pipeline_jobs = FakePipelineJobRepository()
    repository.streamers[1] = StreamerRecord(id=1, name="Missing")

    response = asyncio.run(
        _request(
            client,
            repository,
            pipeline_jobs=pipeline_jobs,
            json={"streamerId": 1, "handle": "@missing"},
            expected_status=404,
        )
    )

    assert response == {"detail": "YouTube channel was not found for this handle."}
    assert pipeline_jobs.jobs[1].status == "failed"
    assert pipeline_jobs.attempts[1].status == "failed"
    assert pipeline_jobs.attempts[1].error_type == "YouTubeDataChannelNotFound"


def test_youtube_data_resolve_maps_upstream_errors() -> None:
    client = FakeYouTubeDataClient()
    client.error = YouTubeDataUpstreamError("YouTube Data API request failed upstream.")
    repository = FakeStreamerRepository()
    pipeline_jobs = FakePipelineJobRepository()
    repository.streamers[1] = StreamerRecord(id=1, name="Blocked")

    response = asyncio.run(
        _request(
            client,
            repository,
            pipeline_jobs=pipeline_jobs,
            json={"streamerId": 1, "handle": "@blocked"},
            expected_status=502,
        )
    )

    assert response == {"detail": "YouTube Data API request failed upstream."}
    assert pipeline_jobs.jobs[1].status == "failed"
    assert pipeline_jobs.attempts[1].status == "failed"
    assert pipeline_jobs.attempts[1].error_type == "YouTubeDataUpstreamError"


def test_youtube_data_resolve_requires_api_key_configuration() -> None:
    repository = FakeStreamerRepository()
    pipeline_jobs = FakePipelineJobRepository()
    repository.streamers[1] = StreamerRecord(id=1, name="Google")

    response = asyncio.run(
        _request_without_client_override(
            repository,
            pipeline_jobs=pipeline_jobs,
            json={"streamerId": 1, "handle": "@GoogleDevelopers"},
            expected_status=503,
        )
    )

    assert response == {"detail": "YouTube Data API key is not configured."}
    assert pipeline_jobs.jobs == {}


def test_youtube_data_openapi_path_and_tag() -> None:
    app = create_app()
    schema = app.openapi()

    path_item = schema["paths"]["/youtube-data/channels/resolve"]
    request_schema = schema["components"]["schemas"]["ResolveYouTubeChannelRequest"]
    response_schema = schema["components"]["schemas"]["ResolveYouTubeChannelResponse"]

    assert path_item["post"]["tags"] == ["youtube-data"]
    assert set(request_schema["properties"]) == {"streamerId", "handle"}
    assert {"jobId", "jobAttemptId"}.issubset(response_schema["properties"])


async def _request(
    youtube_data_client: FakeYouTubeDataClient,
    repository: FakeStreamerRepository,
    *,
    pipeline_jobs: FakePipelineJobRepository | None = None,
    json: dict[str, Any],
    expected_status: int = 200,
) -> Any:
    if pipeline_jobs is None:
        pipeline_jobs = FakePipelineJobRepository()
    app = create_app()
    app.dependency_overrides[get_youtube_data_client] = lambda: youtube_data_client
    app.dependency_overrides[get_streamer_repository] = lambda: repository
    app.dependency_overrides[get_pipeline_job_repository] = lambda: pipeline_jobs

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post("/youtube-data/channels/resolve", json=json)

    assert response.status_code == expected_status, response.text
    return response.json()


async def _request_without_client_override(
    repository: FakeStreamerRepository,
    *,
    pipeline_jobs: FakePipelineJobRepository | None = None,
    json: dict[str, Any],
    expected_status: int = 200,
) -> Any:
    if pipeline_jobs is None:
        pipeline_jobs = FakePipelineJobRepository()
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: CliSettings(youtube_data_api_key=None)
    app.dependency_overrides[get_streamer_repository] = lambda: repository
    app.dependency_overrides[get_pipeline_job_repository] = lambda: pipeline_jobs

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post("/youtube-data/channels/resolve", json=json)

    assert response.status_code == expected_status, response.text
    return response.json()
