from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Protocol

from codex_sdk_cli.application.publication.errors import (
    PublicationRouteNotFound,
    PublicationStagePreconditionFailed,
)
from codex_sdk_cli.application.publication.models import (
    PublicationDestinationResult,
    PublicationMembershipAuthorization,
    PublicationStageResult,
    PublicationStageStatus,
)
from codex_sdk_cli.application.publication_config.ports import (
    PublishConfigurationRepositoryPort,
    ResolvedObjectBinding,
    ResolvedPublishRoute,
)
from codex_sdk_cli.domains.archive_publish.checkpoints import (
    ArchivePublicationCheckpointPort,
    CatalogDeliveryRecord,
    CatalogDeliveryUpsert,
    ObjectDeliveryRecord,
    ObjectDeliveryUpsert,
    PublicationDeliveryRecord,
    PublicationDeliveryUpsert,
    PublicationRecord,
    PublicationUpsert,
)
from codex_sdk_cli.domains.archive_publish.ports import (
    ArchivePublishRepositoryPort,
    ArchiveVideoArtifactRecord,
    RoutedArchivePublishContext,
    RoutedArchivePublishResult,
)
from codex_sdk_cli.domains.publication.ports import (
    PublicationCatalogContext,
    PublicationCatalogPublisherPort,
    PublicationCatalogReconcilerPort,
    PublicationCatalogVideoKey,
    PublicationObjectStorePort,
)
from codex_sdk_cli.infra.publication.projection import (
    build_destination_index,
    canonical_artifact_key,
    catalog_row_from_timeline,
    destination_artifact_key,
    membership_sha256,
    parse_timeline_payload,
)

_IMMUTABLE_CACHE_CONTROL = "public, max-age=31536000, immutable"
_POINTER_CACHE_CONTROL = "public, max-age=60, must-revalidate"
_DEFAULT_CHECKPOINT_LEASE_TIMEOUT = timedelta(minutes=15)


class PublicationConnectionFactoryPort(Protocol):
    def object_store(self, connection_ref: str) -> PublicationObjectStorePort: ...

    def catalog_publisher(self, connection_ref: str) -> PublicationCatalogPublisherPort: ...

    def catalog_reconciler(
        self,
        connection_ref: str,
    ) -> PublicationCatalogReconcilerPort | None: ...


