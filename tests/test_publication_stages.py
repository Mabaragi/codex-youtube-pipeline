from __future__ import annotations

import asyncio
import hashlib
import json
from contextlib import asynccontextmanager
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from codex_sdk_cli.api.schemas.publication_stages import PublicationPointerStageRequest
from codex_sdk_cli.application.publication.errors import PublicationStagePreconditionFailed
from codex_sdk_cli.application.publication.models import PublicationMembershipAuthorization
from codex_sdk_cli.application.publication_config.ports import (
    ResolvedCatalogBinding,
    ResolvedObjectBinding,
    ResolvedPublishRoute,
)
from codex_sdk_cli.domains.archive_publish.checkpoints import (
    ArtifactPublishProfileAssignment,
    CatalogDeliveryRecord,
    CatalogDeliveryUpsert,
    ObjectDeliveryRecord,
    ObjectDeliveryUpsert,
    PublicationDeliveryRecord,
    PublicationDeliveryUpsert,
    PublicationRecord,
    PublicationStatus,
    PublicationUpsert,
)
from codex_sdk_cli.domains.archive_publish.ports import ArchiveVideoArtifactRecord
from codex_sdk_cli.domains.publication.ports import (
    PublicationCatalogContext,
    PublicationObjectLocation,
    PublicationObjectStat,
)
from codex_sdk_cli.infra.archive_publish.checkpoints import (
    ArchiveArtifactCatalogDeliveryModel,
    ArchiveArtifactObjectDeliveryModel,
    ArchivePublicationDeliveryModel,
    ArchivePublicationModel,
    SqlAlchemyArchivePublicationCheckpointRepository,
)
from codex_sdk_cli.infra.archive_publish.repository import ArchiveVideoArtifactModel
from codex_sdk_cli.infra.channels.repository import ChannelModel
from codex_sdk_cli.infra.database.session import create_database_engine, create_session_factory
from codex_sdk_cli.infra.publication.stages import PublicationStageService
from codex_sdk_cli.infra.publication_config.repository import PublishProfileRevisionModel
from codex_sdk_cli.infra.streamers.repository import StreamerModel
from codex_sdk_cli.infra.videos.repository import VideoModel


class FakeObjectStore:
    def __init__(self, name: str, writes: list[tuple[str, str]]) -> None:
        self.name = name
        self.objects: dict[str, bytes] = {}
        self.writes = writes
        self.fail_once_keys: set[str] = set()
        self.fail_once_fragments: set[str] = set()

    def public_url(self, object_key: str) -> str:
        return f"https://{self.name}.example/{object_key.lstrip('/')}"

    async def put_bytes(
        self,
        *,
        object_key: str,
        payload: bytes,
        content_type: str = "application/octet-stream",
        cache_control: str | None = None,
    ) -> PublicationObjectLocation:
        del content_type, cache_control
        matching_fragment = next(
            (fragment for fragment in self.fail_once_fragments if fragment in object_key),
            None,
        )
        if object_key in self.fail_once_keys or matching_fragment is not None:
            self.fail_once_keys.discard(object_key)
            if matching_fragment is not None:
                self.fail_once_fragments.remove(matching_fragment)
            raise OSError(f"planned failure: {self.name}:{object_key}")
        self.objects[object_key] = payload
        self.writes.append((self.name, object_key))
        return PublicationObjectLocation(
            bucket=self.name,
            object_key=object_key,
            public_url=self.public_url(object_key),
        )

    async def get_bytes(self, *, object_key: str) -> bytes:
        return self.objects[object_key]

    async def stat_object(self, *, object_key: str) -> PublicationObjectStat | None:
        payload = self.objects.get(object_key)
        if payload is None:
            return None
        return PublicationObjectStat(
            bucket=self.name,
            object_key=object_key,
            byte_size=len(payload),
            etag=None,
            last_modified=None,
        )


class FakeCatalogPublisher:
    def __init__(self) -> None:
        self.calls: list[tuple[PublicationCatalogContext, int, str]] = []
        self.reconciliations: list[tuple[PublicationCatalogContext, str, tuple[Any, ...]]] = []
        self.fail_once = False

    async def upsert_video(self, context: Any, row: Any) -> None:
        if self.fail_once:
            self.fail_once = False
            raise OSError("planned catalog failure")
        self.calls.append((context, row.video_id, row.timeline_url))

    async def reconcile_videos(
        self,
        context: PublicationCatalogContext,
        *,
        environment: str,
        retained: tuple[Any, ...],
    ) -> None:
        self.reconciliations.append((context, environment, retained))


class FakeConnectionFactory:
    def __init__(
        self,
        stores: dict[str, FakeObjectStore],
        catalogs: dict[str, FakeCatalogPublisher],
    ) -> None:
        self.stores = stores
        self.catalogs = catalogs

    def object_store(self, connection_ref: str) -> FakeObjectStore:
        return self.stores[connection_ref]

    def catalog_publisher(self, connection_ref: str) -> FakeCatalogPublisher:
        return self.catalogs[connection_ref]

    def catalog_reconciler(self, connection_ref: str) -> FakeCatalogPublisher:
        return self.catalogs[connection_ref]


class FakeConfiguration:
    def __init__(self, route: ResolvedPublishRoute) -> None:
        self.route = route

    async def resolve_active_route(self, **_: object) -> ResolvedPublishRoute:
        return self.route

    async def resolve_revision_route(self, **_: object) -> ResolvedPublishRoute:
        return self.route

    async def get_route(self, route_id: int) -> ResolvedPublishRoute | None:
        return self.route if route_id == self.route.route_id else None


