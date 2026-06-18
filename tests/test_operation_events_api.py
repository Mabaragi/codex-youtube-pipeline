from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from httpx import ASGITransport, AsyncClient

from codex_sdk_cli.api.dependencies import get_operation_event_repository
from codex_sdk_cli.api.main import create_app
from codex_sdk_cli.domains.operation_events.ports import (
    OperationEventCreate,
    OperationEventListQuery,
    OperationEventRecord,
    OperationEventRepositoryPort,
)


class FakeOperationEventRepository(OperationEventRepositoryPort):
    def __init__(self) -> None:
        self.queries: list[OperationEventListQuery] = []

    async def create_event(self, event: OperationEventCreate) -> OperationEventRecord:
        raise NotImplementedError

    async def list_events(self, query: OperationEventListQuery) -> list[OperationEventRecord]:
        self.queries.append(query)
        return [
            OperationEventRecord(
                id=12,
                occurred_at=datetime.now(UTC),
                event_type="video_collect.failed",
                severity="error",
                message="Channel video collection failed.",
                actor_type="manual_api",
                source="videos.collect",
                metadata_json={"attemptId": 1},
                job_id=1,
                job_attempt_id=1,
                video_task_id=None,
                channel_id=2,
                video_id=None,
                external_api_call_id=None,
                subject_type="channel",
                subject_id=2,
                external_key="UC123",
                correlation_id=None,
                error_type="UpstreamError",
                error_message="failed",
            )
        ]


def test_ops_events_are_filterable() -> None:
    asyncio.run(_test_ops_events_are_filterable())


async def _test_ops_events_are_filterable() -> None:
    event_repository = FakeOperationEventRepository()
    app = create_app()
    app.dependency_overrides[get_operation_event_repository] = lambda: event_repository

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            "/ops/events",
            params={"severity": "error", "eventType": "video_collect.failed", "jobId": 1},
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["items"][0]["eventType"] == "video_collect.failed"
    assert payload["items"][0]["metadata"] == {"attemptId": 1}
    assert event_repository.queries[0].severity == "error"
    assert event_repository.queries[0].event_type == "video_collect.failed"
    assert event_repository.queries[0].job_id == 1


def test_operation_event_route_is_in_openapi() -> None:
    schema = create_app().openapi()

    assert schema["paths"]["/ops/events"]["get"]["tags"] == ["ops"]
    assert "OperationEventListResponse" in schema["components"]["schemas"]