class PublicationStageService:
    def __init__(
        self,
        *,
        configuration: PublishConfigurationRepositoryPort,
        checkpoints: ArchivePublicationCheckpointPort,
        archive: ArchivePublishRepositoryPort,
        connections: PublicationConnectionFactoryPort,
        artifact_store_ref: str,
        staging_store_ref: str,
        checkpoint_lease_timeout: timedelta = _DEFAULT_CHECKPOINT_LEASE_TIMEOUT,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if checkpoint_lease_timeout <= timedelta(0):
            raise ValueError("Checkpoint lease timeout must be positive.")
        self._configuration = configuration
        self._checkpoints = checkpoints
        self._archive = archive
        self._connections = connections
        self._artifact_store_ref = artifact_store_ref
        self._staging_store_ref = staging_store_ref
        self._checkpoint_lease_timeout = checkpoint_lease_timeout
        self._clock = clock or _utc_now

    async def active_route(
        self,
        *,
        streamer_id: int,
        publish_mode: str,
        environment: str,
    ) -> ResolvedPublishRoute:
        route = await self._configuration.resolve_active_route(
            streamer_id=streamer_id,
            publish_mode=publish_mode,  # type: ignore[arg-type]
            environment=environment,
        )
        if route is None:
            raise PublicationRouteNotFound(
                streamer_id=streamer_id,
                publish_mode=publish_mode,
                environment=environment,
            )
        _primary_binding(route)
        return route

    async def revision_route(
        self,
        *,
        profile_revision_id: int,
        publish_mode: str,
        environment: str,
    ) -> ResolvedPublishRoute:
        route = await self._configuration.resolve_revision_route(
            profile_revision_id=profile_revision_id,
            publish_mode=publish_mode,  # type: ignore[arg-type]
            environment=environment,
        )
        if route is None:
            raise PublicationRouteNotFound(
                profile_revision_id=profile_revision_id,
                publish_mode=publish_mode,
                environment=environment,
            )
        _primary_binding(route)
        return route

    def routed_context(self, route: ResolvedPublishRoute) -> RoutedArchivePublishContext:
        primary = _primary_binding(route)
        store = self._connections.object_store(primary.connection_ref)
        return RoutedArchivePublishContext(
            profile_id=route.profile_id,
            profile_key=route.profile_key,
            profile_revision_id=route.profile_revision_id,
            route_id=route.route_id,
            publish_mode=route.publish_mode,
            environment=route.environment,
            primary_object_binding_id=primary.id,
            primary_destination_id=primary.destination_id,
            primary_key_prefix=primary.key_prefix,
            primary_public_base_url=store.public_url("").rstrip("/"),
        )

    async def prepare_route(
        self,
        *,
        streamer_id: int,
        publish_mode: str,
        environment: str,
    ) -> RoutedArchivePublishContext:
        return self.routed_context(
            await self.active_route(
                streamer_id=streamer_id,
                publish_mode=publish_mode,
                environment=environment,
            )
        )

    async def build_canonical(
        self,
        *,
        artifact: ArchiveVideoArtifactRecord,
        payload: bytes,
    ) -> ArchiveVideoArtifactRecord:
        try:
            _verify_artifact_payload(artifact, payload)
            store = self._connections.object_store(self._artifact_store_ref)
            key = canonical_artifact_key(artifact.sha256)
            existing = await store.stat_object(object_key=key)
            if existing is None:
                await store.put_bytes(
                    object_key=key,
                    payload=payload,
                    content_type="application/json",
                    cache_control=_IMMUTABLE_CACHE_CONTROL,
                )
            else:
                if existing.byte_size != artifact.byte_size:
                    raise ValueError(f"Canonical object size mismatch for artifact {artifact.id}.")
                _verify_artifact_payload(
                    artifact,
                    await store.get_bytes(object_key=key),
                )
            await self._checkpoints.set_artifact_canonical(
                artifact_id=artifact.id,
                build_key=(
                    artifact.build_key or f"artifact:{artifact.id}:sha256:{artifact.sha256}"
                ),
                store_ref=self._artifact_store_ref,
                artifact_key=key,
            )
        except Exception as exc:
            await self._checkpoints.set_artifact_failed(
                artifact_id=artifact.id,
                code=exc.__class__.__name__,
                detail=str(exc) or exc.__class__.__name__,
            )
            raise
        records = await self._checkpoints.get_artifacts((artifact.id,))
        if not records:
            raise LookupError(f"Archive artifact not found: {artifact.id}")
        return records[0]

    async def canonicalize_existing(
        self,
        *,
        artifact_ids: tuple[int, ...],
        publish_mode: str,
    ) -> PublicationStageResult:
        artifacts = await self._required_artifacts(artifact_ids, stage="artifactBuild")
        results: list[PublicationDestinationResult] = []
        completed: list[int] = []
        for artifact in artifacts:
            if artifact.artifact_status == "unavailable":
                results.append(
                    PublicationDestinationResult(
                        destination_id=0,
                        binding_id=0,
                        destination_type="object",
                        required=True,
                        status="unavailable",
                        error_code=artifact.unavailable_code,
                        error_message=artifact.unavailable_detail,
                    )
                )
                continue
            if artifact.artifact_status == "ready" and artifact.artifact_key:
                try:
                    await self._canonical_payload(artifact)
                except Exception as exc:
                    results.append(_failed_result(0, 0, "object", True, exc))
                else:
                    completed.append(artifact.id)
                    results.append(
                        PublicationDestinationResult(
                            destination_id=0,
                            binding_id=0,
                            destination_type="object",
                            required=True,
                            status="succeeded",
                            reused=True,
                        )
                    )
                continue
            candidate = await self._archive.get_publish_candidate(
                video_id=artifact.video_id,
                environment=artifact.environment,
                variant=artifact.variant,
                schema_version=artifact.schema_version,
            )
            if candidate is None:
                raise PublicationStagePreconditionFailed(
                    stage="artifactBuild",
                    missing=[
                        {
                            "artifactId": artifact.id,
                            "kind": "publishCandidate",
                            "reason": "video_or_timeline_missing",
                        }
                    ],
                )
            route = await self.active_route(
                streamer_id=candidate.streamer.id,
                publish_mode=publish_mode,
                environment=artifact.environment,
            )
            primary = _primary_binding(route)
            try:
                source = self._connections.object_store(primary.connection_ref)
                source_stat = await source.stat_object(object_key=artifact.object_key)
                if source_stat is None:
                    await self._checkpoints.set_artifact_unavailable(
                        artifact_id=artifact.id,
                        code="legacy_source_missing",
                        detail=f"Legacy source object does not exist: {artifact.object_key}",
                    )
                    results.append(
                        PublicationDestinationResult(
                            destination_id=0,
                            binding_id=0,
                            destination_type="object",
                            required=True,
                            status="unavailable",
                            error_code="legacy_source_missing",
                            error_message=(
                                f"Legacy source object does not exist: {artifact.object_key}"
                            ),
                        )
                    )
                    continue
                payload = await source.get_bytes(object_key=artifact.object_key)
                await self.build_canonical(artifact=artifact, payload=payload)
            except Exception as exc:
                detail = str(exc) or exc.__class__.__name__
                await self._checkpoints.set_artifact_failed(
                    artifact_id=artifact.id,
                    code=exc.__class__.__name__,
                    detail=detail,
                )
                results.append(_failed_result(0, 0, "object", True, exc))
            else:
                completed.append(artifact.id)
                results.append(
                    PublicationDestinationResult(
                        destination_id=0,
                        binding_id=0,
                        destination_type="object",
                        required=True,
                        status="succeeded",
                    )
                )
        return PublicationStageResult(
            stage="artifactBuild",
            status=_stage_status(results),
            artifact_ids=tuple(completed),
            destination_results=tuple(results),
        )

    async def deliver_objects(
        self,
        *,
        artifact_ids: tuple[int, ...],
        route: ResolvedPublishRoute,
        destination_ids: tuple[int, ...] | None = None,
        membership_authorization: PublicationMembershipAuthorization | None = None,
    ) -> PublicationStageResult:
        artifacts = await self._ready_artifacts(artifact_ids, stage="objectDeliver")
        await self._validate_artifact_profile_membership(
            artifact_ids=tuple(artifact.id for artifact in artifacts),
            route=route,
            stage="objectDeliver",
            authorization=membership_authorization,
        )
        bindings = _select_object_bindings(route, destination_ids, stage="objectDeliver")
        payloads = {artifact.id: await self._canonical_payload(artifact) for artifact in artifacts}
        existing_deliveries: dict[tuple[int, int], ObjectDeliveryRecord] = {}
        running: list[dict[str, object]] = []
        for artifact in artifacts:
            for binding in bindings:
                existing = await self._checkpoints.get_object_delivery(
                    artifact_id=artifact.id,
                    object_binding_id=binding.id,
                )
                if existing is None:
                    continue
                existing_deliveries[(artifact.id, binding.id)] = existing
                if existing.status == "running" and self._has_active_checkpoint_lease(
                    existing.updated_at
                ):
                    running.append(
                        {
                            "kind": "objectDelivery",
                            "artifactId": artifact.id,
                            "objectBindingId": binding.id,
                            "status": existing.status,
                        }
                    )
        if running:
            raise PublicationStagePreconditionFailed(stage="objectDeliver", missing=running)
        results: list[PublicationDestinationResult] = []
        for artifact in artifacts:
            for binding in bindings:
                existing = existing_deliveries.get((artifact.id, binding.id))
                if existing is not None and existing.status in {"succeeded", "unavailable"}:
                    results.append(_object_result(existing, reused=True))
                    continue
                _require_retryable_checkpoint(
                    status=(
                        self._checkpoint_status_for_retry(existing.status, existing.updated_at)
                        if existing is not None
                        else None
                    ),
                    stage="objectDeliver",
                    missing={
                        "kind": "objectDelivery",
                        "artifactId": artifact.id,
                        "objectBindingId": binding.id,
                        "status": existing.status if existing is not None else "missing",
                    },
                )
                object_key = destination_artifact_key(
                    artifact,
                    key_prefix=binding.key_prefix,
                )
                store = self._connections.object_store(binding.connection_ref)
                public_url = store.public_url(object_key)
                await self._checkpoints.upsert_object_delivery(
                    ObjectDeliveryUpsert(
                        artifact_id=artifact.id,
                        profile_revision_id=route.profile_revision_id,
                        route_id=route.route_id,
                        object_binding_id=binding.id,
                        destination_id=binding.destination_id,
                        required=binding.required,
                        object_key=object_key,
                        public_url=public_url,
                        sha256=artifact.sha256,
                        byte_size=artifact.byte_size,
                        status="running",
                    )
                )
                try:
                    location = await store.put_bytes(
                        object_key=object_key,
                        payload=payloads[artifact.id],
                        content_type="application/json",
                        cache_control=_IMMUTABLE_CACHE_CONTROL,
                    )
                    delivery = await self._checkpoints.upsert_object_delivery(
                        ObjectDeliveryUpsert(
                            artifact_id=artifact.id,
                            profile_revision_id=route.profile_revision_id,
                            route_id=route.route_id,
                            object_binding_id=binding.id,
                            destination_id=binding.destination_id,
                            required=binding.required,
                            object_key=object_key,
                            public_url=location.public_url,
                            sha256=artifact.sha256,
                            byte_size=artifact.byte_size,
                            status="succeeded",
                        )
                    )
                except Exception as exc:
                    delivery = await self._checkpoints.upsert_object_delivery(
                        ObjectDeliveryUpsert(
                            artifact_id=artifact.id,
                            profile_revision_id=route.profile_revision_id,
                            route_id=route.route_id,
                            object_binding_id=binding.id,
                            destination_id=binding.destination_id,
                            required=binding.required,
                            object_key=object_key,
                            public_url=public_url,
                            sha256=artifact.sha256,
                            byte_size=artifact.byte_size,
                            status="failed",
                            error_code=exc.__class__.__name__,
                            error_message=str(exc) or exc.__class__.__name__,
                        )
                    )
                results.append(_object_result(delivery))
        return _result(
            stage="objectDeliver",
            route=route,
            artifact_ids=artifact_ids,
            results=results,
        )

    async def publish_catalogs(  # noqa: C901
        self,
        *,
        artifact_ids: tuple[int, ...],
        route: ResolvedPublishRoute,
        destination_ids: tuple[int, ...] | None = None,
        membership_authorization: PublicationMembershipAuthorization | None = None,
        reconcile_scope: bool = False,
    ) -> PublicationStageResult:
        artifacts = await self._ready_artifacts(artifact_ids, stage="catalogPublish")
        await self._validate_artifact_profile_membership(
            artifact_ids=tuple(artifact.id for artifact in artifacts),
            route=route,
            stage="catalogPublish",
            authorization=membership_authorization,
        )
        bindings = _select_catalog_bindings(route, destination_ids, stage="catalogPublish")
        source_deliveries: dict[tuple[int, int], ObjectDeliveryRecord] = {}
        unavailable_sources: set[tuple[int, int]] = set()
        missing: list[dict[str, object]] = []
        for artifact in artifacts:
            for binding in bindings:
                delivery = await self._checkpoints.get_object_delivery(
                    artifact_id=artifact.id,
                    object_binding_id=binding.source_object_binding_id,
                )
                if delivery is None:
                    missing.append(
                        {
                            "artifactId": artifact.id,
                            "kind": "objectDelivery",
                            "objectBindingId": binding.source_object_binding_id,
                            "catalogBindingId": binding.id,
                        }
                    )
                    continue
                source_deliveries[(artifact.id, binding.id)] = delivery
                if delivery.status != "succeeded":
                    if binding.required:
                        missing.append(
                            {
                                "artifactId": artifact.id,
                                "kind": "objectDelivery",
                                "objectBindingId": binding.source_object_binding_id,
                                "catalogBindingId": binding.id,
                                "status": delivery.status,
                            }
                        )
                    else:
                        unavailable_sources.add((artifact.id, binding.id))
        if missing:
            raise PublicationStagePreconditionFailed(stage="catalogPublish", missing=missing)
        existing_deliveries: dict[tuple[int, int], CatalogDeliveryRecord] = {}
        running: list[dict[str, object]] = []
        for artifact in artifacts:
            for binding in bindings:
                existing = await self._checkpoints.get_catalog_delivery(
                    artifact_id=artifact.id,
                    catalog_binding_id=binding.id,
                )
                if existing is None:
                    continue
                existing_deliveries[(artifact.id, binding.id)] = existing
                if existing.status == "running" and self._has_active_checkpoint_lease(
                    existing.updated_at
                ):
                    running.append(
                        {
                            "kind": "catalogDelivery",
                            "artifactId": artifact.id,
                            "catalogBindingId": binding.id,
                            "status": existing.status,
                        }
                    )
        if running:
            raise PublicationStagePreconditionFailed(stage="catalogPublish", missing=running)
        payloads = {
            artifact.id: parse_timeline_payload(await self._canonical_payload(artifact))
            for artifact in artifacts
        }
        results: list[PublicationDestinationResult] = []
        context = PublicationCatalogContext(
            profile_key=route.profile_key,
            publish_mode=route.publish_mode,
        )
        for artifact in artifacts:
            for binding in bindings:
                existing = existing_deliveries.get((artifact.id, binding.id))
                if existing is not None and existing.status in {"succeeded", "unavailable"}:
                    results.append(_catalog_result(existing, reused=True))
                    continue
                if existing is not None and self._checkpoint_status_for_retry(
                    existing.status,
                    existing.updated_at,
                ) not in {"failed", "pending"}:
                    raise PublicationStagePreconditionFailed(
                        stage="catalogPublish",
                        missing=[
                            {
                                "kind": "catalogDelivery",
                                "artifactId": artifact.id,
                                "catalogBindingId": binding.id,
                                "status": existing.status,
                            }
                        ],
                    )
                source = source_deliveries[(artifact.id, binding.id)]
                base = CatalogDeliveryUpsert(
                    artifact_id=artifact.id,
                    profile_revision_id=route.profile_revision_id,
                    route_id=route.route_id,
                    catalog_binding_id=binding.id,
                    destination_id=binding.destination_id,
                    source_object_delivery_id=source.id,
                    required=binding.required,
                    status="running",
                )
                if (artifact.id, binding.id) in unavailable_sources:
                    delivery = await self._checkpoints.upsert_catalog_delivery(
                        replace(
                            base,
                            status="unavailable",
                            error_code="source_object_unavailable",
                            error_message=("The optional source object delivery did not succeed."),
                        )
                    )
                    results.append(_catalog_result(delivery))
                    continue
                await self._checkpoints.upsert_catalog_delivery(base)
                try:
                    publisher = self._connections.catalog_publisher(binding.connection_ref)
                    await publisher.upsert_video(
                        context,
                        catalog_row_from_timeline(
                            artifact=artifact,
                            payload=payloads[artifact.id],
                            timeline_url=source.public_url,
                        ),
                    )
                    delivery = await self._checkpoints.upsert_catalog_delivery(
                        replace(base, status="succeeded")
                    )
                except Exception as exc:
                    delivery = await self._checkpoints.upsert_catalog_delivery(
                        replace(
                            base,
                            status="failed",
                            error_code=exc.__class__.__name__,
                            error_message=str(exc) or exc.__class__.__name__,
                        )
                    )
                results.append(_catalog_result(delivery))
        if reconcile_scope:
            retained = tuple(
                PublicationCatalogVideoKey(video_id=artifact.video_id, variant=artifact.variant)
                for artifact in artifacts
            )
            for binding in bindings:
                reconciler = self._connections.catalog_reconciler(binding.connection_ref)
                if reconciler is None:
                    continue
                try:
                    await reconciler.reconcile_videos(
                        context,
                        environment=route.environment,
                        retained=retained,
                    )
                    results.append(
                        PublicationDestinationResult(
                            destination_id=binding.destination_id,
                            binding_id=binding.id,
                            destination_type="catalog",
                            required=binding.required,
                            status="succeeded",
                        )
                    )
                except Exception as exc:
                    results.append(
                        PublicationDestinationResult(
                            destination_id=binding.destination_id,
                            binding_id=binding.id,
                            destination_type="catalog",
                            required=binding.required,
                            status="failed",
                            error_code=exc.__class__.__name__,
                            error_message=str(exc) or exc.__class__.__name__,
                        )
                    )
        return _result(
            stage="catalogPublish",
            route=route,
            artifact_ids=artifact_ids,
            results=results,
        )

    async def build_publication(  # noqa: C901
        self,
        *,
        artifact_ids: tuple[int, ...],
        route: ResolvedPublishRoute,
        schema_version: int,
        destination_ids: tuple[int, ...] | None = None,
        membership_authorization: PublicationMembershipAuthorization | None = None,
        publication_identity_key: str | None = None,
    ) -> PublicationStageResult:
        normalized_ids = tuple(sorted(set(artifact_ids)))
        artifacts = await self._ready_artifacts(normalized_ids, stage="publicationBuild")
        await self._validate_artifact_profile_membership(
            artifact_ids=normalized_ids,
            route=route,
            stage="publicationBuild",
            authorization=membership_authorization,
        )
        bindings = _select_object_bindings(route, destination_ids, stage="publicationBuild")
        payloads = {
            artifact.id: parse_timeline_payload(await self._canonical_payload(artifact))
            for artifact in artifacts
        }
        deliveries: dict[tuple[int, int], ObjectDeliveryRecord] = {}
        unavailable_object_bindings: set[int] = set()
        missing: list[dict[str, object]] = []
        for artifact in artifacts:
            for binding in bindings:
                delivery = await self._checkpoints.get_object_delivery(
                    artifact_id=artifact.id,
                    object_binding_id=binding.id,
                )
                if delivery is None:
                    missing.append(
                        {
                            "artifactId": artifact.id,
                            "kind": "objectDelivery",
                            "objectBindingId": binding.id,
                        }
                    )
                    continue
                if delivery.status != "succeeded":
                    if binding.required:
                        missing.append(
                            {
                                "artifactId": artifact.id,
                                "kind": "objectDelivery",
                                "objectBindingId": binding.id,
                                "status": delivery.status,
                            }
                        )
                    else:
                        unavailable_object_bindings.add(binding.id)
                    continue
                deliveries[(artifact.id, binding.id)] = delivery
        selected_object_binding_ids = {binding.id for binding in bindings}
        for catalog_binding in route.catalog_bindings:
            if catalog_binding.source_object_binding_id not in selected_object_binding_ids:
                continue
            for artifact in artifacts:
                delivery = await self._checkpoints.get_catalog_delivery(
                    artifact_id=artifact.id,
                    catalog_binding_id=catalog_binding.id,
                )
                if delivery is None:
                    missing.append(
                        {
                            "artifactId": artifact.id,
                            "kind": "catalogDelivery",
                            "catalogBindingId": catalog_binding.id,
                        }
                    )
                elif delivery.status != "succeeded" and catalog_binding.required:
                    missing.append(
                        {
                            "artifactId": artifact.id,
                            "kind": "catalogDelivery",
                            "catalogBindingId": catalog_binding.id,
                            "status": delivery.status,
                        }
                    )
        if missing:
            raise PublicationStagePreconditionFailed(stage="publicationBuild", missing=missing)
        membership = membership_sha256(normalized_ids)
        version = _version()
        publication = await self._checkpoints.create_or_get_publication(
            PublicationUpsert(
                profile_revision_id=route.profile_revision_id,
                route_id=route.route_id,
                schema_version=schema_version,
                version=version,
                membership_sha256=membership,
                identity_key=(
                    publication_identity_key
                    or _runtime_publication_identity(
                        route=route,
                        schema_version=schema_version,
                        membership=membership,
                    )
                ),
                status="building",
                video_count=len({artifact.video_id for artifact in artifacts}),
                artifact_count=len(artifacts),
            ),
            artifact_ids=normalized_ids,
        )
        current = await self._checkpoints.list_publication_deliveries(publication.id)
        by_binding = {delivery.object_binding_id: delivery for delivery in current}
        running: list[dict[str, object]] = [
            {
                "kind": "publicationIndex",
                "publicationId": publication.id,
                "objectBindingId": binding.id,
                "status": existing.status,
            }
            for binding in bindings
            if (existing := by_binding.get(binding.id)) is not None
            and existing.status == "building"
            and existing.index_succeeded_at is None
            and self._has_active_checkpoint_lease(existing.updated_at)
        ]
        if running:
            raise PublicationStagePreconditionFailed(stage="publicationBuild", missing=running)
        staging = self._connections.object_store(self._staging_store_ref)
        results: list[PublicationDestinationResult] = []
        for binding in bindings:
            existing = by_binding.get(binding.id)
            if existing is not None and existing.index_succeeded_at is not None:
                results.append(_publication_result(existing, reused=True))
                continue
            if existing is not None and existing.status == "unavailable":
                results.append(_publication_result(existing, reused=True))
                continue
            if (
                existing is not None
                and self._checkpoint_status_for_retry(
                    existing.status,
                    existing.updated_at,
                )
                != "failed"
            ):
                raise PublicationStagePreconditionFailed(
                    stage="publicationBuild",
                    missing=[
                        {
                            "kind": "publicationIndex",
                            "publicationId": publication.id,
                            "objectBindingId": binding.id,
                            "status": existing.status,
                        }
                    ],
                )
            if binding.id in unavailable_object_bindings:
                unavailable = await self._checkpoints.upsert_publication_delivery(
                    PublicationDeliveryUpsert(
                        publication_id=publication.id,
                        object_binding_id=binding.id,
                        destination_id=binding.destination_id,
                        required=binding.required,
                        status="unavailable",
                        error_code="artifact_object_unavailable",
                        error_message=("One or more optional artifact object deliveries failed."),
                    )
                )
                results.append(_publication_result(unavailable))
                continue
            target = self._connections.object_store(binding.connection_ref)
            index = build_destination_index(
                artifacts=tuple(
                    (
                        artifact,
                        payloads[artifact.id],
                        deliveries[(artifact.id, binding.id)].public_url,
                    )
                    for artifact in artifacts
                ),
                key_prefix=binding.key_prefix,
                public_url=target.public_url,
                environment=route.environment,
                schema_version=schema_version,
                version=publication.version,
            )
            index_staging_key = (
                f"publications/{publication.id}/destinations/{binding.destination_id}/index.json"
            )
            pointer_staging_key = (
                f"publications/{publication.id}/destinations/{binding.destination_id}/pointer.json"
            )
            base = PublicationDeliveryUpsert(
                publication_id=publication.id,
                object_binding_id=binding.id,
                destination_id=binding.destination_id,
                required=binding.required,
                status="building",
                index_staging_key=index_staging_key,
                index_object_key=index.object_key,
                index_public_url=index.public_url,
                index_sha256=index.sha256,
                index_byte_size=index.byte_size,
                pointer_staging_key=pointer_staging_key,
                pointer_object_key=index.pointer_key,
                pointer_public_url=index.pointer_public_url,
                pointer_sha256=index.pointer_sha256,
                pointer_byte_size=index.pointer_byte_size,
            )
            await self._checkpoints.upsert_publication_delivery(base)
            try:
                await staging.put_bytes(
                    object_key=index_staging_key,
                    payload=index.payload_bytes,
                    content_type="application/json",
                    cache_control=_IMMUTABLE_CACHE_CONTROL,
                )
                await staging.put_bytes(
                    object_key=pointer_staging_key,
                    payload=index.pointer_payload_bytes,
                    content_type="application/json",
                    cache_control=_IMMUTABLE_CACHE_CONTROL,
                )
                await target.put_bytes(
                    object_key=index.object_key,
                    payload=index.payload_bytes,
                    content_type="application/json",
                    cache_control=_IMMUTABLE_CACHE_CONTROL,
                )
                delivery = await self._checkpoints.upsert_publication_delivery(
                    replace(
                        base,
                        status="ready",
                        index_succeeded_at=datetime.now(UTC),
                    )
                )
            except Exception as exc:
                delivery = await self._checkpoints.upsert_publication_delivery(
                    replace(
                        base,
                        status="failed",
                        error_code=exc.__class__.__name__,
                        error_message=str(exc) or exc.__class__.__name__,
                    )
                )
            results.append(_publication_result(delivery))
        status = _stage_status(results)
        await self._checkpoints.set_publication_status(
            publication.id,
            status=(
                "ready"
                if status == "succeeded"
                else "partially_published"
                if status == "succeededWithWarnings"
                else "failed"
            ),
        )
        return _result(
            stage="publicationBuild",
            route=route,
            artifact_ids=normalized_ids,
            results=results,
            publication_id=publication.id,
        )

    async def publish_pointer(  # noqa: C901
        self,
        *,
        publication_id: int,
        destination_ids: tuple[int, ...] | None = None,
        expected_artifact_ids: tuple[int, ...] | None = None,
        expected_profile_revision_id: int | None = None,
        expected_publish_mode: str | None = None,
        expected_environment: str | None = None,
    ) -> PublicationStageResult:
        publication = await self._checkpoints.get_publication(publication_id)
        if publication is None:
            raise PublicationStagePreconditionFailed(
                stage="pointerPublish",
                missing=[{"kind": "publication", "publicationId": publication_id}],
            )
        route = await self._configuration.get_route(publication.route_id)
        if route is None:
            raise PublicationStagePreconditionFailed(
                stage="pointerPublish",
                missing=[{"kind": "route", "routeId": publication.route_id}],
            )
        artifact_ids = await self._validate_pointer_snapshot(
            publication=publication,
            route=route,
            expected_artifact_ids=expected_artifact_ids,
            expected_profile_revision_id=expected_profile_revision_id,
            expected_publish_mode=expected_publish_mode,
            expected_environment=expected_environment,
        )
        bindings = _select_object_bindings(route, destination_ids, stage="pointerPublish")
        staging = self._connections.object_store(self._staging_store_ref)
        results: list[PublicationDestinationResult] = []
        ordered = sorted(bindings, key=lambda binding: binding.is_primary)
        selected_binding_ids = {binding.id for binding in ordered}
        async with self._checkpoints.pointer_lock(
            route_id=route.route_id,
            schema_version=publication.schema_version,
        ):
            current = await self._checkpoints.list_publication_deliveries(publication_id)
            by_binding = {item.object_binding_id: item for item in current}
            running: list[dict[str, object]] = [
                {
                    "kind": "publicationPointer",
                    "publicationId": publication_id,
                    "objectBindingId": binding.id,
                    "status": existing.status,
                }
                for binding in ordered
                if (existing := by_binding.get(binding.id)) is not None
                and existing.status == "building"
                and existing.pointer_succeeded_at is None
                and self._has_active_checkpoint_lease(existing.updated_at)
            ]
            if running:
                raise PublicationStagePreconditionFailed(
                    stage="pointerPublish",
                    missing=running,
                )
            missing: list[dict[str, object]] = [
                {
                    "kind": "publicationIndex",
                    "publicationId": publication_id,
                    "objectBindingId": binding.id,
                    **(
                        {"status": by_binding[binding.id].status}
                        if binding.id in by_binding
                        else {}
                    ),
                }
                for binding in route.object_bindings
                if binding.required
                and (
                    binding.id not in by_binding
                    or by_binding[binding.id].index_succeeded_at is None
                )
            ]
            if missing:
                raise PublicationStagePreconditionFailed(
                    stage="pointerPublish",
                    missing=missing,
                )
            pointer_succeeded_binding_ids = {
                delivery.object_binding_id
                for delivery in current
                if delivery.pointer_succeeded_at is not None
            }
            regressions: list[dict[str, object]] = [
                {
                    "kind": "newerPublicationPointer",
                    "publicationId": publication_id,
                    "objectBindingId": binding.id,
                }
                for binding in ordered
                if (
                    by_binding.get(binding.id) is not None
                    and by_binding[binding.id].index_succeeded_at is not None
                    and by_binding[binding.id].pointer_succeeded_at is None
                )
                and await self._checkpoints.has_newer_pointer_delivery(
                    route_id=route.route_id,
                    schema_version=publication.schema_version,
                    object_binding_id=binding.id,
                    publication_id=publication.id,
                )
            ]
            if regressions:
                raise PublicationStagePreconditionFailed(
                    stage="pointerPublish",
                    missing=regressions,
                )
            for binding in ordered:
                existing = by_binding.get(binding.id)
                if existing is not None and existing.pointer_succeeded_at is not None:
                    results.append(_publication_result(existing, reused=True))
                    pointer_succeeded_binding_ids.add(binding.id)
                    continue
                if existing is not None and existing.status == "unavailable":
                    results.append(_publication_result(existing, reused=True))
                    continue
                if binding.is_primary:
                    missing_required_pointers = [
                        candidate.id
                        for candidate in route.object_bindings
                        if candidate.required
                        and not candidate.is_primary
                        and candidate.id not in pointer_succeeded_binding_ids
                    ]
                    if missing_required_pointers:
                        if not any(
                            binding_id in selected_binding_ids
                            for binding_id in missing_required_pointers
                        ):
                            raise PublicationStagePreconditionFailed(
                                stage="pointerPublish",
                                missing=[
                                    {
                                        "kind": "requiredDestinationPointer",
                                        "publicationId": publication_id,
                                        "objectBindingId": binding_id,
                                    }
                                    for binding_id in missing_required_pointers
                                ],
                            )
                        if existing is None:
                            raise PublicationStagePreconditionFailed(
                                stage="pointerPublish",
                                missing=[
                                    {
                                        "kind": "publicationDelivery",
                                        "publicationId": publication_id,
                                        "objectBindingId": binding.id,
                                    }
                                ],
                            )
                        failed_primary = await self._checkpoints.upsert_publication_delivery(
                            _replace_publication_delivery(
                                existing,
                                status="failed",
                                error_code="required_destination_pointer_failed",
                                error_message=(
                                    "Required non-primary destination pointers did not succeed: "
                                    + ", ".join(
                                        str(binding_id) for binding_id in missing_required_pointers
                                    )
                                ),
                            )
                        )
                        by_binding[binding.id] = failed_primary
                        results.append(_publication_result(failed_primary))
                        continue
                if existing is None:
                    if not binding.required:
                        unavailable = await self._checkpoints.upsert_publication_delivery(
                            PublicationDeliveryUpsert(
                                publication_id=publication.id,
                                object_binding_id=binding.id,
                                destination_id=binding.destination_id,
                                required=False,
                                status="unavailable",
                                error_code="publication_index_missing",
                                error_message=(
                                    "The optional destination index has not been built."
                                ),
                            )
                        )
                        results.append(_publication_result(unavailable))
                        continue
                    raise PublicationStagePreconditionFailed(
                        stage="pointerPublish",
                        missing=[
                            {
                                "kind": "publicationDelivery",
                                "publicationId": publication_id,
                                "objectBindingId": binding.id,
                            }
                        ],
                    )
                if existing.index_succeeded_at is None:
                    if not binding.required:
                        results.append(_publication_result(existing, reused=True))
                        continue
                    raise PublicationStagePreconditionFailed(
                        stage="pointerPublish",
                        missing=[
                            {
                                "kind": "publicationIndex",
                                "publicationId": publication_id,
                                "objectBindingId": binding.id,
                                "status": existing.status,
                            }
                        ],
                    )
                if not existing.pointer_staging_key or not existing.pointer_object_key:
                    if not binding.required:
                        results.append(_publication_result(existing, reused=True))
                        continue
                    raise PublicationStagePreconditionFailed(
                        stage="pointerPublish",
                        missing=[
                            {
                                "kind": "stagedPointer",
                                "publicationId": publication_id,
                                "objectBindingId": binding.id,
                            }
                        ],
                    )
                if existing.status not in {"ready", "failed"}:
                    raise PublicationStagePreconditionFailed(
                        stage="pointerPublish",
                        missing=[
                            {
                                "kind": "publicationPointer",
                                "publicationId": publication_id,
                                "objectBindingId": binding.id,
                                "status": existing.status,
                            }
                        ],
                    )
                try:
                    payload = await staging.get_bytes(object_key=existing.pointer_staging_key)
                    if (
                        existing.pointer_sha256 is None
                        or hashlib.sha256(payload).hexdigest() != existing.pointer_sha256
                    ):
                        raise ValueError("Staged pointer SHA-256 mismatch.")
                    target = self._connections.object_store(binding.connection_ref)
                    await target.put_bytes(
                        object_key=existing.pointer_object_key,
                        payload=payload,
                        content_type="application/json",
                        cache_control=_POINTER_CACHE_CONTROL,
                    )
                    delivery = await self._checkpoints.upsert_publication_delivery(
                        _replace_publication_delivery(
                            existing,
                            status="published",
                            pointer_succeeded_at=datetime.now(UTC),
                            error_code=None,
                            error_message=None,
                        )
                    )
                except Exception as exc:
                    delivery = await self._checkpoints.upsert_publication_delivery(
                        _replace_publication_delivery(
                            existing,
                            status="failed",
                            error_code=exc.__class__.__name__,
                            error_message=str(exc) or exc.__class__.__name__,
                        )
                    )
                results.append(_publication_result(delivery))
                by_binding[binding.id] = delivery
                if delivery.pointer_succeeded_at is not None:
                    pointer_succeeded_binding_ids.add(binding.id)
        await self._set_pointer_publication_status(
            publication_id=publication_id,
            route=route,
            results=results,
        )
        return _result(
            stage="pointerPublish",
            route=route,
            artifact_ids=artifact_ids,
            results=results,
            publication_id=publication_id,
        )

    async def publish_composite(
        self,
        *,
        artifact_ids: tuple[int, ...],
        context: RoutedArchivePublishContext,
        schema_version: int,
    ) -> RoutedArchivePublishResult:
        route = await self.revision_route(
            profile_revision_id=context.profile_revision_id,
            publish_mode=context.publish_mode,
            environment=context.environment,
        )
        if route.route_id != context.route_id:
            raise PublicationStagePreconditionFailed(
                stage="routeResolve",
                missing=[
                    {
                        "kind": "routeSnapshot",
                        "expectedRouteId": context.route_id,
                        "resolvedRouteId": route.route_id,
                    }
                ],
            )
        object_result = await self.deliver_objects(
            artifact_ids=artifact_ids,
            route=route,
        )
        _require_composite_success(object_result)
        catalog_result = await self.publish_catalogs(
            artifact_ids=artifact_ids,
            route=route,
        )
        _require_composite_success(catalog_result)
        build_result = await self.build_publication(
            artifact_ids=artifact_ids,
            route=route,
            schema_version=schema_version,
        )
        _require_composite_success(build_result)
        if build_result.publication_id is None:
            raise RuntimeError("Publication build did not create a publication.")
        pointer_result = await self.publish_pointer(publication_id=build_result.publication_id)
        _require_composite_success(pointer_result)
        deliveries = await self._checkpoints.list_publication_deliveries(
            build_result.publication_id
        )
        primary_binding = _primary_binding(route)
        primary = _delivery_by_binding(deliveries, primary_binding.id)
        publication = await self._checkpoints.get_publication(build_result.publication_id)
        if primary is None or publication is None:
            raise RuntimeError("Primary publication delivery is missing.")
        if not all(
            (
                primary.index_object_key,
                primary.index_public_url,
                primary.pointer_object_key,
                primary.pointer_public_url,
                primary.index_sha256,
                primary.index_byte_size,
            )
        ):
            raise RuntimeError("Primary publication delivery is incomplete.")
        composite_status = (
            "succeededWithWarnings"
            if any(
                result.status == "succeededWithWarnings"
                for result in (
                    object_result,
                    catalog_result,
                    build_result,
                    pointer_result,
                )
            )
            else "succeeded"
        )
        if composite_status == "succeededWithWarnings":
            await self._checkpoints.set_publication_status(
                publication.id,
                status="partially_published",
            )
        return RoutedArchivePublishResult(
            publication_id=publication.id,
            primary_index_key=primary.index_object_key or "",
            primary_index_url=primary.index_public_url or "",
            primary_pointer_key=primary.pointer_object_key or "",
            primary_pointer_url=primary.pointer_public_url or "",
            index_version=publication.version,
            index_sha256=primary.index_sha256 or "",
            index_byte_size=primary.index_byte_size or 0,
            video_count=publication.video_count,
            status=composite_status,
        )

    async def _required_artifacts(
        self,
        artifact_ids: tuple[int, ...],
        *,
        stage: str,
    ) -> list[ArchiveVideoArtifactRecord]:
        normalized = tuple(dict.fromkeys(artifact_ids))
        records = await self._checkpoints.get_artifacts(normalized)
        found = {record.id for record in records}
        missing: list[dict[str, object]] = [
            {"kind": "artifact", "artifactId": artifact_id}
            for artifact_id in normalized
            if artifact_id not in found
        ]
        if missing:
            raise PublicationStagePreconditionFailed(stage=stage, missing=missing)
        return records

    async def _ready_artifacts(
        self,
        artifact_ids: tuple[int, ...],
        *,
        stage: str,
    ) -> list[ArchiveVideoArtifactRecord]:
        records = await self._required_artifacts(artifact_ids, stage=stage)
        missing: list[dict[str, object]] = [
            {
                "kind": "canonicalArtifact",
                "artifactId": artifact.id,
                "status": artifact.artifact_status,
            }
            for artifact in records
            if artifact.artifact_status != "ready"
            or not artifact.artifact_store_ref
            or not artifact.artifact_key
        ]
        if missing:
            raise PublicationStagePreconditionFailed(stage=stage, missing=missing)
        return records

    async def _validate_artifact_profile_membership(
        self,
        *,
        artifact_ids: tuple[int, ...],
        route: ResolvedPublishRoute,
        stage: str,
        authorization: PublicationMembershipAuthorization | None,
    ) -> None:
        assignments = await self._checkpoints.get_artifact_publish_profile_assignments(artifact_ids)
        by_artifact_id = {assignment.artifact_id: assignment for assignment in assignments}
        authorization_valid = (
            authorization is not None
            and authorization.purpose == "cutover_target"
            and authorization.target_profile_id == route.profile_id
            and authorization.artifact_ids == artifact_ids
        )
        missing: list[dict[str, object]] = []
        for artifact_id in artifact_ids:
            assignment = by_artifact_id.get(artifact_id)
            if assignment is None:
                missing.append(
                    {
                        "kind": "artifactPublishProfile",
                        "artifactId": artifact_id,
                        "reason": "assignment_missing",
                    }
                )
                continue
            if assignment.publish_profile_id == route.profile_id:
                continue
            mismatch_authorized = (
                authorization_valid
                and authorization is not None
                and assignment.streamer_id == authorization.streamer_id
                and assignment.publish_profile_id == authorization.source_profile_id
            )
            if mismatch_authorized:
                continue
            missing.append(
                {
                    "kind": "artifactPublishProfile",
                    "artifactId": artifact_id,
                    "streamerId": assignment.streamer_id,
                    "expectedProfileId": route.profile_id,
                    "actualProfileId": assignment.publish_profile_id,
                }
            )
        if missing:
            raise PublicationStagePreconditionFailed(stage=stage, missing=missing)

    async def _canonical_payload(self, artifact: ArchiveVideoArtifactRecord) -> bytes:
        if not artifact.artifact_store_ref or not artifact.artifact_key:
            raise PublicationStagePreconditionFailed(
                stage="canonicalRead",
                missing=[{"kind": "canonicalArtifact", "artifactId": artifact.id}],
            )
        store = self._connections.object_store(artifact.artifact_store_ref)
        payload = await store.get_bytes(object_key=artifact.artifact_key)
        _verify_artifact_payload(artifact, payload)
        return payload

    def _checkpoint_status_for_retry(
        self,
        status: str,
        updated_at: datetime | None,
    ) -> str:
        if status in {"running", "building"} and not self._has_active_checkpoint_lease(updated_at):
            return "failed"
        return status

    def _has_active_checkpoint_lease(self, updated_at: datetime | None) -> bool:
        if updated_at is None:
            return True
        return _as_utc(updated_at) > _as_utc(self._clock()) - self._checkpoint_lease_timeout

    async def _validate_pointer_snapshot(
        self,
        *,
        publication: PublicationRecord,
        route: ResolvedPublishRoute,
        expected_artifact_ids: tuple[int, ...] | None,
        expected_profile_revision_id: int | None,
        expected_publish_mode: str | None,
        expected_environment: str | None,
    ) -> tuple[int, ...]:
        artifact_ids = tuple(
            sorted(await self._checkpoints.list_publication_artifact_ids(publication.id))
        )
        expectations = (
            expected_artifact_ids,
            expected_profile_revision_id,
            expected_publish_mode,
            expected_environment,
        )
        if not any(value is not None for value in expectations):
            return artifact_ids
        if not all(value is not None for value in expectations):
            raise PublicationStagePreconditionFailed(
                stage="pointerPublish",
                missing=[
                    {
                        "kind": "publicationRequestSnapshot",
                        "publicationId": publication.id,
                        "reason": "incomplete_expectations",
                    }
                ],
            )
        mismatches: list[dict[str, object]] = []
        normalized_expected_ids = tuple(sorted(expected_artifact_ids or ()))
        if normalized_expected_ids != artifact_ids:
            mismatches.append(
                {
                    "kind": "publicationMembershipSnapshot",
                    "publicationId": publication.id,
                    "expectedArtifactIds": list(normalized_expected_ids),
                    "actualArtifactIds": list(artifact_ids),
                }
            )
        if (
            expected_profile_revision_id != publication.profile_revision_id
            or expected_profile_revision_id != route.profile_revision_id
        ):
            mismatches.append(
                {
                    "kind": "profileRevisionSnapshot",
                    "publicationId": publication.id,
                    "expectedProfileRevisionId": expected_profile_revision_id,
                    "publicationProfileRevisionId": publication.profile_revision_id,
                    "routeProfileRevisionId": route.profile_revision_id,
                }
            )
        if expected_publish_mode != route.publish_mode:
            mismatches.append(
                {
                    "kind": "publishModeSnapshot",
                    "publicationId": publication.id,
                    "expectedPublishMode": expected_publish_mode,
                    "actualPublishMode": route.publish_mode,
                }
            )
        if expected_environment != route.environment:
            mismatches.append(
                {
                    "kind": "environmentSnapshot",
                    "publicationId": publication.id,
                    "expectedEnvironment": expected_environment,
                    "actualEnvironment": route.environment,
                }
            )
        if mismatches:
            raise PublicationStagePreconditionFailed(
                stage="pointerPublish",
                missing=mismatches,
            )
        return artifact_ids

    async def _set_pointer_publication_status(
        self,
        *,
        publication_id: int,
        route: ResolvedPublishRoute,
        results: list[PublicationDestinationResult],
    ) -> None:
        final_deliveries = await self._checkpoints.list_publication_deliveries(publication_id)
        published_bindings = {
            delivery.object_binding_id
            for delivery in final_deliveries
            if delivery.pointer_succeeded_at is not None
        }
        all_pointers_published = all(
            binding.id in published_bindings for binding in route.object_bindings
        )
        stage_status = _stage_status(results)
        await self._checkpoints.set_publication_status(
            publication_id,
            status=(
                "published"
                if all_pointers_published
                else "partially_published"
                if published_bindings
                else "failed"
                if stage_status == "failed"
                else "partially_published"
            ),
        )


def _primary_binding(route: ResolvedPublishRoute) -> ResolvedObjectBinding:
    primary = [binding for binding in route.object_bindings if binding.is_primary]
    if len(primary) != 1:
        raise PublicationStagePreconditionFailed(
            stage="routeResolve",
            missing=[
                {
                    "kind": "primaryObjectBinding",
                    "routeId": route.route_id,
                    "found": len(primary),
                }
            ],
        )
    return primary[0]


def _select_object_bindings(
    route: ResolvedPublishRoute,
    destination_ids: tuple[int, ...] | None,
    *,
    stage: str,
) -> tuple[ResolvedObjectBinding, ...]:
    if destination_ids is None:
        return route.object_bindings
    requested = set(destination_ids)
    selected = tuple(
        binding for binding in route.object_bindings if binding.destination_id in requested
    )
    found = {binding.destination_id for binding in selected}
    if requested - found:
        raise PublicationStagePreconditionFailed(
            stage=stage,
            missing=[
                {"kind": "objectDestination", "destinationId": value}
                for value in sorted(requested - found)
            ],
        )
    return selected


def _select_catalog_bindings(
    route: ResolvedPublishRoute,
    destination_ids: tuple[int, ...] | None,
    *,
    stage: str,
):
    if destination_ids is None:
        return route.catalog_bindings
    requested = set(destination_ids)
    selected = tuple(
        binding for binding in route.catalog_bindings if binding.destination_id in requested
    )
    found = {binding.destination_id for binding in selected}
    if requested - found:
        raise PublicationStagePreconditionFailed(
            stage=stage,
            missing=[
                {"kind": "catalogDestination", "destinationId": value}
                for value in sorted(requested - found)
            ],
        )
    return selected


def _verify_artifact_payload(
    artifact: ArchiveVideoArtifactRecord,
    payload: bytes,
) -> None:
    if len(payload) != artifact.byte_size:
        raise ValueError(f"Artifact {artifact.id} byte size mismatch.")
    if hashlib.sha256(payload).hexdigest() != artifact.sha256:
        raise ValueError(f"Artifact {artifact.id} SHA-256 mismatch.")


def _require_retryable_checkpoint(
    *,
    status: str | None,
    stage: str,
    missing: dict[str, object],
) -> None:
    if status is None or status in {"failed", "pending"}:
        return
    raise PublicationStagePreconditionFailed(stage=stage, missing=[missing])


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _stage_status(
    results: list[PublicationDestinationResult],
) -> PublicationStageStatus:
    failed_required = any(
        result.required and result.status not in {"succeeded", "ready", "published"}
        for result in results
    )
    if failed_required:
        return "failed"
    failed_optional = any(
        not result.required and result.status not in {"succeeded", "ready", "published"}
        for result in results
    )
    return "succeededWithWarnings" if failed_optional else "succeeded"


def _result(
    *,
    stage: str,
    route: ResolvedPublishRoute,
    artifact_ids: tuple[int, ...],
    results: list[PublicationDestinationResult],
    publication_id: int | None = None,
) -> PublicationStageResult:
    return PublicationStageResult(
        stage=stage,  # type: ignore[arg-type]
        status=_stage_status(results),  # type: ignore[arg-type]
        artifact_ids=artifact_ids,
        profile_revision_id=route.profile_revision_id,
        route_id=route.route_id,
        publication_id=publication_id,
        destination_results=tuple(results),
    )


def _object_result(
    delivery: ObjectDeliveryRecord,
    *,
    reused: bool = False,
) -> PublicationDestinationResult:
    return PublicationDestinationResult(
        destination_id=delivery.destination_id,
        binding_id=delivery.object_binding_id,
        destination_type="object",
        required=delivery.required,
        status=delivery.status,
        reused=reused,
        public_url=delivery.public_url,
        error_code=delivery.error_code,
        error_message=delivery.error_message,
    )


def _catalog_result(
    delivery: CatalogDeliveryRecord,
    *,
    reused: bool = False,
) -> PublicationDestinationResult:
    return PublicationDestinationResult(
        destination_id=delivery.destination_id,
        binding_id=delivery.catalog_binding_id,
        destination_type="catalog",
        required=delivery.required,
        status=delivery.status,
        reused=reused,
        error_code=delivery.error_code,
        error_message=delivery.error_message,
    )


def _publication_result(
    delivery: PublicationDeliveryRecord,
    *,
    reused: bool = False,
) -> PublicationDestinationResult:
    return PublicationDestinationResult(
        destination_id=delivery.destination_id,
        binding_id=delivery.object_binding_id,
        destination_type="object",
        required=delivery.required,
        status=delivery.status,
        reused=reused,
        public_url=delivery.index_public_url,
        error_code=delivery.error_code,
        error_message=delivery.error_message,
    )


def _failed_result(
    destination_id: int,
    binding_id: int,
    destination_type: str,
    required: bool,
    exc: Exception,
    *,
    unavailable: bool = False,
) -> PublicationDestinationResult:
    return PublicationDestinationResult(
        destination_id=destination_id,
        binding_id=binding_id,
        destination_type=destination_type,  # type: ignore[arg-type]
        required=required,
        status="unavailable" if unavailable else "failed",
        error_code=exc.__class__.__name__,
        error_message=str(exc) or exc.__class__.__name__,
    )


def _delivery_by_binding(
    deliveries: tuple[PublicationDeliveryRecord, ...],
    binding_id: int,
) -> PublicationDeliveryRecord | None:
    return next(
        (item for item in deliveries if item.object_binding_id == binding_id),
        None,
    )


def _replace_publication_delivery(
    delivery: PublicationDeliveryRecord,
    **changes: object,
) -> PublicationDeliveryUpsert:
    values = {
        field: getattr(delivery, field) for field in PublicationDeliveryUpsert.__dataclass_fields__
    }
    values.update(changes)
    return PublicationDeliveryUpsert(**values)  # type: ignore[arg-type]


def _require_composite_success(result: PublicationStageResult) -> None:
    if result.status == "failed":
        failures = [
            destination
            for destination in result.destination_results
            if destination.required
            and destination.status not in {"succeeded", "ready", "published"}
        ]
        message = "; ".join(
            destination.error_message or destination.error_code or destination.status
            for destination in failures
        )
        raise RuntimeError(f"Required {result.stage} destination failed: {message}")


def _version() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")


def _runtime_publication_identity(
    *,
    route: ResolvedPublishRoute,
    schema_version: int,
    membership: str,
) -> str:
    return f"runtime:{route.profile_revision_id}:{route.route_id}:{schema_version}:{membership}"