class FakeCheckpoints:
    def __init__(self, artifact: ArchiveVideoArtifactRecord) -> None:
        self.artifacts = {artifact.id: artifact}
        self.objects: dict[tuple[int, int], ObjectDeliveryRecord] = {}
        self.catalogs: dict[tuple[int, int], CatalogDeliveryRecord] = {}
        self.publications: dict[int, PublicationRecord] = {}
        self.publication_artifacts: dict[int, tuple[int, ...]] = {}
        self.publication_deliveries: dict[tuple[int, int], PublicationDeliveryRecord] = {}
        self.newer_pointer_bindings: set[int] = set()
        self.assignments = {
            artifact.id: ArtifactPublishProfileAssignment(
                artifact_id=artifact.id,
                streamer_id=3,
                publish_profile_id=1,
            )
        }

    async def get_artifacts(
        self, artifact_ids: tuple[int, ...]
    ) -> list[ArchiveVideoArtifactRecord]:
        return [self.artifacts[value] for value in artifact_ids if value in self.artifacts]

    async def get_artifact_publish_profile_assignments(
        self,
        artifact_ids: tuple[int, ...],
    ) -> tuple[ArtifactPublishProfileAssignment, ...]:
        return tuple(
            self.assignments[artifact_id]
            for artifact_id in artifact_ids
            if artifact_id in self.assignments
        )

    async def set_artifact_canonical(
        self,
        *,
        artifact_id: int,
        build_key: str,
        store_ref: str,
        artifact_key: str,
    ) -> None:
        self.artifacts[artifact_id] = replace(
            self.artifacts[artifact_id],
            build_key=build_key,
            artifact_status="ready",
            artifact_store_ref=store_ref,
            artifact_key=artifact_key,
            unavailable_code=None,
            unavailable_detail=None,
        )

    async def set_artifact_unavailable(self, **_: object) -> None:
        raise AssertionError("not used")

    async def set_artifact_failed(
        self,
        *,
        artifact_id: int,
        code: str,
        detail: str,
    ) -> None:
        self.artifacts[artifact_id] = replace(
            self.artifacts[artifact_id],
            artifact_status="failed",
            artifact_store_ref=None,
            artifact_key=None,
            unavailable_code=code,
            unavailable_detail=detail,
        )

    async def get_object_delivery(
        self, *, artifact_id: int, object_binding_id: int
    ) -> ObjectDeliveryRecord | None:
        return self.objects.get((artifact_id, object_binding_id))

    async def upsert_object_delivery(self, delivery: ObjectDeliveryUpsert) -> ObjectDeliveryRecord:
        key = (delivery.artifact_id, delivery.object_binding_id)
        previous = self.objects.get(key)
        record = ObjectDeliveryRecord(
            **asdict(delivery),
            id=previous.id if previous else len(self.objects) + 1,
            attempt_count=(previous.attempt_count if previous else 0) + 1,
            succeeded_at=(datetime.now(UTC) if delivery.status == "succeeded" else None),
            updated_at=datetime.now(UTC),
        )
        self.objects[key] = record
        return record

    async def get_catalog_delivery(
        self, *, artifact_id: int, catalog_binding_id: int
    ) -> CatalogDeliveryRecord | None:
        return self.catalogs.get((artifact_id, catalog_binding_id))

    async def upsert_catalog_delivery(
        self, delivery: CatalogDeliveryUpsert
    ) -> CatalogDeliveryRecord:
        key = (delivery.artifact_id, delivery.catalog_binding_id)
        previous = self.catalogs.get(key)
        record = CatalogDeliveryRecord(
            **asdict(delivery),
            id=previous.id if previous else len(self.catalogs) + 1,
            attempt_count=(previous.attempt_count if previous else 0) + 1,
            succeeded_at=(datetime.now(UTC) if delivery.status == "succeeded" else None),
            updated_at=datetime.now(UTC),
        )
        self.catalogs[key] = record
        return record

    async def create_or_get_publication(
        self,
        publication: PublicationUpsert,
        *,
        artifact_ids: tuple[int, ...],
    ) -> PublicationRecord:
        existing = next(
            (
                value
                for value in self.publications.values()
                if value.route_id == publication.route_id
                and value.identity_key == publication.identity_key
            ),
            None,
        )
        if existing:
            return existing
        record = PublicationRecord(
            **asdict(publication),
            id=len(self.publications) + 1,
            created_at=datetime.now(UTC),
        )
        self.publications[record.id] = record
        self.publication_artifacts[record.id] = artifact_ids
        return record

    async def list_publication_artifact_ids(self, publication_id: int) -> tuple[int, ...]:
        return self.publication_artifacts[publication_id]

    async def get_publication(self, publication_id: int) -> PublicationRecord | None:
        return self.publications.get(publication_id)

    async def upsert_publication_delivery(
        self, delivery: PublicationDeliveryUpsert
    ) -> PublicationDeliveryRecord:
        key = (delivery.publication_id, delivery.object_binding_id)
        previous = self.publication_deliveries.get(key)
        record = PublicationDeliveryRecord(
            **asdict(delivery),
            id=previous.id if previous else len(self.publication_deliveries) + 1,
            attempt_count=(previous.attempt_count if previous else 0) + 1,
            updated_at=datetime.now(UTC),
        )
        self.publication_deliveries[key] = record
        return record

    async def list_publication_deliveries(
        self, publication_id: int
    ) -> tuple[PublicationDeliveryRecord, ...]:
        return tuple(
            value
            for (owner_id, _), value in self.publication_deliveries.items()
            if owner_id == publication_id
        )

    async def set_publication_status(
        self,
        publication_id: int,
        *,
        status: PublicationStatus,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        self.publications[publication_id] = replace(
            self.publications[publication_id],
            status=status,
            error_code=error_code,
            error_message=error_message,
        )

    async def has_newer_pointer_delivery(
        self,
        *,
        object_binding_id: int,
        **_: object,
    ) -> bool:
        return object_binding_id in self.newer_pointer_bindings

    @asynccontextmanager
    async def pointer_lock(self, **_: object):
        yield


def test_publication_stages_reuse_success_and_retry_only_failed_pointer() -> None:
    asyncio.run(_run_publication_stage_recovery_scenario())


def test_required_secondary_pointer_failure_blocks_primary_and_is_retryable() -> None:
    asyncio.run(_run_required_secondary_pointer_failure_scenario())


def test_running_stage_checkpoints_return_precondition_conflicts_without_writes() -> None:
    asyncio.run(_run_running_checkpoint_rejection_scenario())


def test_stale_stage_checkpoints_are_reclaimed() -> None:
    asyncio.run(_run_stale_checkpoint_recovery_scenario())


def test_catalog_scope_reconciliation_uses_complete_membership() -> None:
    asyncio.run(_run_catalog_scope_reconciliation_scenario())


def test_unavailable_stage_checkpoints_are_terminal_and_reused() -> None:
    asyncio.run(_run_unavailable_checkpoint_reuse_scenario())


def test_publication_index_retries_only_failed_destination() -> None:
    asyncio.run(_run_publication_index_retry_scenario())


def test_pointer_snapshot_mismatch_is_rejected_before_writes() -> None:
    asyncio.run(_run_pointer_snapshot_validation_scenario())


def test_pointer_request_requires_publication_snapshot_fields() -> None:
    schema = PublicationPointerStageRequest.model_json_schema(by_alias=True)

    assert set(schema["required"]) >= {
        "publicationId",
        "artifactIds",
        "profileRevisionId",
        "publishMode",
        "environment",
    }


def test_pointer_subset_keeps_publication_partial_until_every_destination_finishes() -> None:
    asyncio.run(_run_pointer_subset_scenario())


def test_optional_destination_failure_completes_with_warnings() -> None:
    asyncio.run(_run_optional_destination_scenario())


def test_older_publication_cannot_overwrite_a_newer_pointer() -> None:
    asyncio.run(_run_pointer_regression_scenario())


def test_optional_index_failure_never_publishes_its_pointer() -> None:
    asyncio.run(_run_optional_index_failure_scenario())


def test_missing_optional_index_is_a_warning_and_never_publishes_its_pointer() -> None:
    asyncio.run(_run_missing_optional_index_scenario())


def test_stage_rejects_artifact_assigned_to_another_profile() -> None:
    asyncio.run(_run_profile_membership_rejection_scenario())


def test_cutover_target_authorization_is_scoped_to_snapshot_membership() -> None:
    asyncio.run(_run_cutover_authorization_scenario())


def test_publication_identity_not_membership_controls_retry_reuse() -> None:
    asyncio.run(_run_publication_identity_scenario())


def test_checkpoint_repository_uses_explicit_identity_and_monotonic_id(
    migrated_database_path: Path,
) -> None:
    asyncio.run(_run_checkpoint_identity_scenario(migrated_database_path))


def test_checkpoint_repository_enforces_routing_scope(
    migrated_database_path: Path,
) -> None:
    asyncio.run(_run_checkpoint_routing_scope_scenario(migrated_database_path))


async def _run_publication_stage_recovery_scenario() -> None:
    writes: list[tuple[str, str]] = []
    stores = {
        name: FakeObjectStore(name, writes) for name in ("artifact", "staging", "remote", "local")
    }
    catalogs = {
        "remote-catalog": FakeCatalogPublisher(),
        "local-catalog": FakeCatalogPublisher(),
    }
    route = _route()
    artifact, payload = _artifact_and_payload()
    checkpoints = FakeCheckpoints(artifact)
    service = PublicationStageService(
        configuration=FakeConfiguration(route),  # type: ignore[arg-type]
        checkpoints=checkpoints,  # type: ignore[arg-type]
        archive=Any,  # type: ignore[arg-type]
        connections=FakeConnectionFactory(stores, catalogs),
        artifact_store_ref="artifact",
        staging_store_ref="staging",
    )

    canonical_key = f"artifacts/sha256/{artifact.sha256[:2]}/{artifact.sha256}.json"
    stores["artifact"].fail_once_keys.add(canonical_key)
    with pytest.raises(OSError, match="planned failure"):
        await service.build_canonical(artifact=artifact, payload=payload)
    failed_artifact = checkpoints.artifacts[artifact.id]
    assert failed_artifact.artifact_status == "failed"
    assert failed_artifact.unavailable_code == "OSError"

    artifact = await service.build_canonical(artifact=failed_artifact, payload=payload)
    assert artifact.artifact_status == "ready"
    assert artifact.artifact_key == canonical_key

    object_result = await service.deliver_objects(artifact_ids=(artifact.id,), route=route)
    assert object_result.status == "succeeded"
    object_write_count = len(writes)

    catalogs["remote-catalog"].fail_once = True
    first_catalog = await service.publish_catalogs(artifact_ids=(artifact.id,), route=route)
    assert first_catalog.status == "failed"
    second_catalog = await service.publish_catalogs(artifact_ids=(artifact.id,), route=route)
    assert second_catalog.status == "succeeded"
    assert len(writes) == object_write_count
    assert len(catalogs["local-catalog"].calls) == 1

    built = await service.build_publication(
        artifact_ids=(artifact.id,), route=route, schema_version=1
    )
    assert built.status == "succeeded"
    assert built.publication_id is not None
    index_write_count = len(writes)

    primary_pointer = "legacy/channels/prod.json"
    stores["remote"].fail_once_keys.add(primary_pointer)
    first_pointer = await service.publish_pointer(publication_id=built.publication_id)
    assert first_pointer.status == "failed"
    assert writes[-1] == ("local", "local/channels/prod.json")
    after_failed_pointer = len(writes)

    second_pointer = await service.publish_pointer(publication_id=built.publication_id)
    assert second_pointer.status == "succeeded"
    assert writes[-1] == ("remote", primary_pointer)
    assert len(writes) == after_failed_pointer + 1
    assert all("/index." not in key for _, key in writes[index_write_count:])

    third_pointer = await service.publish_pointer(publication_id=built.publication_id)
    assert third_pointer.status == "succeeded"
    assert all(result.reused for result in third_pointer.destination_results)
    assert len(writes) == after_failed_pointer + 1


async def _run_required_secondary_pointer_failure_scenario() -> None:
    service, checkpoints, stores, route, artifact = await _ready_service()
    built = await service.build_publication(
        artifact_ids=(artifact.id,),
        route=route,
        schema_version=1,
    )
    assert built.publication_id is not None
    publication_id = built.publication_id
    local_pointer = "local/channels/prod.json"
    primary_pointer = "legacy/channels/prod.json"
    stores["local"].fail_once_keys.add(local_pointer)

    first = await service.publish_pointer(publication_id=publication_id)

    assert first.status == "failed"
    assert local_pointer not in stores["local"].objects
    assert primary_pointer not in stores["remote"].objects
    by_binding = {result.binding_id: result for result in first.destination_results}
    assert by_binding[2].status == "failed"
    assert by_binding[1].status == "failed"
    assert by_binding[1].error_code == "required_destination_pointer_failed"
    assert checkpoints.publications[publication_id].status == "failed"
    assert checkpoints.publication_deliveries[(publication_id, 1)].pointer_succeeded_at is None

    retry = await service.publish_pointer(publication_id=publication_id)

    assert retry.status == "succeeded"
    assert stores["local"].writes[-2:] == [
        ("local", local_pointer),
        ("remote", primary_pointer),
    ]
    assert checkpoints.publications[publication_id].status == "published"


async def _run_running_checkpoint_rejection_scenario() -> None:
    service, checkpoints, stores, route, artifact = await _ready_service()
    object_delivery = checkpoints.objects[(artifact.id, 1)]
    checkpoints.objects[(artifact.id, 1)] = replace(
        object_delivery,
        status="running",
        succeeded_at=None,
    )
    writes_before = sum(len(store.objects) for store in stores.values())

    with pytest.raises(PublicationStagePreconditionFailed) as object_error:
        await service.deliver_objects(
            artifact_ids=(artifact.id,),
            route=route,
            destination_ids=(1,),
        )

    object_missing = cast(
        list[dict[str, object]],
        object_error.value.descriptor.details["missingPreconditions"],
    )
    assert object_missing[0]["status"] == "running"
    assert sum(len(store.objects) for store in stores.values()) == writes_before
    checkpoints.objects[(artifact.id, 1)] = object_delivery

    catalog_delivery = checkpoints.catalogs[(artifact.id, 1)]
    checkpoints.catalogs[(artifact.id, 1)] = replace(
        catalog_delivery,
        status="running",
        succeeded_at=None,
    )
    with pytest.raises(PublicationStagePreconditionFailed) as catalog_error:
        await service.publish_catalogs(
            artifact_ids=(artifact.id,),
            route=route,
            destination_ids=(1,),
        )
    catalog_missing = cast(
        list[dict[str, object]],
        catalog_error.value.descriptor.details["missingPreconditions"],
    )
    assert catalog_missing[0]["status"] == "running"
    checkpoints.catalogs[(artifact.id, 1)] = catalog_delivery

    built = await service.build_publication(
        artifact_ids=(artifact.id,),
        route=route,
        schema_version=1,
    )
    assert built.publication_id is not None
    publication_id = built.publication_id
    publication_delivery = checkpoints.publication_deliveries[(publication_id, 1)]
    checkpoints.publication_deliveries[(publication_id, 1)] = replace(
        publication_delivery,
        status="building",
        index_succeeded_at=None,
    )
    with pytest.raises(PublicationStagePreconditionFailed) as index_error:
        await service.build_publication(
            artifact_ids=(artifact.id,),
            route=route,
            schema_version=1,
            destination_ids=(1,),
        )
    index_missing = cast(
        list[dict[str, object]],
        index_error.value.descriptor.details["missingPreconditions"],
    )
    assert index_missing[0]["status"] == "building"

    checkpoints.publication_deliveries[(publication_id, 1)] = replace(
        publication_delivery,
        status="building",
    )
    pointer_objects_before = {name: set(store.objects) for name, store in stores.items()}
    with pytest.raises(PublicationStagePreconditionFailed) as pointer_error:
        await service.publish_pointer(
            publication_id=publication_id,
            destination_ids=(1,),
        )
    pointer_missing = cast(
        list[dict[str, object]],
        pointer_error.value.descriptor.details["missingPreconditions"],
    )
    assert pointer_missing[0]["status"] == "building"
    assert {name: set(store.objects) for name, store in stores.items()} == pointer_objects_before


async def _run_stale_checkpoint_recovery_scenario() -> None:
    service, checkpoints, _, route, artifact = await _ready_service()
    stale_at = datetime.now(UTC) - timedelta(hours=1)

    object_delivery = checkpoints.objects[(artifact.id, 1)]
    checkpoints.objects[(artifact.id, 1)] = replace(
        object_delivery,
        status="running",
        succeeded_at=None,
        updated_at=stale_at,
    )
    object_result = await service.deliver_objects(
        artifact_ids=(artifact.id,),
        route=route,
        destination_ids=(1,),
    )
    assert object_result.status == "succeeded"

    catalog_delivery = checkpoints.catalogs[(artifact.id, 1)]
    checkpoints.catalogs[(artifact.id, 1)] = replace(
        catalog_delivery,
        status="running",
        succeeded_at=None,
        updated_at=stale_at,
    )
    catalog_result = await service.publish_catalogs(
        artifact_ids=(artifact.id,),
        route=route,
        destination_ids=(1,),
    )
    assert catalog_result.status == "succeeded"

    built = await service.build_publication(
        artifact_ids=(artifact.id,),
        route=route,
        schema_version=1,
        destination_ids=(1,),
    )
    assert built.publication_id is not None
    publication_delivery = checkpoints.publication_deliveries[(built.publication_id, 1)]
    checkpoints.publication_deliveries[(built.publication_id, 1)] = replace(
        publication_delivery,
        status="building",
        index_succeeded_at=None,
        updated_at=stale_at,
    )
    rebuilt = await service.build_publication(
        artifact_ids=(artifact.id,),
        route=route,
        schema_version=1,
        destination_ids=(1,),
    )
    assert rebuilt.status == "succeeded"


async def _run_catalog_scope_reconciliation_scenario() -> None:
    service, _, _, route, artifact = await _ready_service()
    result = await service.publish_catalogs(
        artifact_ids=(artifact.id,),
        route=route,
        reconcile_scope=True,
    )

    assert result.status == "succeeded"
    factory = cast(FakeConnectionFactory, service._connections)  # noqa: SLF001
    for catalog in factory.catalogs.values():
        assert len(catalog.reconciliations) == 1
        context, environment, retained = catalog.reconciliations[0]
        assert context.profile_key == route.profile_key
        assert environment == route.environment
        assert [(item.video_id, item.variant) for item in retained] == [
            (artifact.video_id, artifact.variant)
        ]


async def _run_unavailable_checkpoint_reuse_scenario() -> None:
    service, checkpoints, stores, route, artifact = await _ready_service()
    object_delivery = checkpoints.objects[(artifact.id, 1)]
    checkpoints.objects[(artifact.id, 1)] = replace(
        object_delivery,
        status="unavailable",
        succeeded_at=None,
    )
    object_attempts = object_delivery.attempt_count
    writes_before = len(stores["remote"].writes)

    object_result = await service.deliver_objects(
        artifact_ids=(artifact.id,),
        route=route,
        destination_ids=(1,),
    )

    assert object_result.status == "failed"
    assert object_result.destination_results[0].status == "unavailable"
    assert object_result.destination_results[0].reused
    assert checkpoints.objects[(artifact.id, 1)].attempt_count == object_attempts
    assert len(stores["remote"].writes) == writes_before
    checkpoints.objects[(artifact.id, 1)] = object_delivery

    catalog_delivery = checkpoints.catalogs[(artifact.id, 1)]
    checkpoints.catalogs[(artifact.id, 1)] = replace(
        catalog_delivery,
        status="unavailable",
        succeeded_at=None,
    )
    catalog_result = await service.publish_catalogs(
        artifact_ids=(artifact.id,),
        route=route,
        destination_ids=(1,),
    )

    assert catalog_result.status == "failed"
    assert catalog_result.destination_results[0].status == "unavailable"
    assert catalog_result.destination_results[0].reused
    assert checkpoints.catalogs[(artifact.id, 1)].attempt_count == (catalog_delivery.attempt_count)
    checkpoints.catalogs[(artifact.id, 1)] = catalog_delivery

    built = await service.build_publication(
        artifact_ids=(artifact.id,),
        route=route,
        schema_version=1,
    )
    assert built.publication_id is not None
    publication_id = built.publication_id
    publication_delivery = checkpoints.publication_deliveries[(publication_id, 1)]
    checkpoints.publication_deliveries[(publication_id, 1)] = replace(
        publication_delivery,
        status="unavailable",
        index_succeeded_at=None,
    )
    index_result = await service.build_publication(
        artifact_ids=(artifact.id,),
        route=route,
        schema_version=1,
        destination_ids=(1,),
    )

    assert index_result.status == "failed"
    assert index_result.destination_results[0].status == "unavailable"
    assert index_result.destination_results[0].reused
    assert checkpoints.publication_deliveries[(publication_id, 1)].attempt_count == (
        publication_delivery.attempt_count
    )

    optional_route = _optional_route()
    (
        optional_service,
        optional_checkpoints,
        optional_stores,
        _,
        optional_artifact,
    ) = await _ready_service(route=optional_route)
    optional_build = await optional_service.build_publication(
        artifact_ids=(optional_artifact.id,),
        route=optional_route,
        schema_version=1,
    )
    assert optional_build.publication_id is not None
    optional_publication_id = optional_build.publication_id
    optional_local = optional_checkpoints.publication_deliveries[(optional_publication_id, 2)]
    optional_checkpoints.publication_deliveries[(optional_publication_id, 2)] = replace(
        optional_local,
        status="unavailable",
        index_succeeded_at=None,
    )

    pointer_result = await optional_service.publish_pointer(publication_id=optional_publication_id)

    assert pointer_result.status == "succeededWithWarnings"
    pointer_by_binding = {
        result.binding_id: result for result in pointer_result.destination_results
    }
    assert pointer_by_binding[2].status == "unavailable"
    assert pointer_by_binding[2].reused
    assert "legacy/channels/prod.json" in optional_stores["remote"].objects
    assert "local/channels/prod.json" not in optional_stores["local"].objects


async def _run_publication_index_retry_scenario() -> None:
    service, checkpoints, stores, route, artifact = await _ready_service()
    stores["remote"].fail_once_fragments.add("/index.")

    first = await service.build_publication(
        artifact_ids=(artifact.id,),
        route=route,
        schema_version=1,
    )
    assert first.status == "failed"
    assert first.publication_id is not None
    publication_id = first.publication_id
    local_before = checkpoints.publication_deliveries[(publication_id, 2)]
    local_write_count = len([write for write in stores["local"].writes if write[0] == "local"])

    retry = await service.build_publication(
        artifact_ids=(artifact.id,),
        route=route,
        schema_version=1,
    )

    assert retry.status == "succeeded"
    by_binding = {result.binding_id: result for result in retry.destination_results}
    assert not by_binding[1].reused
    assert by_binding[2].reused
    assert checkpoints.publication_deliveries[(publication_id, 2)].attempt_count == (
        local_before.attempt_count
    )
    assert len([write for write in stores["local"].writes if write[0] == "local"]) == (
        local_write_count
    )


async def _run_pointer_snapshot_validation_scenario() -> None:
    service, _, stores, route, artifact = await _ready_service()
    built = await service.build_publication(
        artifact_ids=(artifact.id,),
        route=route,
        schema_version=1,
    )
    assert built.publication_id is not None
    publication_id = built.publication_id
    pointer_objects_before = {name: set(store.objects) for name, store in stores.items()}
    cases = (
        ({"expected_artifact_ids": (999,)}, "publicationMembershipSnapshot"),
        ({"expected_profile_revision_id": 99}, "profileRevisionSnapshot"),
        ({"expected_publish_mode": "dev"}, "publishModeSnapshot"),
        ({"expected_environment": "staging"}, "environmentSnapshot"),
    )
    defaults: dict[str, object] = {
        "expected_artifact_ids": (artifact.id,),
        "expected_profile_revision_id": route.profile_revision_id,
        "expected_publish_mode": route.publish_mode,
        "expected_environment": route.environment,
    }
    for override, expected_kind in cases:
        expectations = defaults | override
        with pytest.raises(PublicationStagePreconditionFailed) as error:
            await service.publish_pointer(
                publication_id=publication_id,
                expected_artifact_ids=expectations["expected_artifact_ids"],  # type: ignore[arg-type]
                expected_profile_revision_id=expectations["expected_profile_revision_id"],  # type: ignore[arg-type]
                expected_publish_mode=expectations["expected_publish_mode"],  # type: ignore[arg-type]
                expected_environment=expectations["expected_environment"],  # type: ignore[arg-type]
            )
        snapshot_missing = cast(
            list[dict[str, object]],
            error.value.descriptor.details["missingPreconditions"],
        )
        assert snapshot_missing[0]["kind"] == expected_kind
        assert {name: set(store.objects) for name, store in stores.items()} == (
            pointer_objects_before
        )

    published = await service.publish_pointer(
        publication_id=publication_id,
        expected_artifact_ids=(artifact.id,),
        expected_profile_revision_id=route.profile_revision_id,
        expected_publish_mode=route.publish_mode,
        expected_environment=route.environment,
    )
    assert published.status == "succeeded"


async def _run_pointer_subset_scenario() -> None:
    service, checkpoints, stores, route, artifact = await _ready_service()
    built = await service.build_publication(
        artifact_ids=(artifact.id,), route=route, schema_version=1
    )
    assert built.publication_id is not None

    with pytest.raises(PublicationStagePreconditionFailed) as error:
        await service.publish_pointer(
            publication_id=built.publication_id,
            destination_ids=(1,),
        )
    assert error.value.descriptor.details == {
        "stage": "pointerPublish",
        "missingPreconditions": [
            {
                "kind": "requiredDestinationPointer",
                "publicationId": built.publication_id,
                "objectBindingId": 2,
            }
        ],
    }
    assert "legacy/channels/prod.json" not in stores["remote"].objects

    selected = await service.publish_pointer(
        publication_id=built.publication_id,
        destination_ids=(2,),
    )

    assert selected.status == "succeeded"
    assert checkpoints.publications[built.publication_id].status == "partially_published"
    assert "local/channels/prod.json" in stores["local"].objects
    assert "legacy/channels/prod.json" not in stores["remote"].objects

    completed = await service.publish_pointer(
        publication_id=built.publication_id,
        destination_ids=(1,),
    )
    assert completed.status == "succeeded"
    assert checkpoints.publications[built.publication_id].status == "published"


async def _run_optional_destination_scenario() -> None:
    route = _optional_route()
    service, checkpoints, stores, _, artifact = await _ready_service(
        route=route,
        publish_destinations=False,
    )
    optional_key = (
        f"local/archive/v1/videos/{artifact.video_id}/"
        f"timeline.{artifact.version}.{artifact.variant}.json"
    )
    stores["local"].fail_once_keys.add(optional_key)

    result = await service.publish_composite(
        artifact_ids=(artifact.id,),
        context=service.routed_context(route),
        schema_version=1,
    )

    assert result.status == "succeededWithWarnings"
    assert checkpoints.publications[result.publication_id].status == "partially_published"
    assert "legacy/channels/prod.json" in stores["remote"].objects
    assert "local/channels/prod.json" not in stores["local"].objects


async def _run_pointer_regression_scenario() -> None:
    service, checkpoints, stores, route, artifact = await _ready_service()
    built = await service.build_publication(
        artifact_ids=(artifact.id,), route=route, schema_version=1
    )
    assert built.publication_id is not None
    checkpoints.newer_pointer_bindings.add(1)
    pointer_writes_before = {name: set(store.objects) for name, store in stores.items()}

    with pytest.raises(PublicationStagePreconditionFailed) as error:
        await service.publish_pointer(publication_id=built.publication_id)

    assert error.value.descriptor.details == {
        "stage": "pointerPublish",
        "missingPreconditions": [
            {
                "kind": "newerPublicationPointer",
                "publicationId": built.publication_id,
                "objectBindingId": 1,
            }
        ],
    }
    assert {name: set(store.objects) for name, store in stores.items()} == pointer_writes_before


async def _run_optional_index_failure_scenario() -> None:
    route = _optional_route()
    service, checkpoints, stores, _, artifact = await _ready_service(route=route)
    stores["local"].fail_once_fragments.add("/index.")

    built = await service.build_publication(
        artifact_ids=(artifact.id,),
        route=route,
        schema_version=1,
    )
    assert built.status == "succeededWithWarnings"
    assert built.publication_id is not None

    pointer = await service.publish_pointer(publication_id=built.publication_id)

    assert pointer.status == "succeededWithWarnings"
    assert "legacy/channels/prod.json" in stores["remote"].objects
    assert "local/channels/prod.json" not in stores["local"].objects
    local = checkpoints.publication_deliveries[(built.publication_id, 2)]
    assert local.index_succeeded_at is None
    assert local.pointer_succeeded_at is None


async def _run_missing_optional_index_scenario() -> None:
    route = _optional_route()
    service, checkpoints, stores, _, artifact = await _ready_service(route=route)
    built = await service.build_publication(
        artifact_ids=(artifact.id,),
        route=route,
        schema_version=1,
        destination_ids=(1,),
    )
    assert built.status == "succeeded"
    assert built.publication_id is not None

    pointer = await service.publish_pointer(publication_id=built.publication_id)

    assert pointer.status == "succeededWithWarnings"
    assert "legacy/channels/prod.json" in stores["remote"].objects
    assert "local/channels/prod.json" not in stores["local"].objects
    local = checkpoints.publication_deliveries[(built.publication_id, 2)]
    assert local.status == "unavailable"
    assert local.error_code == "publication_index_missing"
    assert local.pointer_succeeded_at is None


async def _run_profile_membership_rejection_scenario() -> None:
    service, checkpoints, _, route, artifact = await _ready_service()
    checkpoints.assignments[artifact.id] = ArtifactPublishProfileAssignment(
        artifact_id=artifact.id,
        streamer_id=3,
        publish_profile_id=99,
    )
    for expected_stage in ("objectDeliver", "catalogPublish", "publicationBuild"):
        with pytest.raises(PublicationStagePreconditionFailed) as error:
            if expected_stage == "objectDeliver":
                await service.deliver_objects(artifact_ids=(artifact.id,), route=route)
            elif expected_stage == "catalogPublish":
                await service.publish_catalogs(artifact_ids=(artifact.id,), route=route)
            else:
                await service.build_publication(
                    artifact_ids=(artifact.id,),
                    route=route,
                    schema_version=1,
                )
        assert error.value.descriptor.details == {
            "stage": expected_stage,
            "missingPreconditions": [
                {
                    "kind": "artifactPublishProfile",
                    "artifactId": artifact.id,
                    "streamerId": 3,
                    "expectedProfileId": 1,
                    "actualProfileId": 99,
                }
            ],
        }


async def _run_cutover_authorization_scenario() -> None:
    service, checkpoints, _, route, artifact = await _ready_service()
    checkpoints.assignments[artifact.id] = ArtifactPublishProfileAssignment(
        artifact_id=artifact.id,
        streamer_id=3,
        publish_profile_id=2,
    )
    authorization = PublicationMembershipAuthorization(
        purpose="cutover_target",
        cutover_id=44,
        streamer_id=3,
        source_profile_id=2,
        target_profile_id=1,
        artifact_ids=(artifact.id,),
    )

    allowed = await service.deliver_objects(
        artifact_ids=(artifact.id,),
        route=route,
        membership_authorization=authorization,
    )
    assert allowed.status == "succeeded"

    with pytest.raises(PublicationStagePreconditionFailed):
        await service.deliver_objects(
            artifact_ids=(artifact.id,),
            route=route,
            membership_authorization=replace(authorization, artifact_ids=(999,)),
        )


async def _run_publication_identity_scenario() -> None:
    service, checkpoints, _, route, artifact = await _ready_service()
    first = await service.build_publication(
        artifact_ids=(artifact.id,),
        route=route,
        schema_version=1,
    )
    retry = await service.build_publication(
        artifact_ids=(artifact.id,),
        route=route,
        schema_version=1,
    )
    cutover = await service.build_publication(
        artifact_ids=(artifact.id,),
        route=route,
        schema_version=1,
        publication_identity_key="cutover:44:source",
    )

    assert first.publication_id == retry.publication_id
    assert cutover.publication_id != first.publication_id
    assert len(checkpoints.publications) == 2


async def _run_checkpoint_identity_scenario(database_path: Path) -> None:
    engine = create_database_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")
    try:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            repository = SqlAlchemyArchivePublicationCheckpointRepository(session)
            streamer, artifact = await _create_checkpoint_artifact(
                session,
                stem="membership",
            )
            assignments = await repository.get_artifact_publish_profile_assignments((artifact.id,))
            assert assignments == (
                ArtifactPublishProfileAssignment(
                    artifact_id=artifact.id,
                    streamer_id=streamer.id,
                    publish_profile_id=1,
                ),
            )
            common = {
                "profile_revision_id": 1,
                "route_id": 1,
                "schema_version": 1,
                "membership_sha256": "a" * 64,
                "status": "ready",
                "video_count": 0,
                "artifact_count": 0,
            }
            first = await repository.create_or_get_publication(
                PublicationUpsert(
                    **common,  # type: ignore[arg-type]
                    version="zzzz-lexically-newer",
                    identity_key="history:first",
                ),
                artifact_ids=(),
            )
            second = await repository.create_or_get_publication(
                PublicationUpsert(
                    **common,  # type: ignore[arg-type]
                    version="aaaa-lexically-older",
                    identity_key="history:second",
                ),
                artifact_ids=(),
            )
            retry = await repository.create_or_get_publication(
                PublicationUpsert(
                    **common,  # type: ignore[arg-type]
                    version="retry-version-is-ignored",
                    identity_key="history:first",
                ),
                artifact_ids=(),
            )
            assert first.id != second.id
            assert retry.id == first.id

            now = datetime.now(UTC)
            await repository.upsert_publication_delivery(
                PublicationDeliveryUpsert(
                    publication_id=second.id,
                    object_binding_id=1,
                    destination_id=1,
                    required=True,
                    status="published",
                    index_succeeded_at=now,
                    pointer_succeeded_at=now,
                )
            )
            assert await repository.has_newer_pointer_delivery(
                route_id=1,
                schema_version=1,
                object_binding_id=1,
                publication_id=first.id,
            )
            assert not await repository.has_newer_pointer_delivery(
                route_id=1,
                schema_version=1,
                object_binding_id=1,
                publication_id=second.id,
            )
    finally:
        await engine.dispose()


async def _run_checkpoint_routing_scope_scenario(database_path: Path) -> None:
    engine = create_database_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")
    try:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            repository = SqlAlchemyArchivePublicationCheckpointRepository(session)
            _, artifact = await _create_checkpoint_artifact(session, stem="routing-scope")
            await session.execute(text("PRAGMA foreign_keys = ON"))
            artifact_id = artifact.id
            source_delivery = await repository.upsert_object_delivery(
                ObjectDeliveryUpsert(
                    artifact_id=artifact_id,
                    profile_revision_id=1,
                    route_id=1,
                    object_binding_id=1,
                    destination_id=1,
                    required=True,
                    object_key="archive/routing-scope.json",
                    public_url="https://example.invalid/archive/routing-scope.json",
                    sha256=artifact.sha256,
                    byte_size=artifact.byte_size,
                    status="succeeded",
                )
            )

            with pytest.raises(ValueError, match="Object delivery does not match"):
                await repository.upsert_object_delivery(
                    ObjectDeliveryUpsert(
                        artifact_id=artifact_id,
                        profile_revision_id=1,
                        route_id=1,
                        object_binding_id=3,
                        destination_id=1,
                        required=True,
                        object_key="invalid-object.json",
                        public_url="https://example.invalid/invalid-object.json",
                        sha256=artifact.sha256,
                        byte_size=artifact.byte_size,
                        status="pending",
                    )
                )
            with pytest.raises(ValueError, match="configured source object delivery"):
                await repository.upsert_catalog_delivery(
                    CatalogDeliveryUpsert(
                        artifact_id=artifact_id,
                        profile_revision_id=1,
                        route_id=1,
                        catalog_binding_id=2,
                        destination_id=2,
                        source_object_delivery_id=source_delivery.id,
                        required=True,
                        status="pending",
                    )
                )

            second_revision = PublishProfileRevisionModel(
                profile_id=1,
                revision_number=2,
                state="draft",
            )
            session.add(second_revision)
            await session.commit()
            second_revision_id = second_revision.id
            mismatched_publication = PublicationUpsert(
                profile_revision_id=second_revision_id,
                route_id=1,
                schema_version=1,
                version="mismatched",
                membership_sha256="c" * 64,
                identity_key="routing:mismatched",
                status="ready",
                video_count=1,
                artifact_count=1,
            )
            with pytest.raises(ValueError, match="route does not belong"):
                await repository.create_or_get_publication(
                    mismatched_publication,
                    artifact_ids=(artifact_id,),
                )

            publication = await repository.create_or_get_publication(
                PublicationUpsert(
                    profile_revision_id=1,
                    route_id=1,
                    schema_version=1,
                    version="routing-scope",
                    membership_sha256="d" * 64,
                    identity_key="routing:valid",
                    status="ready",
                    video_count=1,
                    artifact_count=1,
                ),
                artifact_ids=(artifact_id,),
            )
            with pytest.raises(ValueError, match="do not belong to the publication route"):
                await repository.upsert_publication_delivery(
                    PublicationDeliveryUpsert(
                        publication_id=publication.id,
                        object_binding_id=3,
                        destination_id=1,
                        required=True,
                        status="ready",
                    )
                )

            session.add(
                ArchiveArtifactObjectDeliveryModel(
                    artifact_id=artifact_id,
                    profile_revision_id=1,
                    route_id=1,
                    object_binding_id=3,
                    destination_id=1,
                    required=True,
                    object_key="invalid-direct-object.json",
                    public_url="https://example.invalid/invalid-direct-object.json",
                    sha256=artifact.sha256,
                    byte_size=artifact.byte_size,
                    status="pending",
                )
            )
            with pytest.raises(IntegrityError):
                await session.flush()
            await session.rollback()

            session.add(
                ArchiveArtifactCatalogDeliveryModel(
                    artifact_id=artifact_id,
                    profile_revision_id=1,
                    route_id=1,
                    catalog_binding_id=2,
                    destination_id=2,
                    source_object_delivery_id=source_delivery.id,
                    source_object_binding_id=2,
                    required=True,
                    status="pending",
                )
            )
            with pytest.raises(IntegrityError):
                await session.flush()
            await session.rollback()

            session.add(
                ArchivePublicationModel(
                    profile_revision_id=second_revision_id,
                    route_id=1,
                    schema_version=1,
                    version="invalid-direct-publication",
                    membership_sha256="e" * 64,
                    identity_key="routing:invalid-direct",
                    status="ready",
                    video_count=1,
                    artifact_count=1,
                )
            )
            with pytest.raises(IntegrityError):
                await session.flush()
            await session.rollback()

            session.add(
                ArchivePublicationDeliveryModel(
                    publication_id=publication.id,
                    route_id=1,
                    object_binding_id=3,
                    destination_id=1,
                    required=True,
                    status="ready",
                )
            )
            with pytest.raises(IntegrityError):
                await session.flush()
            await session.rollback()
    finally:
        await engine.dispose()


async def _create_checkpoint_artifact(
    session: AsyncSession,
    *,
    stem: str,
) -> tuple[StreamerModel, ArchiveVideoArtifactModel]:
    streamer = StreamerModel(name=f"{stem} streamer", publish_profile_id=1)
    session.add(streamer)
    await session.flush()
    channel = ChannelModel(
        streamer_id=streamer.id,
        handle=f"@{stem}",
        name=f"{stem} channel",
    )
    session.add(channel)
    await session.flush()
    video = VideoModel(
        channel_id=channel.id,
        youtube_video_id=f"{stem}-video",
        title=f"{stem} video",
        description="",
        published_at=datetime.now(UTC),
    )
    session.add(video)
    await session.flush()
    artifact = ArchiveVideoArtifactModel(
        video_id=video.id,
        source_timeline_composition_id=1,
        source_timeline_task_id=1,
        source_micro_event_task_id=1,
        publish_task_id=1,
        publish_job_id=1,
        environment="prod",
        variant="control",
        schema_version=1,
        version=stem,
        object_key=f"{stem}.json",
        public_url=f"https://example.invalid/{stem}.json",
        sha256=hashlib.sha256(stem.encode()).hexdigest(),
        byte_size=1,
        block_count=0,
        episode_count=0,
        topic_cluster_count=0,
        review_flag_count=0,
        micro_event_count=0,
    )
    session.add(artifact)
    await session.commit()
    return streamer, artifact


async def _ready_service(
    *,
    route: ResolvedPublishRoute | None = None,
    publish_destinations: bool = True,
) -> tuple[
    PublicationStageService,
    FakeCheckpoints,
    dict[str, FakeObjectStore],
    ResolvedPublishRoute,
    ArchiveVideoArtifactRecord,
]:
    writes: list[tuple[str, str]] = []
    stores = {
        name: FakeObjectStore(name, writes) for name in ("artifact", "staging", "remote", "local")
    }
    catalogs = {
        "remote-catalog": FakeCatalogPublisher(),
        "local-catalog": FakeCatalogPublisher(),
    }
    resolved_route = route or _route()
    artifact, payload = _artifact_and_payload()
    checkpoints = FakeCheckpoints(artifact)
    service = PublicationStageService(
        configuration=FakeConfiguration(resolved_route),  # type: ignore[arg-type]
        checkpoints=checkpoints,  # type: ignore[arg-type]
        archive=Any,  # type: ignore[arg-type]
        connections=FakeConnectionFactory(stores, catalogs),
        artifact_store_ref="artifact",
        staging_store_ref="staging",
    )
    artifact = await service.build_canonical(artifact=artifact, payload=payload)
    if publish_destinations:
        object_result = await service.deliver_objects(
            artifact_ids=(artifact.id,), route=resolved_route
        )
        assert object_result.status == "succeeded"
        catalog_result = await service.publish_catalogs(
            artifact_ids=(artifact.id,), route=resolved_route
        )
        assert catalog_result.status == "succeeded"
    return service, checkpoints, stores, resolved_route, artifact


def _route() -> ResolvedPublishRoute:
    return ResolvedPublishRoute(
        profile_id=1,
        profile_key="legacy-current",
        profile_revision_id=1,
        revision_number=1,
        route_id=1,
        publish_mode="prod",
        environment="prod",
        object_bindings=(
            ResolvedObjectBinding(
                id=1,
                destination_id=1,
                connection_ref="remote",
                key_prefix="legacy",
                required=True,
                is_primary=True,
            ),
            ResolvedObjectBinding(
                id=2,
                destination_id=2,
                connection_ref="local",
                key_prefix="local",
                required=True,
                is_primary=False,
            ),
        ),
        catalog_bindings=(
            ResolvedCatalogBinding(
                id=1,
                destination_id=1,
                connection_ref="remote-catalog",
                source_object_binding_id=1,
                required=True,
            ),
            ResolvedCatalogBinding(
                id=2,
                destination_id=2,
                connection_ref="local-catalog",
                source_object_binding_id=2,
                required=True,
            ),
        ),
    )


def _optional_route() -> ResolvedPublishRoute:
    route = _route()
    return replace(
        route,
        object_bindings=(
            route.object_bindings[0],
            replace(route.object_bindings[1], required=False),
        ),
        catalog_bindings=(
            route.catalog_bindings[0],
            replace(route.catalog_bindings[1], required=False),
        ),
    )


def _artifact_and_payload() -> tuple[ArchiveVideoArtifactRecord, bytes]:
    payload = json.dumps(
        {
            "schemaVersion": 1,
            "environment": "prod",
            "variant": "control",
            "version": "20260718T010203Z",
            "videoId": 77,
            "youtubeVideoId": "youtube-77",
            "video": {
                "id": 77,
                "title": "Publication test",
                "streamer": {"id": 3, "name": "Creator"},
                "channel": {
                    "id": 4,
                    "name": "Main",
                    "handle": "@main",
                    "youtubeChannelId": "UC_TEST",
                },
                "publishedAt": "2026-07-18T00:00:00Z",
                "duration": "PT1M",
                "durationSec": 60,
                "thumbnailUrl": None,
                "isEmbeddable": True,
                "displayTitle": "Publication test",
                "displaySummary": "Summary",
                "mainTopics": ["testing"],
            },
            "blocks": [],
            "episodes": [],
            "topicClusters": [],
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    sha256 = hashlib.sha256(payload).hexdigest()
    now = datetime.now(UTC)
    return (
        ArchiveVideoArtifactRecord(
            id=7,
            video_id=77,
            source_timeline_composition_id=10,
            source_timeline_task_id=11,
            source_micro_event_task_id=12,
            publish_task_id=13,
            publish_job_id=14,
            environment="prod",
            variant="control",
            schema_version=1,
            version="20260718T010203Z",
            object_key="legacy/archive/v1/videos/77/timeline.json",
            public_url="https://remote.example/legacy/archive/v1/videos/77/timeline.json",
            sha256=sha256,
            byte_size=len(payload),
            block_count=0,
            episode_count=0,
            topic_cluster_count=0,
            review_flag_count=0,
            micro_event_count=0,
            build_key=None,
            artifact_status="pending",
            artifact_store_ref=None,
            artifact_key=None,
            unavailable_code=None,
            unavailable_detail=None,
            public_catalog_synced_at=None,
            public_catalog_sync_error=None,
            created_at=now,
            updated_at=now,
        ),
        payload,
    )
