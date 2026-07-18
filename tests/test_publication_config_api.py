from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

from httpx import ASGITransport, AsyncClient

from codex_sdk_cli.api.dependencies import (
    get_operation_event_recorder,
    get_publish_configuration_repository,
)
from codex_sdk_cli.api.main import create_app
from codex_sdk_cli.api.use_case_dependencies.publication import (
    get_publication_connection_registry,
)
from codex_sdk_cli.application.publication_config.ports import (
    CreateCatalogDestination,
    CreateObjectDestination,
    CreatePublishProfile,
)
from codex_sdk_cli.domains.operation_events.ports import OperationEventCreate
from codex_sdk_cli.domains.publication_config.models import (
    PublishCatalogDestination,
    PublishObjectDestination,
    PublishProfile,
    PublishProfileDetail,
)
from codex_sdk_cli.infra.publication.connections import PublicationConnectionRegistry


class FakePublishConfigurationRepository:
    def __init__(self) -> None:
        self._profiles: dict[int, PublishProfile] = {}
        self._object_destinations: dict[int, PublishObjectDestination] = {}
        self._catalog_destinations: dict[int, PublishCatalogDestination] = {}
        self._next_profile_id = 1

    async def create_object_destination(
        self,
        create: CreateObjectDestination,
    ) -> PublishObjectDestination:
        destination = PublishObjectDestination(
            id=len(self._object_destinations) + 1,
            key=create.key,
            name=create.name,
            connection_ref=create.connection_ref,
            created_at=datetime.now(UTC),
        )
        self._object_destinations[destination.id] = destination
        return destination

    async def create_catalog_destination(
        self,
        create: CreateCatalogDestination,
    ) -> PublishCatalogDestination:
        destination = PublishCatalogDestination(
            id=len(self._catalog_destinations) + 1,
            key=create.key,
            name=create.name,
            connection_ref=create.connection_ref,
            created_at=datetime.now(UTC),
        )
        self._catalog_destinations[destination.id] = destination
        return destination

    async def create_profile(self, create: CreatePublishProfile) -> PublishProfile:
        profile = PublishProfile(
            id=self._next_profile_id,
            key=create.key,
            name=create.name,
            description=create.description,
            active_revision_id=None,
            created_at=datetime.now(UTC),
        )
        self._profiles[profile.id] = profile
        self._next_profile_id += 1
        return profile

    async def list_profiles(self) -> list[PublishProfile]:
        return list(self._profiles.values())

    async def get_profile(self, profile_id: int) -> PublishProfileDetail | None:
        profile = self._profiles.get(profile_id)
        if profile is None:
            return None
        return PublishProfileDetail(profile=profile, revisions=())


class FakeOperationEventRecorder:
    def __init__(self) -> None:
        self.events: list[OperationEventCreate] = []

    async def record_event(self, event: OperationEventCreate) -> None:
        self.events.append(event)


def test_publication_profile_routes_use_config_dependency_and_map_not_found() -> None:
    repository = FakePublishConfigurationRepository()
    recorder = FakeOperationEventRecorder()

    created = asyncio.run(
        _request(
            repository,
            recorder,
            "POST",
            "/ops/publish/profiles",
            json={"key": "creator-profile", "name": "Creator profile"},
            expected_status=201,
        )
    )
    assert created["key"] == "creator-profile"
    assert created["activeRevisionId"] is None
    assert recorder.events[0].subject_type == "publish_profile"

    listed = asyncio.run(_request(repository, recorder, "GET", "/ops/publish/profiles"))
    assert listed == [created]

    missing = asyncio.run(
        _request(
            repository,
            recorder,
            "GET",
            "/ops/publish/profiles/999",
            expected_status=404,
        )
    )
    assert missing == {
        "error": {
            "code": "publish_configuration_not_found",
            "message": "Publish profile not found.",
            "details": None,
        }
    }


