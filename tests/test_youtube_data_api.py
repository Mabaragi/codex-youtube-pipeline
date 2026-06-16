from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from httpx import ASGITransport, AsyncClient

from codex_sdk_cli.api.dependencies import (
    get_channel_repository,
    get_pipeline_job_repository,
    get_settings,
    get_streamer_repository,
    get_youtube_data_client,
)
from codex_sdk_cli.api.main import create_app
from codex_sdk_cli.domains.channels.exceptions import ChannelAlreadyExists
from codex_sdk_cli.domains.channels.ports import (
    ChannelCreate,
    ChannelRecord,
    ChannelRepositoryPort,
    ChannelUpdate,
)
from codex_sdk_cli.domains.pipeline_jobs.ports import (
    ExternalApiCallSummaryRecord,
    JsonObject,
    PipelineChannelOutputRecord,
    PipelineJobAttemptRecord,
    PipelineJobAttemptStatus,
    PipelineJobCreate,
    PipelineJobDetailRecord,
    PipelineJobListQuery,
    PipelineJobRecord,
    PipelineJobRepositoryPort,
    PipelineJobStatus,
    PipelineJobSummaryRecord,
)
from codex_sdk_cli.domains.streamers.ports import StreamerRecord, StreamerRepositoryPort
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
        self.external_api_calls: list[ExternalApiCallSummaryRecord] = []
        self.channels: list[PipelineChannelOutputRecord] = []
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

    async def get_job(self, job_id: int) -> PipelineJobRecord | None:
        return self.jobs.get(job_id)

    async def list_job_summaries(
        self,
        query: PipelineJobListQuery,
    ) -> list[PipelineJobSummaryRecord]:
        jobs = sorted(self.jobs.values(), key=lambda job: job.id, reverse=True)
        if query.step is not None:
            jobs = [job for job in jobs if job.step == query.step]
        if query.status is not None:
            jobs = [job for job in jobs if job.status == query.status]
        if query.subject_type is not None:
            jobs = [job for job in jobs if job.subject_type == query.subject_type]
        if query.subject_id is not None:
            jobs = [job for job in jobs if job.subject_id == query.subject_id]
        if query.external_key is not None:
            jobs = [job for job in jobs if job.external_key == query.external_key]
        if query.cursor is not None:
            jobs = [job for job in jobs if job.id < query.cursor]
        return [self._summary(job) for job in jobs[: query.limit]]

    async def get_job_detail(self, job_id: int) -> PipelineJobDetailRecord | None:
        job = self.jobs.get(job_id)
        if job is None:
            return None
        attempts = sorted(
            [attempt for attempt in self.attempts.values() if attempt.job_id == job_id],
            key=lambda attempt: attempt.attempt_no,
        )
        attempt_ids = {attempt.id for attempt in attempts}
        return PipelineJobDetailRecord(
            job=job,
            attempts=attempts,
            external_api_calls=[
                call
                for call in self.external_api_calls
                if call.pipeline_job_attempt_id in attempt_ids
            ],
            channels=[channel for channel in self.channels if channel.source_job_id == job_id],
        )

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

    async def mark_job_running(self, job_id: int) -> PipelineJobRecord:
        record = self.jobs[job_id]
        now = datetime.now(UTC)
        updated = replace(record, status="running", updated_at=now, completed_at=None)
        self.jobs[job_id] = updated
        return updated

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

    def _summary(self, job: PipelineJobRecord) -> PipelineJobSummaryRecord:
        attempts = sorted(
            [attempt for attempt in self.attempts.values() if attempt.job_id == job.id],
            key=lambda attempt: attempt.attempt_no,
        )
        latest = attempts[-1] if attempts else None
        return PipelineJobSummaryRecord(
            job=job,
            latest_attempt_id=latest.id if latest is not None else None,
            latest_attempt_status=latest.status if latest is not None else None,
            attempt_count=len(attempts),
        )


class FakeStreamerRepository(StreamerRepositoryPort):
    def __init__(self) -> None:
        self.streamers: dict[int, StreamerRecord] = {}
        self.next_streamer_id = 1

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