def test_destination_creation_requires_safe_compatible_registry_connection() -> None:
    repository = FakePublishConfigurationRepository()
    recorder = FakeOperationEventRecorder()
    registry = _connection_registry()

    created_object = asyncio.run(
        _request(
            repository,
            recorder,
            "POST",
            "/ops/publish/object-destinations",
            registry=registry,
            json={
                "key": "public-object",
                "name": "Public object",
                "connectionRef": "object-store",
            },
            expected_status=201,
        )
    )
    assert created_object["connectionRef"] == "object-store"

    for key, connection_ref in (
        ("http-catalog-destination", "http-catalog"),
        ("sql-catalog-destination", "sql-catalog"),
    ):
        created_catalog = asyncio.run(
            _request(
                repository,
                recorder,
                "POST",
                "/ops/publish/catalog-destinations",
                registry=registry,
                json={
                    "key": key,
                    "name": key,
                    "connectionRef": connection_ref,
                },
                expected_status=201,
            )
        )
        assert created_catalog["connectionRef"] == connection_ref

    rejected = (
        (
            "/ops/publish/object-destinations",
            "wrong-object-kind",
            "sql-catalog",
            "connectionRef must reference a s3_compatible_object connection.",
        ),
        (
            "/ops/publish/catalog-destinations",
            "wrong-catalog-kind",
            "object-store",
            "connectionRef must reference a sql_catalog or http_catalog connection.",
        ),
        (
            "/ops/publish/object-destinations",
            "missing-connection",
            "missing-object-store",
            "connectionRef is not configured in the publication connection registry.",
        ),
        (
            "/ops/publish/object-destinations",
            "secret-shaped-dsn",
            "postgresql://operator:DB_PASSWORD@db/catalog",
            "connectionRef must be a safe publication connection registry identifier.",
        ),
        (
            "/ops/publish/catalog-destinations",
            "secret-shaped-token",
            "Bearer TOKEN_SECRET",
            "connectionRef must be a safe publication connection registry identifier.",
        ),
    )
    for path, key, connection_ref, expected_message in rejected:
        response = asyncio.run(
            _request(
                repository,
                recorder,
                "POST",
                path,
                registry=registry,
                json={"key": key, "name": key, "connectionRef": connection_ref},
                expected_status=400,
            )
        )
        assert response == {
            "error": {
                "code": "publish_configuration_invalid_connection",
                "message": expected_message,
                "details": None,
            }
        }
        assert "DB_PASSWORD" not in json.dumps(response)
        assert "TOKEN_SECRET" not in json.dumps(response)

    assert len(repository._object_destinations) == 1
    assert len(repository._catalog_destinations) == 2
    assert len(recorder.events) == 3


async def _request(
    repository: FakePublishConfigurationRepository,
    recorder: FakeOperationEventRecorder,
    method: str,
    path: str,
    *,
    registry: PublicationConnectionRegistry | None = None,
    json: dict[str, Any] | None = None,
    expected_status: int = 200,
) -> Any:
    app = create_app()
    app.dependency_overrides[get_publish_configuration_repository] = lambda: repository
    app.dependency_overrides[get_operation_event_recorder] = lambda: recorder
    if registry is not None:
        app.dependency_overrides[get_publication_connection_registry] = lambda: registry
    headers = {"X-Operator-Reason": "publication profile test"} if method == "POST" else None
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.request(method, path, json=json, headers=headers)

    assert response.status_code == expected_status, response.text
    return response.json()


def _connection_registry() -> PublicationConnectionRegistry:
    return PublicationConnectionRegistry.model_validate(
        {
            "connections": {
                "object-store": {
                    "kind": "s3_compatible_object",
                    "endpoint": "http://127.0.0.1:9000",
                    "accessKey": "access",
                    "secretKey": "secret",
                    "bucket": "archive-public",
                    "secure": False,
                    "publicBaseUrl": "http://127.0.0.1:9000/archive-public",
                },
                "http-catalog": {
                    "kind": "http_catalog",
                    "url": "https://catalog.example.test/upsert",
                    "token": "secret",
                },
                "sql-catalog": {
                    "kind": "sql_catalog",
                    "databaseUrl": "sqlite+aiosqlite:///catalog.db",
                },
            }
        }
    )