class FakeChannelRepository(ChannelRepositoryPort):
    def __init__(self) -> None:
        self.channels: dict[int, ChannelRecord] = {}
        self.next_channel_id = 1

    async def create_channel(self, channel: ChannelCreate) -> ChannelRecord:
        if channel.youtube_channel_id is not None:
            existing = await self.get_channel_by_youtube_channel_id(channel.youtube_channel_id)
            if existing is not None:
                raise ChannelAlreadyExists("YouTube channel already exists.")
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

    async def get_channel_by_youtube_channel_id(
        self,
        youtube_channel_id: str,
    ) -> ChannelRecord | None:
        return next(
            (
                record
                for record in self.channels.values()
                if record.youtube_channel_id == youtube_channel_id
            ),
            None,
        )

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
    streamers = FakeStreamerRepository()
    channels = FakeChannelRepository()
    pipeline_jobs = FakePipelineJobRepository()
    streamers.streamers[1] = StreamerRecord(id=1, name="Google")

    response = asyncio.run(
        _request(
            client,
            streamers,
            channels,
            streamer_id=1,
            pipeline_jobs=pipeline_jobs,
            json={"handle": " @GoogleDevelopers "},
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
    assert channels.channels[1] == ChannelRecord(
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
    streamers = FakeStreamerRepository()
    channels = FakeChannelRepository()
    pipeline_jobs = FakePipelineJobRepository()
    streamers.streamers[1] = StreamerRecord(id=1, name="Google")

    response = asyncio.run(
        _request(
            client,
            streamers,
            channels,
            streamer_id=1,
            pipeline_jobs=pipeline_jobs,
            json={
                "handle": "@GoogleDevelopers",
                "youtubeChannelId": "UC-other",
            },
            expected_status=422,
        )
    )

    assert response["detail"][0]["type"] == "extra_forbidden"
    assert response["detail"][0]["loc"] == ["body", "youtubeChannelId"]
    assert channels.channels == {}
    assert pipeline_jobs.jobs == {}


def test_youtube_data_resolve_maps_missing_streamer_to_not_found() -> None:
    pipeline_jobs = FakePipelineJobRepository()

    response = asyncio.run(
        _request(
            FakeYouTubeDataClient(),
            FakeStreamerRepository(),
            FakeChannelRepository(),
            streamer_id=404,
            pipeline_jobs=pipeline_jobs,
            json={"handle": "@GoogleDevelopers"},
            expected_status=404,
        )
    )

    assert response == {"detail": "Streamer not found."}
    assert pipeline_jobs.jobs == {}


def test_youtube_data_resolve_maps_missing_channel_to_not_found() -> None:
    client = FakeYouTubeDataClient()
    client.error = YouTubeDataChannelNotFound("YouTube channel was not found for this handle.")
    streamers = FakeStreamerRepository()
    channels = FakeChannelRepository()
    pipeline_jobs = FakePipelineJobRepository()
    streamers.streamers[1] = StreamerRecord(id=1, name="Missing")

    response = asyncio.run(
        _request(
            client,
            streamers,
            channels,
            streamer_id=1,
            pipeline_jobs=pipeline_jobs,
            json={"handle": "@missing"},
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
    streamers = FakeStreamerRepository()
    channels = FakeChannelRepository()
    pipeline_jobs = FakePipelineJobRepository()
    streamers.streamers[1] = StreamerRecord(id=1, name="Blocked")

    response = asyncio.run(
        _request(
            client,
            streamers,
            channels,
            streamer_id=1,
            pipeline_jobs=pipeline_jobs,
            json={"handle": "@blocked"},
            expected_status=502,
        )
    )

    assert response == {"detail": "YouTube Data API request failed upstream."}
    assert pipeline_jobs.jobs[1].status == "failed"
    assert pipeline_jobs.attempts[1].status == "failed"
    assert pipeline_jobs.attempts[1].error_type == "YouTubeDataUpstreamError"


def test_youtube_data_resolve_requires_api_key_configuration() -> None:
    streamers = FakeStreamerRepository()
    channels = FakeChannelRepository()
    pipeline_jobs = FakePipelineJobRepository()
    streamers.streamers[1] = StreamerRecord(id=1, name="Google")

    response = asyncio.run(
        _request_without_client_override(
            streamers,
            channels,
            streamer_id=1,
            pipeline_jobs=pipeline_jobs,
            json={"handle": "@GoogleDevelopers"},
            expected_status=503,
        )
    )

    assert response == {"detail": "YouTube Data API key is not configured."}
    assert pipeline_jobs.jobs == {}


def test_youtube_data_resolve_reuses_existing_channel_for_same_streamer() -> None:
    client = FakeYouTubeDataClient()
    streamers = FakeStreamerRepository()
    channels = FakeChannelRepository()
    pipeline_jobs = FakePipelineJobRepository()
    streamers.streamers[1] = StreamerRecord(id=1, name="Google")
    channels.channels[7] = ChannelRecord(
        id=7,
        streamer_id=1,
        handle="@GoogleDevelopers",
        name="Google for Developers",
        youtube_channel_id="UC_x5XG1OV2P6uZZ5FSM9Ttw",
        source_api_call_id=11,
        source_job_id=99,
    )
    channels.next_channel_id = 8

    response = asyncio.run(
        _request(
            client,
            streamers,
            channels,
            streamer_id=1,
            pipeline_jobs=pipeline_jobs,
            json={"handle": "@GoogleDevelopers"},
            expected_status=201,
        )
    )

    assert response["channelId"] == 7
    assert response["sourceApiCallId"] == 42
    assert len(channels.channels) == 1
    assert pipeline_jobs.attempts[1].output_json == response


def test_youtube_data_resolve_rejects_existing_channel_for_other_streamer() -> None:
    client = FakeYouTubeDataClient()
    streamers = FakeStreamerRepository()
    channels = FakeChannelRepository()
    pipeline_jobs = FakePipelineJobRepository()
    streamers.streamers[1] = StreamerRecord(id=1, name="Google")
    streamers.streamers[2] = StreamerRecord(id=2, name="Other")
    channels.channels[7] = ChannelRecord(
        id=7,
        streamer_id=1,
        handle="@GoogleDevelopers",
        name="Google for Developers",
        youtube_channel_id="UC_x5XG1OV2P6uZZ5FSM9Ttw",
        source_api_call_id=11,
        source_job_id=99,
    )
    channels.next_channel_id = 8

    response = asyncio.run(
        _request(
            client,
            streamers,
            channels,
            streamer_id=2,
            pipeline_jobs=pipeline_jobs,
            json={"handle": "@GoogleDevelopers"},
            expected_status=409,
        )
    )

    assert response == {"detail": "YouTube channel already belongs to another streamer."}
    assert pipeline_jobs.jobs[1].status == "failed"
    assert pipeline_jobs.attempts[1].status == "failed"
    assert pipeline_jobs.attempts[1].error_type == "ChannelAlreadyExists"


def test_pipeline_retry_retries_failed_channel_resolve_job() -> None:
    client = FakeYouTubeDataClient()
    streamers = FakeStreamerRepository()
    channels = FakeChannelRepository()
    pipeline_jobs = FakePipelineJobRepository()
    streamers.streamers[1] = StreamerRecord(id=1, name="Google")
    _seed_channel_resolve_job(pipeline_jobs, status="failed")
    _seed_failed_attempt(pipeline_jobs, job_id=1)

    response = asyncio.run(
        _retry_request(
            client,
            streamers,
            channels,
            pipeline_jobs,
            job_id=1,
            expected_status=201,
        )
    )

    expected_result = {
        "channelId": 1,
        "streamerId": 1,
        "handle": "@GoogleDevelopers",
        "name": "Google for Developers",
        "youtubeChannelId": "UC_x5XG1OV2P6uZZ5FSM9Ttw",
        "sourceApiCallId": 42,
        "jobId": 1,
        "jobAttemptId": 2,
    }
    assert response == {
        "jobId": 1,
        "jobAttemptId": 2,
        "step": "channel_resolve",
        "status": "succeeded",
        "result": expected_result,
    }
    assert client.requests == [("@GoogleDevelopers", 2)]
    assert channels.channels[1].source_job_id == 1
    assert pipeline_jobs.jobs[1].status == "succeeded"
    assert pipeline_jobs.attempts[2].status == "succeeded"
    assert pipeline_jobs.attempts[2].output_json == expected_result


def test_pipeline_retry_rejects_non_failed_job() -> None:
    client = FakeYouTubeDataClient()
    streamers = FakeStreamerRepository()
    channels = FakeChannelRepository()
    pipeline_jobs = FakePipelineJobRepository()
    _seed_channel_resolve_job(pipeline_jobs, status="succeeded")

    response = asyncio.run(
        _retry_request(
            client,
            streamers,
            channels,
            pipeline_jobs,
            job_id=1,
            expected_status=409,
        )
    )

    assert response == {"detail": "Only failed pipeline jobs can be retried."}
    assert pipeline_jobs.attempts == {}


def test_pipeline_retry_maps_missing_job_to_not_found() -> None:
    response = asyncio.run(
        _retry_request(
            FakeYouTubeDataClient(),
            FakeStreamerRepository(),
            FakeChannelRepository(),
            FakePipelineJobRepository(),
            job_id=404,
            expected_status=404,
        )
    )

    assert response == {"detail": "Pipeline job not found."}


def test_pipeline_retry_records_failed_attempt_on_upstream_error() -> None:
    client = FakeYouTubeDataClient()
    client.error = YouTubeDataUpstreamError("YouTube Data API request failed upstream.")
    streamers = FakeStreamerRepository()
    channels = FakeChannelRepository()
    pipeline_jobs = FakePipelineJobRepository()
    streamers.streamers[1] = StreamerRecord(id=1, name="Blocked")
    _seed_channel_resolve_job(pipeline_jobs, status="failed")

    response = asyncio.run(
        _retry_request(
            client,
            streamers,
            channels,
            pipeline_jobs,
            job_id=1,
            expected_status=502,
        )
    )

    assert response == {"detail": "YouTube Data API request failed upstream."}
    assert pipeline_jobs.jobs[1].status == "failed"
    assert pipeline_jobs.attempts[1].status == "failed"
    assert pipeline_jobs.attempts[1].error_type == "YouTubeDataUpstreamError"


def test_pipeline_jobs_list_filters_and_paginates_operational_summary() -> None:
    pipeline_jobs = FakePipelineJobRepository()
    _seed_channel_resolve_job(pipeline_jobs, status="failed")
    _seed_failed_attempt(pipeline_jobs, job_id=1)
    _seed_channel_resolve_job(pipeline_jobs, job_id=2, status="succeeded", handle="@Other")
    pipeline_jobs.attempts[2] = replace(
        pipeline_jobs.attempts[1],
        id=2,
        job_id=2,
        status="succeeded",
        error_type=None,
        error_message=None,
    )

    failed_response = asyncio.run(
        _pipeline_request(
            pipeline_jobs,
            "GET",
            "/pipeline/jobs?status=failed&limit=1",
        )
    )
    next_page = asyncio.run(
        _pipeline_request(
            pipeline_jobs,
            "GET",
            "/pipeline/jobs?limit=1",
        )
    )

    assert failed_response["nextCursor"] is None
    assert failed_response["items"] == [
        {
            "jobId": 1,
            "step": "channel_resolve",
            "status": "failed",
            "subjectType": "streamer",
            "subjectId": 1,
            "externalKey": "@GoogleDevelopers",
            "createdAt": failed_response["items"][0]["createdAt"],
            "updatedAt": failed_response["items"][0]["updatedAt"],
            "completedAt": failed_response["items"][0]["completedAt"],
            "latestAttemptId": 1,
            "latestAttemptStatus": "failed",
            "attemptCount": 1,
        }
    ]
    assert next_page["items"][0]["jobId"] == 2
    assert next_page["nextCursor"] == 2


def test_pipeline_job_detail_returns_attempts_raw_calls_and_outputs() -> None:
    pipeline_jobs = FakePipelineJobRepository()
    _seed_channel_resolve_job(pipeline_jobs, status="failed")
    _seed_failed_attempt(pipeline_jobs, job_id=1)
    _seed_external_api_call(pipeline_jobs)
    pipeline_jobs.channels.append(
        PipelineChannelOutputRecord(
            id=7,
            streamer_id=1,
            handle="@GoogleDevelopers",
            name="Google for Developers",
            youtube_channel_id="UC_x5XG1OV2P6uZZ5FSM9Ttw",
            source_api_call_id=42,
            source_job_id=1,
        )
    )

    response = asyncio.run(
        _pipeline_request(
            pipeline_jobs,
            "GET",
            "/pipeline/jobs/1",
        )
    )

    assert response["jobId"] == 1
    assert response["inputJson"] == {"streamerId": 1, "handle": "@GoogleDevelopers"}
    assert response["attempts"][0]["jobAttemptId"] == 1
    assert response["attempts"][0]["errorType"] == "YouTubeDataUpstreamError"
    assert response["externalApiCalls"][0]["externalApiCallId"] == 42
    assert response["externalApiCalls"][0]["jobAttemptId"] == 1
    assert response["channels"][0]["channelId"] == 7


def test_pipeline_job_detail_maps_missing_job_to_not_found() -> None:
    response = asyncio.run(
        _pipeline_request(
            FakePipelineJobRepository(),
            "GET",
            "/pipeline/jobs/404",
            expected_status=404,
        )
    )

    assert response == {"detail": "Pipeline job not found."}


def test_channel_resolve_openapi_path_and_tag() -> None:
    app = create_app()
    schema = app.openapi()

    path_item = schema["paths"]["/streamers/{streamer_id}/channels/resolve"]
    list_path_item = schema["paths"]["/pipeline/jobs"]
    detail_path_item = schema["paths"]["/pipeline/jobs/{job_id}"]
    retry_path_item = schema["paths"]["/pipeline/jobs/{job_id}/retry"]
    request_schema = schema["components"]["schemas"]["ResolveYouTubeChannelRequest"]
    response_schema = schema["components"]["schemas"]["ResolveYouTubeChannelResponse"]

    assert "/youtube-data/channels/resolve" not in schema["paths"]
    assert path_item["post"]["tags"] == ["channels"]
    assert list_path_item["get"]["tags"] == ["pipeline-jobs"]
    assert detail_path_item["get"]["tags"] == ["pipeline-jobs"]
    assert retry_path_item["post"]["tags"] == ["pipeline-jobs"]
    assert set(request_schema["properties"]) == {"handle"}
    assert {"jobId", "jobAttemptId"}.issubset(response_schema["properties"])


def test_legacy_youtube_data_resolve_path_is_removed() -> None:
    response = asyncio.run(_legacy_resolve_request())

    assert response == {"detail": "Not Found"}


async def _request(
    youtube_data_client: FakeYouTubeDataClient,
    streamers: FakeStreamerRepository,
    channels: FakeChannelRepository,
    *,
    streamer_id: int,
    pipeline_jobs: FakePipelineJobRepository | None = None,
    json: dict[str, Any],
    expected_status: int = 200,
) -> Any:
    if pipeline_jobs is None:
        pipeline_jobs = FakePipelineJobRepository()
    app = create_app()
    app.dependency_overrides[get_youtube_data_client] = lambda: youtube_data_client
    app.dependency_overrides[get_streamer_repository] = lambda: streamers
    app.dependency_overrides[get_channel_repository] = lambda: channels
    app.dependency_overrides[get_pipeline_job_repository] = lambda: pipeline_jobs

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            f"/streamers/{streamer_id}/channels/resolve",
            json=json,
        )

    assert response.status_code == expected_status, response.text
    return response.json()


async def _legacy_resolve_request() -> Any:
    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/youtube-data/channels/resolve",
            json={"streamerId": 1, "handle": "@GoogleDevelopers"},
        )

    assert response.status_code == 404, response.text
    return response.json()


async def _request_without_client_override(
    streamers: FakeStreamerRepository,
    channels: FakeChannelRepository,
    *,
    streamer_id: int,
    pipeline_jobs: FakePipelineJobRepository | None = None,
    json: dict[str, Any],
    expected_status: int = 200,
) -> Any:
    if pipeline_jobs is None:
        pipeline_jobs = FakePipelineJobRepository()
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: CliSettings(youtube_data_api_key=None)
    app.dependency_overrides[get_streamer_repository] = lambda: streamers
    app.dependency_overrides[get_channel_repository] = lambda: channels
    app.dependency_overrides[get_pipeline_job_repository] = lambda: pipeline_jobs

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            f"/streamers/{streamer_id}/channels/resolve",
            json=json,
        )

    assert response.status_code == expected_status, response.text
    return response.json()


async def _retry_request(
    youtube_data_client: FakeYouTubeDataClient,
    streamers: FakeStreamerRepository,
    channels: FakeChannelRepository,
    pipeline_jobs: FakePipelineJobRepository,
    *,
    job_id: int,
    expected_status: int = 200,
) -> Any:
    app = create_app()
    app.dependency_overrides[get_youtube_data_client] = lambda: youtube_data_client
    app.dependency_overrides[get_streamer_repository] = lambda: streamers
    app.dependency_overrides[get_channel_repository] = lambda: channels
    app.dependency_overrides[get_pipeline_job_repository] = lambda: pipeline_jobs

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(f"/pipeline/jobs/{job_id}/retry")

    assert response.status_code == expected_status, response.text
    return response.json()


async def _pipeline_request(
    pipeline_jobs: FakePipelineJobRepository,
    method: str,
    path: str,
    *,
    expected_status: int = 200,
) -> Any:
    app = create_app()
    app.dependency_overrides[get_pipeline_job_repository] = lambda: pipeline_jobs

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.request(method, path)

    assert response.status_code == expected_status, response.text
    return response.json()


def _seed_channel_resolve_job(
    pipeline_jobs: FakePipelineJobRepository,
    *,
    job_id: int = 1,
    status: PipelineJobStatus,
    handle: str = "@GoogleDevelopers",
) -> None:
    now = datetime.now(UTC)
    pipeline_jobs.jobs[job_id] = PipelineJobRecord(
        id=job_id,
        step="channel_resolve",
        status=status,
        subject_type="streamer",
        subject_id=1,
        external_key=handle,
        input_json={"streamerId": 1, "handle": handle},
        input_hash="0" * 64,
        parent_job_id=None,
        created_at=now,
        updated_at=now,
        completed_at=now if status != "running" else None,
    )
    pipeline_jobs.next_job_id = max(pipeline_jobs.next_job_id, job_id + 1)


def _seed_failed_attempt(pipeline_jobs: FakePipelineJobRepository, *, job_id: int) -> None:
    now = datetime.now(UTC)
    pipeline_jobs.attempts[1] = PipelineJobAttemptRecord(
        id=1,
        job_id=job_id,
        attempt_no=1,
        status="failed",
        started_at=now,
        finished_at=now,
        worker_id=None,
        error_type="YouTubeDataUpstreamError",
        error_message="upstream failed",
        output_json=None,
    )
    pipeline_jobs.next_attempt_id = 2


def _seed_external_api_call(pipeline_jobs: FakePipelineJobRepository) -> None:
    pipeline_jobs.external_api_calls.append(
        ExternalApiCallSummaryRecord(
            id=42,
            pipeline_job_attempt_id=1,
            provider="youtube_data",
            operation="channels.list",
            response_status_code=500,
            validation_status="not_validated",
            response_storage_uri="s3://raw/external-api-calls/object.json",
            duration_ms=123,
            quota_cost=1,
            created_at=datetime.now(UTC),
        )
    )
