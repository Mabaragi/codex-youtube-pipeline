from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from codex_sdk_cli.application.publication_config.ports import (
    ResolvedObjectBinding,
    ResolvedPublishRoute,
)
from codex_sdk_cli.domains.archive_publish.checkpoints import (
    CatalogDeliveryUpsert,
    ObjectDeliveryRecord,
    ObjectDeliveryUpsert,
    PublicationDeliveryRecord,
    PublicationDeliveryUpsert,
    PublicationUpsert,
)
from codex_sdk_cli.domains.archive_publish.ports import ArchiveVideoArtifactRecord
from codex_sdk_cli.domains.publication.ports import (
    PublicationCatalogContext,
    PublicationCatalogRowVerification,
    PublicationObjectStorePort,
)
from codex_sdk_cli.infra.archive_publish.checkpoints import (
    ArchivePublicationModel,
    SqlAlchemyArchivePublicationCheckpointRepository,
)
from codex_sdk_cli.infra.archive_publish.repository import (
    ArchiveIndexPublicationModel,
    ArchiveVideoArtifactModel,
    _artifact_record,
)
from codex_sdk_cli.infra.channels.repository import ChannelModel
from codex_sdk_cli.infra.publication.factory import PublicationConnectionFactory
from codex_sdk_cli.infra.publication.migration_integrity import (
    validate_current_remote_membership,
    verify_available_historical_local_indexes,
)
from codex_sdk_cli.infra.publication.projection import (
    build_destination_index,
    canonical_artifact_key,
    catalog_row_from_timeline,
    destination_artifact_key,
    membership_sha256,
    parse_timeline_payload,
)
from codex_sdk_cli.infra.publication_config.repository import (
    SqlAlchemyPublishConfigurationRepository,
)
from codex_sdk_cli.infra.streamers.repository import StreamerModel
from codex_sdk_cli.infra.videos.repository import VideoModel

PublicationMigrationMode = Literal["dry-run", "apply", "resume", "verify"]
_IMMUTABLE_CACHE_CONTROL = "public, max-age=31536000, immutable"
_POINTER_CACHE_CONTROL = "public, max-age=60, must-revalidate"


@dataclass(frozen=True, slots=True)
class PublicationMigrationRequest:
    mode: PublicationMigrationMode
    profile_revision_id: int = 1
    publish_mode: str = "prod"
    environment: str = "prod"
    schema_version: int = 1
    latest_limit: int = 180
    expected_artifact_count: int | None = 802
    expected_ready_count: int | None = 450
    expected_unavailable_count: int | None = 352
    expected_latest_count: int | None = 179
    expected_history_count: int | None = 416
    source_manifest: Path | None = None

    @property
    def mutates(self) -> bool:
        return self.mode in {"apply", "resume"}


class PublicationMigrationSourceError(RuntimeError):
    """The legacy source could not be inspected reliably."""


@dataclass(frozen=True, slots=True)
class _MigratedIndexResult:
    artifact_ids: tuple[int, ...]
    publication_id: int | None


class PublicationDataMigrator:
    def __init__(
        self,
        *,
        session: AsyncSession,
        connections: PublicationConnectionFactory,
        artifact_store_ref: str,
        staging_store_ref: str,
    ) -> None:
        self._session = session
        self._connections = connections
        self._artifact_store_ref = artifact_store_ref
        self._staging_store_ref = staging_store_ref
        self._configuration = SqlAlchemyPublishConfigurationRepository(session)
        self._checkpoints = SqlAlchemyArchivePublicationCheckpointRepository(session)

    async def run(self, request: PublicationMigrationRequest) -> dict[str, object]:
        if request.mode in {"apply", "resume", "verify"} and request.source_manifest is None:
            raise ValueError("--source-manifest is required for apply, resume, and verify.")
        manifest_keys = (
            _manifest_keys(request.source_manifest) if request.source_manifest is not None else None
        )
        route = await self._configuration.resolve_revision_route(
            profile_revision_id=request.profile_revision_id,
            publish_mode=cast(AnyPublishMode, request.publish_mode),
            environment=request.environment,
        )
        if route is None:
            raise ValueError(
                "Publication profile revision has no route for the requested mode/environment."
            )
        primary = _primary_binding(route)
        source_store = self._connections.object_store(primary.connection_ref)
        canonical_store = self._connections.object_store(self._artifact_store_ref)
        staging_store = self._connections.object_store(self._staging_store_ref)
        artifacts = await self._artifact_models(route, request)
        index_models = await self._index_models(request)
        report = _new_report(request, route, len(artifacts))
        ready_payloads: dict[int, bytes] = {}
        artifact_records: dict[int, ArchiveVideoArtifactRecord] = {}
        object_deliveries: dict[tuple[int, int], ObjectDeliveryRecord] = {}

        for model in artifacts:
            record = _artifact_record(model)
            artifact_records[record.id] = record
            await self._migrate_artifact(
                request=request,
                route=route,
                primary=primary,
                artifact=record,
                source_store=source_store,
                canonical_store=canonical_store,
                ready_payloads=ready_payloads,
                object_deliveries=object_deliveries,
                report=report,
            )

        pointer = await self._read_legacy_pointer(
            request=request,
            primary=primary,
            source_store=source_store,
            staging_store=staging_store,
            report=report,
        )
        current_index_url = _string(pointer.get("currentIndexUrl")) if pointer else None
        historical_memberships: dict[str, tuple[int, ...]] = {}
        available_index_models: list[ArchiveIndexPublicationModel] = []
        for index_model in index_models:
            migrated_index = await self._migrate_index(
                request=request,
                route=route,
                primary=primary,
                index_model=index_model,
                current_index_url=current_index_url,
                source_store=source_store,
                staging_store=staging_store,
                artifact_records=artifact_records,
                ready_payloads=ready_payloads,
                object_deliveries=object_deliveries,
                report=report,
            )
            if migrated_index is not None:
                available_index_models.append(index_model)
                historical_memberships[index_model.public_url] = migrated_index.artifact_ids
        await self._preserve_manifest_only_history(
            request=request,
            manifest_keys=manifest_keys,
            index_models=index_models,
            primary=primary,
            source_store=source_store,
            staging_store=staging_store,
            report=report,
        )
        if request.mode == "verify":
            await self._verify_history_checkpoints(
                route=route,
                primary=primary,
                index_models=available_index_models,
                report=report,
            )

        latest_ids = await self._latest_artifact_ids(
            request=request,
            route=route,
            ready_ids=set(ready_payloads),
        )
        report["latest"]["selected"] = len(latest_ids)  # type: ignore[index]
        report["latest"]["artifactIds"] = list(latest_ids)  # type: ignore[index]
        current_membership_valid = _validate_current_remote_membership(
            request=request,
            current_index_url=current_index_url,
            historical_memberships=historical_memberships,
            latest_ids=latest_ids,
            report=report,
        )
        if current_membership_valid:
            await self._publish_latest_local(
                request=request,
                route=route,
                primary=primary,
                artifact_ids=latest_ids,
                artifact_records=artifact_records,
                ready_payloads=ready_payloads,
                object_deliveries=object_deliveries,
                staging_store=staging_store,
                report=report,
            )
        await self._replay_catalogs(
            request=request,
            route=route,
            primary=primary,
            artifact_ids=latest_ids,
            artifact_records=artifact_records,
            ready_payloads=ready_payloads,
            object_deliveries=object_deliveries,
            report=report,
        )
        _add_manifest_comparison(
            manifest_keys,
            artifacts,
            index_models,
            ready_ids=set(ready_payloads),
            report=report,
        )
        _finish_report(request, report)
        return report

    async def _artifact_models(
        self,
        route: ResolvedPublishRoute,
        request: PublicationMigrationRequest,
    ) -> list[ArchiveVideoArtifactModel]:
        statement = (
            select(ArchiveVideoArtifactModel)
            .join(VideoModel, VideoModel.id == ArchiveVideoArtifactModel.video_id)
            .join(ChannelModel, ChannelModel.id == VideoModel.channel_id)
            .join(StreamerModel, StreamerModel.id == ChannelModel.streamer_id)
            .where(
                StreamerModel.publish_profile_id == route.profile_id,
                ArchiveVideoArtifactModel.environment == request.environment,
                ArchiveVideoArtifactModel.schema_version == request.schema_version,
            )
            .order_by(ArchiveVideoArtifactModel.id)
        )
        return list((await self._session.scalars(statement)).all())

    async def _index_models(
        self,
        request: PublicationMigrationRequest,
    ) -> list[ArchiveIndexPublicationModel]:
        statement = (
            select(ArchiveIndexPublicationModel)
            .where(
                ArchiveIndexPublicationModel.environment == request.environment,
                ArchiveIndexPublicationModel.schema_version == request.schema_version,
            )
            .order_by(ArchiveIndexPublicationModel.id)
        )
        return list((await self._session.scalars(statement)).all())

    async def _migrate_artifact(  # noqa: C901 - migration steps stay auditable together
        self,
        *,
        request: PublicationMigrationRequest,
        route: ResolvedPublishRoute,
        primary: ResolvedObjectBinding,
        artifact: ArchiveVideoArtifactRecord,
        source_store: PublicationObjectStorePort,
        canonical_store: PublicationObjectStorePort,
        ready_payloads: dict[int, bytes],
        object_deliveries: dict[tuple[int, int], ObjectDeliveryRecord],
        report: dict[str, object],
    ) -> None:
        artifact_report = cast(dict[str, object], report["artifacts"])
        payload = await _read_legacy_source_object(
            source_store,
            object_key=artifact.object_key,
            object_kind="artifact",
        )
        if payload is None:
            await self._mark_source_missing(request, artifact, report)
            return
        actual_sha256 = _sha256(payload)
        if len(payload) != artifact.byte_size or actual_sha256 != artifact.sha256:
            mismatches = cast(list[dict[str, object]], artifact_report["mismatches"])
            mismatches.append(
                {
                    "artifactId": artifact.id,
                    "objectKey": artifact.object_key,
                    "expectedSha256": artifact.sha256,
                    "actualSha256": actual_sha256,
                    "expectedBytes": artifact.byte_size,
                    "actualBytes": len(payload),
                }
            )
            return

        _increment(artifact_report, "ready")
        ready_payloads[artifact.id] = payload
        canonical_key = canonical_artifact_key(artifact.sha256)
        if request.mode == "verify" and (
            artifact.artifact_status != "ready"
            or artifact.artifact_store_ref != self._artifact_store_ref
            or artifact.artifact_key != canonical_key
        ):
            _block(
                report,
                "canonical_artifact_checkpoint_mismatch",
                artifactId=artifact.id,
                status=artifact.artifact_status,
            )
        if request.mutates:
            copied = await _ensure_immutable_object(
                canonical_store,
                object_key=canonical_key,
                payload=payload,
            )
            _increment(artifact_report, "canonicalCopied", int(copied))
            await self._checkpoints.set_artifact_canonical(
                artifact_id=artifact.id,
                build_key=artifact.build_key
                or _legacy_artifact_build_key(artifact.id, artifact.sha256),
                store_ref=self._artifact_store_ref,
                artifact_key=canonical_key,
            )
        else:
            canonical_stat = await canonical_store.stat_object(object_key=canonical_key)
            if canonical_stat is None:
                if request.mode == "verify":
                    _block(
                        report,
                        "canonical_object_missing",
                        artifactId=artifact.id,
                        objectKey=canonical_key,
                    )
                else:
                    _increment(artifact_report, "canonicalWouldCopy")
            elif canonical_stat.byte_size != artifact.byte_size:
                _block(
                    report,
                    "canonical_size_mismatch",
                    artifactId=artifact.id,
                    objectKey=canonical_key,
                )
            elif request.mode == "verify":
                canonical_payload = await canonical_store.get_bytes(object_key=canonical_key)
                if _sha256(canonical_payload) != artifact.sha256:
                    _block(
                        report,
                        "canonical_sha256_mismatch",
                        artifactId=artifact.id,
                        objectKey=canonical_key,
                    )

        for binding in route.object_bindings:
            destination_store = self._connections.object_store(binding.connection_ref)
            if binding.id == primary.id:
                object_key = artifact.object_key
                public_url = artifact.public_url
            else:
                object_key = destination_artifact_key(
                    artifact,
                    key_prefix=binding.key_prefix,
                )
                public_url = destination_store.public_url(object_key)
                if request.mutates:
                    copied = await _ensure_immutable_object(
                        destination_store,
                        object_key=object_key,
                        payload=payload,
                    )
                    _increment(
                        artifact_report,
                        "publicationObjectsCopied",
                        int(copied),
                    )
                else:
                    target_stat = await destination_store.stat_object(object_key=object_key)
                    if target_stat is None:
                        if request.mode == "verify":
                            _block(
                                report,
                                "publication_object_missing",
                                artifactId=artifact.id,
                                bindingId=binding.id,
                            )
                        else:
                            _increment(artifact_report, "publicationObjectsWouldCopy")
                    elif target_stat.byte_size != artifact.byte_size:
                        _block(
                            report,
                            "publication_object_size_mismatch",
                            artifactId=artifact.id,
                            bindingId=binding.id,
                        )
                    elif request.mode == "verify":
                        target_payload = await destination_store.get_bytes(object_key=object_key)
                        if _sha256(target_payload) != artifact.sha256:
                            _block(
                                report,
                                "publication_object_sha256_mismatch",
                                artifactId=artifact.id,
                                bindingId=binding.id,
                            )
            if request.mutates:
                delivery = await self._succeeded_object_delivery(
                    artifact=artifact,
                    route=route,
                    binding=binding,
                    object_key=object_key,
                    public_url=public_url,
                )
                object_deliveries[(artifact.id, binding.id)] = delivery

    async def _mark_source_missing(
        self,
        request: PublicationMigrationRequest,
        artifact: ArchiveVideoArtifactRecord,
        report: dict[str, object],
        *,
        detail: str = "Legacy source object is absent.",
    ) -> None:
        artifact_report = cast(dict[str, object], report["artifacts"])
        _increment(artifact_report, "unavailable")
        missing = cast(list[dict[str, object]], artifact_report["missing"])
        missing.append(
            {
                "artifactId": artifact.id,
                "objectKey": artifact.object_key,
                "reason": "legacy_source_missing",
            }
        )
        if request.mode == "verify" and (
            artifact.artifact_status != "unavailable"
            or artifact.unavailable_code != "legacy_source_missing"
        ):
            _block(
                report,
                "unavailable_artifact_checkpoint_mismatch",
                artifactId=artifact.id,
                status=artifact.artifact_status,
                unavailableCode=artifact.unavailable_code,
            )
        if request.mutates:
            await self._checkpoints.set_artifact_unavailable(
                artifact_id=artifact.id,
                code="legacy_source_missing",
                detail=detail[:2000],
            )

    async def _succeeded_object_delivery(
        self,
        *,
        artifact: ArchiveVideoArtifactRecord,
        route: ResolvedPublishRoute,
        binding: ResolvedObjectBinding,
        object_key: str,
        public_url: str,
    ) -> ObjectDeliveryRecord:
        existing = await self._checkpoints.get_object_delivery(
            artifact_id=artifact.id,
            object_binding_id=binding.id,
        )
        if existing is not None and existing.status == "succeeded":
            return existing
        return await self._checkpoints.upsert_object_delivery(
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
                status="succeeded",
            )
        )

    async def _read_legacy_pointer(
        self,
        *,
        request: PublicationMigrationRequest,
        primary: ResolvedObjectBinding,
        source_store: PublicationObjectStorePort,
        staging_store: PublicationObjectStorePort,
        report: dict[str, object],
    ) -> dict[str, object] | None:
        pointer_key = f"{primary.key_prefix.strip('/')}/channels/{request.environment}.json"
        pointer_report = cast(dict[str, object], report["pointer"])
        pointer_report["sourceKey"] = pointer_key
        payload = await _read_legacy_source_object(
            source_store,
            object_key=pointer_key,
            object_kind="pointer",
        )
        if payload is None:
            pointer_report["verified"] = False
            _block(report, "legacy_pointer_missing", objectKey=pointer_key)
            return None
        try:
            value = json.loads(payload)
            if not isinstance(value, dict):
                raise ValueError("Legacy pointer must be a JSON object.")
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            pointer_report["verified"] = False
            _block(report, "legacy_pointer_invalid", detail=str(exc))
            return None
        pointer_report["verified"] = True
        pointer_report["sha256"] = _sha256(payload)
        pointer_report["byteSize"] = len(payload)
        staging_key = _legacy_staging_key("pointers", payload)
        pointer_report["stagingKey"] = staging_key
        if request.mutates:
            await _ensure_immutable_object(
                staging_store,
                object_key=staging_key,
                payload=payload,
            )
            pointer_report["stagingVerified"] = True
        elif request.mode == "verify":
            try:
                await _verify_immutable_object(
                    staging_store,
                    object_key=staging_key,
                    payload=payload,
                )
            except ValueError as exc:
                pointer_report["stagingVerified"] = False
                _block(report, "legacy_pointer_staging_mismatch", detail=str(exc))
            else:
                pointer_report["stagingVerified"] = True
        return cast(dict[str, object], value)

    async def _migrate_index(  # noqa: C901 - history validation is intentionally linear
        self,
        *,
        request: PublicationMigrationRequest,
        route: ResolvedPublishRoute,
        primary: ResolvedObjectBinding,
        index_model: ArchiveIndexPublicationModel,
        current_index_url: str | None,
        source_store: PublicationObjectStorePort,
        staging_store: PublicationObjectStorePort,
        artifact_records: dict[int, ArchiveVideoArtifactRecord],
        ready_payloads: dict[int, bytes],
        object_deliveries: dict[tuple[int, int], ObjectDeliveryRecord],
        report: dict[str, object],
    ) -> _MigratedIndexResult | None:
        index_report = cast(dict[str, object], report["indices"])
        payload = await _read_legacy_source_object(
            source_store,
            object_key=index_model.index_key,
            object_kind="index",
        )
        if payload is None:
            _increment(index_report, "unavailable")
            cast(list[dict[str, object]], index_report["missing"]).append(
                {
                    "indexPublicationId": index_model.id,
                    "objectKey": index_model.index_key,
                    "reason": "legacy_source_missing",
                }
            )
            return None
        actual_sha256 = _sha256(payload)
        if actual_sha256 != index_model.sha256 or len(payload) != index_model.byte_size:
            mismatches = cast(list[dict[str, object]], index_report["mismatches"])
            mismatches.append(
                {
                    "indexPublicationId": index_model.id,
                    "objectKey": index_model.index_key,
                    "expectedSha256": index_model.sha256,
                    "actualSha256": actual_sha256,
                    "expectedBytes": index_model.byte_size,
                    "actualBytes": len(payload),
                }
            )
            return None
        try:
            index_value = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            _block(
                report,
                "legacy_index_invalid_json",
                indexPublicationId=index_model.id,
                detail=str(exc),
            )
            return None
        artifact_ids, missing_urls = _index_membership(
            index_value,
            artifacts_by_url={item.public_url: item.id for item in artifact_records.values()},
        )
        if missing_urls:
            _increment(index_report, "historyWithMissingArtifacts")
        staging_key = _legacy_staging_key("indexes", payload)
        if request.mutates:
            await _ensure_immutable_object(
                staging_store,
                object_key=staging_key,
                payload=payload,
            )
        elif request.mode == "verify":
            try:
                await _verify_immutable_object(
                    staging_store,
                    object_key=staging_key,
                    payload=payload,
                )
            except ValueError as exc:
                _block(
                    report,
                    "legacy_index_staging_mismatch",
                    indexPublicationId=index_model.id,
                    detail=str(exc),
                )
                return None
        _increment(index_report, "preserved")
        if not request.mutates:
            if not missing_urls and all(value in ready_payloads for value in artifact_ids):
                _increment(index_report, "localWouldBuild")
            return _MigratedIndexResult(
                artifact_ids=artifact_ids,
                publication_id=None,
            )

        publication = await self._checkpoints.create_or_get_publication(
            PublicationUpsert(
                profile_revision_id=route.profile_revision_id,
                route_id=route.route_id,
                schema_version=index_model.schema_version,
                version=index_model.version,
                membership_sha256=membership_sha256(artifact_ids),
                identity_key=f"legacy-index:{index_model.id}",
                status=(
                    "ready"
                    if not missing_urls and all(value in ready_payloads for value in artifact_ids)
                    else "unavailable"
                ),
                video_count=index_model.video_count,
                artifact_count=len(artifact_ids),
                legacy_index_publication_id=index_model.id,
                error_code="legacy_artifact_missing" if missing_urls else None,
                error_message=(
                    f"Missing legacy timeline references: {len(missing_urls)}"
                    if missing_urls
                    else None
                ),
            ),
            artifact_ids=artifact_ids,
        )
        is_current = index_model.public_url == current_index_url
        pointer_bytes = None
        pointer_staging_key = None
        pointer_sha256 = None
        pointer_byte_size = None
        if is_current:
            pointer_report = cast(dict[str, object], report["pointer"])
            source_pointer_key = _string(pointer_report.get("sourceKey"))
            if source_pointer_key:
                pointer_bytes = await _read_legacy_source_object(
                    source_store,
                    object_key=source_pointer_key,
                    object_kind="pointer",
                )
                if pointer_bytes is None:
                    _block(
                        report,
                        "legacy_pointer_disappeared",
                        objectKey=source_pointer_key,
                    )
                    return _MigratedIndexResult(
                        artifact_ids=artifact_ids,
                        publication_id=publication.id,
                    )
                pointer_staging_key = _string(pointer_report.get("stagingKey"))
                pointer_sha256 = _sha256(pointer_bytes)
                pointer_byte_size = len(pointer_bytes)
        await self._upsert_publication_delivery_once(
            PublicationDeliveryUpsert(
                publication_id=publication.id,
                object_binding_id=primary.id,
                destination_id=primary.destination_id,
                required=primary.required,
                status="published" if is_current and pointer_bytes else "ready",
                index_staging_key=staging_key,
                index_object_key=index_model.index_key,
                index_public_url=index_model.public_url,
                index_sha256=index_model.sha256,
                index_byte_size=index_model.byte_size,
                index_succeeded_at=index_model.created_at,
                pointer_staging_key=pointer_staging_key,
                pointer_object_key=index_model.pointer_key if pointer_bytes else None,
                pointer_public_url=(
                    source_store.public_url(index_model.pointer_key) if pointer_bytes else None
                ),
                pointer_sha256=pointer_sha256,
                pointer_byte_size=pointer_byte_size,
                pointer_succeeded_at=index_model.created_at if pointer_bytes else None,
            )
        )
        if missing_urls or any(value not in ready_payloads for value in artifact_ids):
            await self._record_local_history_unavailable(
                publication_id=publication.id,
                route=route,
            )
            return _MigratedIndexResult(
                artifact_ids=artifact_ids,
                publication_id=publication.id,
            )
        await self._build_local_index_deliveries(
            request=request,
            route=route,
            primary=primary,
            publication_id=publication.id,
            version=index_model.version,
            generated_at=_iso(index_model.created_at),
            artifact_ids=artifact_ids,
            artifact_records=artifact_records,
            ready_payloads=ready_payloads,
            object_deliveries=object_deliveries,
            staging_store=staging_store,
            publish_pointer=False,
            report=report,
        )
        return _MigratedIndexResult(
            artifact_ids=artifact_ids,
            publication_id=publication.id,
        )

    async def _preserve_manifest_only_history(
        self,
        *,
        request: PublicationMigrationRequest,
        manifest_keys: set[str] | None,
        index_models: list[ArchiveIndexPublicationModel],
        primary: ResolvedObjectBinding,
        source_store: PublicationObjectStorePort,
        staging_store: PublicationObjectStorePort,
        report: dict[str, object],
    ) -> None:
        if manifest_keys is None:
            return
        known_index_keys = {item.index_key for item in index_models}
        known_pointer_keys = {item.pointer_key for item in index_models}
        current_pointer_key = f"{primary.key_prefix.strip('/')}/channels/{request.environment}.json"
        known_pointer_keys.add(current_pointer_key)
        manifest_index_keys = {key for key in manifest_keys if _is_index_key(key)}
        manifest_pointer_keys = {key for key in manifest_keys if _is_pointer_key(key)}
        orphan_index_keys = sorted(manifest_index_keys - known_index_keys)
        orphan_pointer_keys = sorted(manifest_pointer_keys - known_pointer_keys)
        additional_pointer_keys = sorted(manifest_pointer_keys - {current_pointer_key})
        manifest_report = cast(dict[str, object], report["sourceManifest"])
        manifest_report["orphanIndexCount"] = len(orphan_index_keys)
        manifest_report["orphanIndexKeys"] = orphan_index_keys
        manifest_report["orphanPointerCount"] = len(orphan_pointer_keys)
        manifest_report["orphanPointerKeys"] = orphan_pointer_keys

        for object_key in orphan_index_keys:
            preserved = await self._preserve_manifest_object(
                request=request,
                source_store=source_store,
                staging_store=staging_store,
                object_key=object_key,
                staging_kind="indexes",
                report=report,
            )
            if preserved:
                _increment(manifest_report, "orphanIndexesPreserved")
        for object_key in additional_pointer_keys:
            preserved = await self._preserve_manifest_object(
                request=request,
                source_store=source_store,
                staging_store=staging_store,
                object_key=object_key,
                staging_kind="pointers",
                report=report,
            )
            if preserved:
                _increment(manifest_report, "additionalPointersPreserved")

    async def _preserve_manifest_object(
        self,
        *,
        request: PublicationMigrationRequest,
        source_store: PublicationObjectStorePort,
        staging_store: PublicationObjectStorePort,
        object_key: str,
        staging_kind: str,
        report: dict[str, object],
    ) -> bool:
        payload = await _read_legacy_source_object(
            source_store,
            object_key=object_key,
            object_kind=f"manifest {staging_kind.rstrip('s')}",
        )
        if payload is None:
            _block(
                report,
                "manifest_object_missing_at_source",
                objectKey=object_key,
            )
            return False
        staging_key = _legacy_staging_key(staging_kind, payload)
        if request.mutates:
            await _ensure_immutable_object(
                staging_store,
                object_key=staging_key,
                payload=payload,
            )
        elif request.mode == "verify":
            try:
                await _verify_immutable_object(
                    staging_store,
                    object_key=staging_key,
                    payload=payload,
                )
            except ValueError as exc:
                _block(
                    report,
                    "manifest_history_staging_mismatch",
                    objectKey=object_key,
                    detail=str(exc),
                )
                return False
        return True

    async def _record_local_history_unavailable(
        self,
        *,
        publication_id: int,
        route: ResolvedPublishRoute,
    ) -> None:
        primary = _primary_binding(route)
        for binding in route.object_bindings:
            if binding.id == primary.id:
                continue
            await self._upsert_publication_delivery_once(
                PublicationDeliveryUpsert(
                    publication_id=publication_id,
                    object_binding_id=binding.id,
                    destination_id=binding.destination_id,
                    required=binding.required,
                    status="unavailable",
                    error_code="legacy_artifact_missing",
                    error_message="One or more referenced timeline artifacts are unavailable.",
                )
            )

    async def _latest_artifact_ids(
        self,
        *,
        request: PublicationMigrationRequest,
        route: ResolvedPublishRoute,
        ready_ids: set[int],
    ) -> tuple[int, ...]:
        if not ready_ids:
            return ()
        statement = (
            select(
                ArchiveVideoArtifactModel.id,
                ArchiveVideoArtifactModel.video_id,
                ArchiveVideoArtifactModel.variant,
            )
            .join(VideoModel, VideoModel.id == ArchiveVideoArtifactModel.video_id)
            .join(ChannelModel, ChannelModel.id == VideoModel.channel_id)
            .join(StreamerModel, StreamerModel.id == ChannelModel.streamer_id)
            .where(
                ArchiveVideoArtifactModel.id.in_(ready_ids),
                StreamerModel.publish_profile_id == route.profile_id,
                VideoModel.is_embeddable.is_not(False),
            )
            .order_by(
                VideoModel.published_at.desc(),
                VideoModel.id.desc(),
                ArchiveVideoArtifactModel.variant.asc(),
                ArchiveVideoArtifactModel.id.desc(),
            )
        )
        rows = (await self._session.execute(statement)).all()
        selected: list[int] = []
        seen: set[tuple[int, str]] = set()
        for artifact_id, video_id, variant in rows:
            identity = (video_id, variant)
            if identity in seen:
                continue
            seen.add(identity)
            selected.append(artifact_id)
        return tuple(selected[: request.latest_limit])

    async def _publish_latest_local(
        self,
        *,
        request: PublicationMigrationRequest,
        route: ResolvedPublishRoute,
        primary: ResolvedObjectBinding,
        artifact_ids: tuple[int, ...],
        artifact_records: dict[int, ArchiveVideoArtifactRecord],
        ready_payloads: dict[int, bytes],
        object_deliveries: dict[tuple[int, int], ObjectDeliveryRecord],
        staging_store: PublicationObjectStorePort,
        report: dict[str, object],
    ) -> None:
        if not artifact_ids:
            if request.expected_latest_count == 0:
                return
            _block(report, "latest_membership_empty")
            return
        if not request.mutates:
            cast(dict[str, object], report["latest"])["localWouldPublish"] = True
            if request.mode == "verify":
                await self._verify_latest_local_publication(
                    request=request,
                    route=route,
                    primary=primary,
                    artifact_ids=artifact_ids,
                    report=report,
                )
            return
        membership = membership_sha256(artifact_ids)
        version = f"migration-{membership[:16]}"
        publication = await self._checkpoints.create_or_get_publication(
            PublicationUpsert(
                profile_revision_id=route.profile_revision_id,
                route_id=route.route_id,
                schema_version=request.schema_version,
                version=version,
                membership_sha256=membership,
                identity_key=_migration_latest_identity(
                    route=route,
                    schema_version=request.schema_version,
                    membership=membership,
                ),
                status="ready",
                video_count=len({artifact_records[value].video_id for value in artifact_ids}),
                artifact_count=len(artifact_ids),
            ),
            artifact_ids=artifact_ids,
        )
        await self._build_local_index_deliveries(
            request=request,
            route=route,
            primary=primary,
            publication_id=publication.id,
            version=publication.version,
            generated_at=_iso(max(artifact_records[value].created_at for value in artifact_ids)),
            artifact_ids=artifact_ids,
            artifact_records=artifact_records,
            ready_payloads=ready_payloads,
            object_deliveries=object_deliveries,
            staging_store=staging_store,
            publish_pointer=True,
            report=report,
        )
        await self._checkpoints.set_publication_status(
            publication.id,
            status="published",
        )
        cast(dict[str, object], report["latest"])["publicationId"] = publication.id

    async def _verify_latest_local_publication(
        self,
        *,
        request: PublicationMigrationRequest,
        route: ResolvedPublishRoute,
        primary: ResolvedObjectBinding,
        artifact_ids: tuple[int, ...],
        report: dict[str, object],
    ) -> None:
        membership = membership_sha256(artifact_ids)
        publication = await self._session.scalar(
            select(ArchivePublicationModel).where(
                ArchivePublicationModel.route_id == route.route_id,
                ArchivePublicationModel.identity_key
                == _migration_latest_identity(
                    route=route,
                    schema_version=request.schema_version,
                    membership=membership,
                ),
            )
        )
        if publication is None:
            _block(report, "latest_publication_checkpoint_missing")
            return
        deliveries = await self._checkpoints.list_publication_deliveries(publication.id)
        latest_report = cast(dict[str, object], report["latest"])
        latest_report["publicationId"] = publication.id
        for binding in route.object_bindings:
            if binding.id == primary.id:
                continue
            delivery = next(
                (item for item in deliveries if item.object_binding_id == binding.id),
                None,
            )
            if (
                delivery is None
                or delivery.status != "published"
                or not delivery.index_object_key
                or not delivery.pointer_object_key
                or not delivery.index_sha256
                or not delivery.pointer_sha256
            ):
                _block(
                    report,
                    "latest_local_publication_incomplete",
                    bindingId=binding.id,
                )
                continue
            store = self._connections.object_store(binding.connection_ref)
            index_payload = await store.get_bytes(object_key=delivery.index_object_key)
            pointer_payload = await store.get_bytes(object_key=delivery.pointer_object_key)
            if _sha256(index_payload) != delivery.index_sha256:
                _block(
                    report,
                    "latest_local_index_sha256_mismatch",
                    bindingId=binding.id,
                )
                continue
            if _sha256(pointer_payload) != delivery.pointer_sha256:
                _block(
                    report,
                    "latest_local_pointer_sha256_mismatch",
                    bindingId=binding.id,
                )
                continue
            _increment(latest_report, "localPointersVerified")

    async def _verify_history_checkpoints(
        self,
        *,
        route: ResolvedPublishRoute,
        primary: ResolvedObjectBinding,
        index_models: list[ArchiveIndexPublicationModel],
        report: dict[str, object],
    ) -> None:
        verification = await verify_available_historical_local_indexes(
            session=self._session,
            checkpoints=self._checkpoints,
            connections=self._connections,
            route=route,
            primary=primary,
            index_models=index_models,
        )
        indices_report = cast(dict[str, object], report["indices"])
        indices_report["historyCheckpointCount"] = verification.checkpoint_count
        indices_report["localHistoryVerified"] = verification.verified_count
        for issue in verification.issues:
            _block(report, issue.code, **issue.detail)

    async def _build_local_index_deliveries(  # noqa: C901 - preserves crash-resume order
        self,
        *,
        request: PublicationMigrationRequest,
        route: ResolvedPublishRoute,
        primary: ResolvedObjectBinding,
        publication_id: int,
        version: str,
        generated_at: str,
        artifact_ids: tuple[int, ...],
        artifact_records: dict[int, ArchiveVideoArtifactRecord],
        ready_payloads: dict[int, bytes],
        object_deliveries: dict[tuple[int, int], ObjectDeliveryRecord],
        staging_store: PublicationObjectStorePort,
        publish_pointer: bool,
        report: dict[str, object],
    ) -> None:
        for binding in route.object_bindings:
            if binding.id == primary.id:
                continue
            existing = next(
                (
                    item
                    for item in await self._checkpoints.list_publication_deliveries(publication_id)
                    if item.object_binding_id == binding.id
                ),
                None,
            )
            if existing is not None:
                if existing.status == "published" and existing.pointer_succeeded_at:
                    _increment(
                        cast(dict[str, object], report["latest"]),
                        "localPointersVerified",
                    )
                    continue
                if existing.status == "ready" and not publish_pointer:
                    continue
            destination_store = self._connections.object_store(binding.connection_ref)
            if (
                existing is not None
                and existing.status == "ready"
                and publish_pointer
                and existing.index_object_key
                and existing.index_public_url
                and existing.index_sha256
                and existing.index_byte_size is not None
            ):
                pointer_key = f"{binding.key_prefix.strip('/')}/channels/{request.environment}.json"
                pointer_payload = _json_bytes(
                    {
                        "schemaVersion": request.schema_version,
                        "environment": request.environment,
                        "generatedAt": generated_at,
                        "currentIndexUrl": existing.index_public_url,
                        "currentIndexVersion": version,
                        "videoCount": len(
                            {artifact_records[value].video_id for value in artifact_ids}
                        ),
                    }
                )
                pointer_staging_key = _generated_staging_key(
                    publication_id,
                    binding.id,
                    "pointer",
                    pointer_payload,
                )
                await _ensure_immutable_object(
                    staging_store,
                    object_key=pointer_staging_key,
                    payload=pointer_payload,
                )
                await destination_store.put_bytes(
                    object_key=pointer_key,
                    payload=pointer_payload,
                    content_type="application/json",
                    cache_control=_POINTER_CACHE_CONTROL,
                )
                await self._checkpoints.upsert_publication_delivery(
                    PublicationDeliveryUpsert(
                        publication_id=publication_id,
                        object_binding_id=binding.id,
                        destination_id=binding.destination_id,
                        required=binding.required,
                        status="published",
                        index_staging_key=existing.index_staging_key,
                        index_object_key=existing.index_object_key,
                        index_public_url=existing.index_public_url,
                        index_sha256=existing.index_sha256,
                        index_byte_size=existing.index_byte_size,
                        index_succeeded_at=existing.index_succeeded_at,
                        pointer_staging_key=pointer_staging_key,
                        pointer_object_key=pointer_key,
                        pointer_public_url=destination_store.public_url(pointer_key),
                        pointer_sha256=_sha256(pointer_payload),
                        pointer_byte_size=len(pointer_payload),
                        pointer_succeeded_at=_now(),
                    )
                )
                latest_report = cast(dict[str, object], report["latest"])
                _increment(latest_report, "localPointersPublished")
                continue
            timeline_rows = []
            for artifact_id in artifact_ids:
                delivery = object_deliveries.get((artifact_id, binding.id))
                if delivery is None:
                    delivery = await self._checkpoints.get_object_delivery(
                        artifact_id=artifact_id,
                        object_binding_id=binding.id,
                    )
                if delivery is None or delivery.status != "succeeded":
                    raise ValueError(
                        "Object delivery is missing for artifact "
                        f"{artifact_id}, binding {binding.id}."
                    )
                timeline_rows.append(
                    (
                        artifact_records[artifact_id],
                        parse_timeline_payload(ready_payloads[artifact_id]),
                        delivery.public_url,
                    )
                )
            built = build_destination_index(
                artifacts=tuple(timeline_rows),
                key_prefix=binding.key_prefix,
                public_url=destination_store.public_url,
                environment=request.environment,
                schema_version=request.schema_version,
                version=version,
                generated_at=generated_at,
            )
            index_staging_key = _generated_staging_key(
                publication_id,
                binding.id,
                "index",
                built.payload_bytes,
            )
            await _ensure_immutable_object(
                staging_store,
                object_key=index_staging_key,
                payload=built.payload_bytes,
            )
            await _ensure_immutable_object(
                destination_store,
                object_key=built.object_key,
                payload=built.payload_bytes,
            )
            pointer_staging_key = None
            pointer_succeeded_at = None
            pointer_sha256 = None
            pointer_byte_size = None
            pointer_object_key = None
            pointer_public_url = None
            status: Literal["ready", "published"] = "ready"
            if publish_pointer:
                pointer_staging_key = _generated_staging_key(
                    publication_id,
                    binding.id,
                    "pointer",
                    built.pointer_payload_bytes,
                )
                await _ensure_immutable_object(
                    staging_store,
                    object_key=pointer_staging_key,
                    payload=built.pointer_payload_bytes,
                )
                await destination_store.put_bytes(
                    object_key=built.pointer_key,
                    payload=built.pointer_payload_bytes,
                    content_type="application/json",
                    cache_control=_POINTER_CACHE_CONTROL,
                )
                pointer_succeeded_at = _now()
                pointer_sha256 = built.pointer_sha256
                pointer_byte_size = built.pointer_byte_size
                pointer_object_key = built.pointer_key
                pointer_public_url = built.pointer_public_url
                status = "published"
                latest_report = cast(dict[str, object], report["latest"])
                _increment(latest_report, "localPointersPublished")
            await self._upsert_publication_delivery_once(
                PublicationDeliveryUpsert(
                    publication_id=publication_id,
                    object_binding_id=binding.id,
                    destination_id=binding.destination_id,
                    required=binding.required,
                    status=status,
                    index_staging_key=index_staging_key,
                    index_object_key=built.object_key,
                    index_public_url=built.public_url,
                    index_sha256=built.sha256,
                    index_byte_size=built.byte_size,
                    index_succeeded_at=_now(),
                    pointer_staging_key=pointer_staging_key,
                    pointer_object_key=pointer_object_key,
                    pointer_public_url=pointer_public_url,
                    pointer_sha256=pointer_sha256,
                    pointer_byte_size=pointer_byte_size,
                    pointer_succeeded_at=pointer_succeeded_at,
                )
            )
            indices_report = cast(dict[str, object], report["indices"])
            _increment(indices_report, "localBuilt")

    async def _upsert_publication_delivery_once(
        self,
        delivery: PublicationDeliveryUpsert,
    ) -> PublicationDeliveryRecord:
        existing = next(
            (
                item
                for item in await self._checkpoints.list_publication_deliveries(
                    delivery.publication_id
                )
                if item.object_binding_id == delivery.object_binding_id
            ),
            None,
        )
        if existing is not None and existing.status == delivery.status:
            if delivery.status == "published" and existing.pointer_succeeded_at is not None:
                return existing
            if delivery.status == "ready" and existing.index_succeeded_at is not None:
                return existing
            if delivery.status == "unavailable":
                return existing
        return await self._checkpoints.upsert_publication_delivery(delivery)

    async def _replay_catalogs(  # noqa: C901 - remote import and local replay share state
        self,
        *,
        request: PublicationMigrationRequest,
        route: ResolvedPublishRoute,
        primary: ResolvedObjectBinding,
        artifact_ids: tuple[int, ...],
        artifact_records: dict[int, ArchiveVideoArtifactRecord],
        ready_payloads: dict[int, bytes],
        object_deliveries: dict[tuple[int, int], ObjectDeliveryRecord],
        report: dict[str, object],
    ) -> None:
        catalog_report = cast(dict[str, object], report["catalog"])
        for binding in route.catalog_bindings:
            is_legacy_remote = binding.connection_ref == "legacy-remote-catalog"
            binding_artifact_ids = (
                tuple(sorted(ready_payloads)) if is_legacy_remote else artifact_ids
            )
            for artifact_id in binding_artifact_ids:
                artifact = artifact_records[artifact_id]
                source_delivery = object_deliveries.get(
                    (artifact_id, binding.source_object_binding_id)
                )
                if source_delivery is None and request.mutates:
                    source_delivery = await self._checkpoints.get_object_delivery(
                        artifact_id=artifact_id,
                        object_binding_id=binding.source_object_binding_id,
                    )
                if source_delivery is None and not request.mutates:
                    source_binding = next(
                        (
                            item
                            for item in route.object_bindings
                            if item.id == binding.source_object_binding_id
                        ),
                        None,
                    )
                    if source_binding is not None:
                        store = self._connections.object_store(source_binding.connection_ref)
                        object_key = (
                            artifact.object_key
                            if source_binding.id == primary.id
                            else destination_artifact_key(
                                artifact,
                                key_prefix=source_binding.key_prefix,
                            )
                        )
                        source_delivery = ObjectDeliveryRecord(
                            artifact_id=artifact.id,
                            profile_revision_id=route.profile_revision_id,
                            route_id=route.route_id,
                            object_binding_id=source_binding.id,
                            destination_id=source_binding.destination_id,
                            required=source_binding.required,
                            object_key=object_key,
                            public_url=(
                                artifact.public_url
                                if source_binding.id == primary.id
                                else store.public_url(object_key)
                            ),
                            sha256=artifact.sha256,
                            byte_size=artifact.byte_size,
                            status="succeeded",
                        )
                if source_delivery is None:
                    _block(
                        report,
                        "catalog_source_object_delivery_missing",
                        artifactId=artifact_id,
                        catalogBindingId=binding.id,
                    )
                    continue
                if is_legacy_remote:
                    status = (
                        "succeeded"
                        if artifact.public_catalog_synced_at is not None
                        else "unavailable"
                    )
                    if status == "succeeded":
                        _increment(catalog_report, "remoteImported")
                    if request.mode == "verify":
                        existing = await self._checkpoints.get_catalog_delivery(
                            artifact_id=artifact_id,
                            catalog_binding_id=binding.id,
                        )
                        if existing is None or existing.status != status:
                            _block(
                                report,
                                "legacy_catalog_checkpoint_mismatch",
                                artifactId=artifact_id,
                                catalogBindingId=binding.id,
                            )
                        else:
                            _increment(catalog_report, "remoteCheckpointed")
                    if request.mutates:
                        await self._upsert_catalog_delivery_once(
                            CatalogDeliveryUpsert(
                                artifact_id=artifact_id,
                                profile_revision_id=route.profile_revision_id,
                                route_id=route.route_id,
                                catalog_binding_id=binding.id,
                                destination_id=binding.destination_id,
                                source_object_delivery_id=source_delivery.id,
                                required=binding.required,
                                status=status,
                                error_code=(
                                    None if status == "succeeded" else "legacy_state_missing"
                                ),
                                error_message=(
                                    None
                                    if status == "succeeded"
                                    else "Legacy catalog success was not recorded."
                                ),
                            )
                        )
                        _increment(catalog_report, "remoteCheckpointed")
                    elif request.mode == "dry-run":
                        _increment(catalog_report, "remoteWouldCheckpoint")
                    continue
                context = PublicationCatalogContext(
                    profile_key=route.profile_key,
                    publish_mode=request.publish_mode,
                )
                row = catalog_row_from_timeline(
                    artifact=artifact,
                    payload=parse_timeline_payload(ready_payloads[artifact_id]),
                    timeline_url=source_delivery.public_url,
                )
                if request.mode == "dry-run":
                    _increment(catalog_report, "localWouldReplay")
                    continue
                existing = await self._checkpoints.get_catalog_delivery(
                    artifact_id=artifact_id,
                    catalog_binding_id=binding.id,
                )
                verifier = self._connections.catalog_verifier(binding.connection_ref)
                verification = await verifier.verify_video(context, row)
                delivery = CatalogDeliveryUpsert(
                    artifact_id=artifact_id,
                    profile_revision_id=route.profile_revision_id,
                    route_id=route.route_id,
                    catalog_binding_id=binding.id,
                    destination_id=binding.destination_id,
                    source_object_delivery_id=source_delivery.id,
                    required=binding.required,
                    status="succeeded",
                )
                if request.mode == "verify":
                    _record_catalog_verification(catalog_report, verification)
                    if existing is None or existing.status != "succeeded":
                        _block(
                            report,
                            "local_catalog_checkpoint_missing",
                            artifactId=artifact_id,
                            catalogBindingId=binding.id,
                        )
                    if not verification.matches:
                        _block(
                            report,
                            "local_catalog_projection_mismatch",
                            artifactId=artifact_id,
                            catalogBindingId=binding.id,
                            exists=verification.exists,
                            detail=verification.detail,
                        )
                    if (
                        existing is not None
                        and existing.status == "succeeded"
                        and verification.matches
                    ):
                        _increment(catalog_report, "localVerified")
                    continue
                if verification.matches:
                    _record_catalog_verification(catalog_report, verification)
                    await self._upsert_catalog_delivery_once(delivery)
                    _increment(catalog_report, "localReused")
                    continue
                publisher = self._connections.catalog_publisher(binding.connection_ref)
                await publisher.upsert_video(
                    context,
                    row,
                )
                repaired = await verifier.verify_video(context, row)
                _record_catalog_verification(catalog_report, repaired)
                if not repaired.matches:
                    _block(
                        report,
                        "local_catalog_repair_verification_failed",
                        artifactId=artifact_id,
                        catalogBindingId=binding.id,
                        exists=repaired.exists,
                        detail=repaired.detail,
                    )
                    continue
                await self._upsert_catalog_delivery_once(delivery)
                _increment(catalog_report, "localReplayed")

    async def _upsert_catalog_delivery_once(
        self,
        delivery: CatalogDeliveryUpsert,
    ) -> None:
        existing = await self._checkpoints.get_catalog_delivery(
            artifact_id=delivery.artifact_id,
            catalog_binding_id=delivery.catalog_binding_id,
        )
        if existing is not None and existing.status == delivery.status:
            return
        await self._checkpoints.upsert_catalog_delivery(delivery)


# Kept local to the infrastructure migration adapter so legacy CLI strings do not
# leak into the publication domain model.
AnyPublishMode = Literal["prod", "dev"]


def write_publication_migration_report(
    report: dict[str, object],
    *,
    report_dir: Path,
) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    mode = str(report.get("mode", "unknown")).replace("/", "-")
    path = report_dir / f"publication-migration-{stamp}-{mode}.json"
    _atomic_write_json(path, report)
    return path


async def _read_legacy_source_object(
    store: PublicationObjectStorePort,
    *,
    object_key: str,
    object_kind: str,
) -> bytes | None:
    try:
        source_stat = await store.stat_object(object_key=object_key)
    except Exception as exc:
        raise PublicationMigrationSourceError(
            f"Legacy {object_kind} stat failed for '{object_key}': {exc}"
        ) from exc
    if source_stat is None:
        return None
    try:
        payload = await store.get_bytes(object_key=object_key)
    except Exception as exc:
        raise PublicationMigrationSourceError(
            f"Legacy {object_kind} read failed for '{object_key}': {exc}"
        ) from exc
    if len(payload) != source_stat.byte_size:
        raise PublicationMigrationSourceError(
            f"Legacy {object_kind} changed while reading '{object_key}': "
            f"stat={source_stat.byte_size}, read={len(payload)}"
        )
    return payload


async def _ensure_immutable_object(
    store: PublicationObjectStorePort,
    *,
    object_key: str,
    payload: bytes,
) -> bool:
    expected_sha256 = _sha256(payload)
    existing = await store.stat_object(object_key=object_key)
    if existing is not None:
        if existing.byte_size != len(payload):
            raise ValueError(f"Immutable object size mismatch: {object_key}")
        existing_payload = await store.get_bytes(object_key=object_key)
        if _sha256(existing_payload) != expected_sha256:
            raise ValueError(f"Immutable object SHA-256 mismatch: {object_key}")
        return False
    await store.put_bytes(
        object_key=object_key,
        payload=payload,
        content_type="application/json",
        cache_control=_IMMUTABLE_CACHE_CONTROL,
    )
    written = await store.get_bytes(object_key=object_key)
    if len(written) != len(payload) or _sha256(written) != expected_sha256:
        raise ValueError(f"Immutable object verification failed after write: {object_key}")
    return True


async def _verify_immutable_object(
    store: PublicationObjectStorePort,
    *,
    object_key: str,
    payload: bytes,
) -> None:
    existing = await store.stat_object(object_key=object_key)
    if existing is None:
        raise ValueError(f"Immutable object is missing: {object_key}")
    if existing.byte_size != len(payload):
        raise ValueError(f"Immutable object size mismatch: {object_key}")
    existing_payload = await store.get_bytes(object_key=object_key)
    if _sha256(existing_payload) != _sha256(payload):
        raise ValueError(f"Immutable object SHA-256 mismatch: {object_key}")


def _primary_binding(route: ResolvedPublishRoute) -> ResolvedObjectBinding:
    values = [binding for binding in route.object_bindings if binding.is_primary]
    if len(values) != 1:
        raise ValueError("Publication route must have exactly one primary object binding.")
    return values[0]


def _index_membership(
    value: object,
    *,
    artifacts_by_url: dict[str, int],
) -> tuple[tuple[int, ...], tuple[str, ...]]:
    if not isinstance(value, dict) or not isinstance(value.get("videos"), list):
        raise ValueError("Legacy index must contain a videos list.")
    artifact_ids: list[int] = []
    missing_urls: list[str] = []
    for video in value["videos"]:
        if not isinstance(video, dict):
            continue
        variants = video.get("timelineVariants")
        if not isinstance(variants, list):
            continue
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            url = variant.get("url")
            if not isinstance(url, str):
                continue
            artifact_id = artifacts_by_url.get(url)
            if artifact_id is None:
                missing_urls.append(url)
            elif artifact_id not in artifact_ids:
                artifact_ids.append(artifact_id)
    return tuple(artifact_ids), tuple(missing_urls)


def _legacy_staging_key(kind: str, payload: bytes) -> str:
    digest = _sha256(payload)
    return f"legacy/{kind}/sha256/{digest[:2]}/{digest}.json"


def _generated_staging_key(
    publication_id: int,
    binding_id: int,
    kind: str,
    payload: bytes,
) -> str:
    return f"publications/{publication_id}/bindings/{binding_id}/{kind}.{_sha256(payload)}.json"


def _new_report(
    request: PublicationMigrationRequest,
    route: ResolvedPublishRoute,
    artifact_count: int,
) -> dict[str, object]:
    return {
        "version": 1,
        "mode": request.mode,
        "generatedAt": _now().isoformat().replace("+00:00", "Z"),
        "mutated": request.mutates,
        "scope": {
            "profileKey": route.profile_key,
            "profileRevisionId": route.profile_revision_id,
            "routeId": route.route_id,
            "publishMode": request.publish_mode,
            "environment": request.environment,
            "schemaVersion": request.schema_version,
        },
        "artifacts": {
            "total": artifact_count,
            "ready": 0,
            "unavailable": 0,
            "canonicalCopied": 0,
            "canonicalWouldCopy": 0,
            "publicationObjectsCopied": 0,
            "publicationObjectsWouldCopy": 0,
            "mismatches": [],
            "missing": [],
        },
        "indices": {
            "total": 0,
            "preserved": 0,
            "unavailable": 0,
            "localBuilt": 0,
            "localWouldBuild": 0,
            "localHistoryVerified": 0,
            "historyWithMissingArtifacts": 0,
            "mismatches": [],
            "missing": [],
        },
        "pointer": {"verified": False},
        "latest": {
            "limit": request.latest_limit,
            "selected": 0,
            "artifactIds": [],
            "remoteArtifactIds": [],
            "remoteCurrentIndexUrl": None,
            "remoteMembershipMatches": None,
            "localWouldPublish": False,
            "localPointersPublished": 0,
            "localPointersVerified": 0,
        },
        "catalog": {
            "remoteImported": 0,
            "remoteCheckpointed": 0,
            "remoteWouldCheckpoint": 0,
            "localReplayed": 0,
            "localReused": 0,
            "localWouldReplay": 0,
            "localVerified": 0,
            "localRowsFound": 0,
            "localRowsMatched": 0,
        },
        "sourceManifest": {
            "path": str(request.source_manifest) if request.source_manifest else None,
            "required": request.mode in {"apply", "resume", "verify"},
            "objectCount": None,
            "historyIndexCount": None,
            "historyPreservedCount": 0,
            "orphanTimelineCount": None,
            "orphanTimelineKeys": [],
            "orphanIndexCount": 0,
            "orphanIndexKeys": [],
            "orphanIndexesPreserved": 0,
            "orphanPointerCount": 0,
            "orphanPointerKeys": [],
            "additionalPointersPreserved": 0,
            "missingReadyArtifactKeys": [],
            "staleMissingArtifactKeys": [],
            "missingKnownIndexKeys": [],
            "missingKnownPointerKeys": [],
            "complete": None,
        },
        "expectations": {},
        "blockers": [],
        "ok": False,
    }


def _add_manifest_comparison(
    manifest_keys: set[str] | None,
    artifacts: list[ArchiveVideoArtifactModel],
    indices: list[ArchiveIndexPublicationModel],
    *,
    ready_ids: set[int],
    report: dict[str, object],
) -> None:
    index_report = cast(dict[str, object], report["indices"])
    index_report["total"] = len(indices)
    if manifest_keys is None:
        return
    artifact_keys = {item.object_key for item in artifacts}
    ready_artifact_keys = {item.object_key for item in artifacts if item.id in ready_ids}
    missing_artifact_keys = {
        str(item["objectKey"])
        for item in cast(
            list[dict[str, object]],
            cast(dict[str, object], report["artifacts"])["missing"],
        )
    }
    known_index_keys = {item.index_key for item in indices}
    known_pointer_keys = {item.pointer_key for item in indices}
    pointer_source_key = _string(cast(dict[str, object], report["pointer"]).get("sourceKey"))
    if pointer_source_key is not None:
        known_pointer_keys.add(pointer_source_key)
    manifest_index_keys = {key for key in manifest_keys if _is_index_key(key)} | (
        manifest_keys & known_index_keys
    )
    manifest_pointer_keys = {key for key in manifest_keys if _is_pointer_key(key)} | (
        manifest_keys & known_pointer_keys
    )
    known = artifact_keys | known_index_keys | known_pointer_keys
    orphan_timelines = sorted(
        key for key in manifest_keys - known if "/videos/" in key and "/timeline." in key
    )
    missing_ready_artifacts = sorted(ready_artifact_keys - manifest_keys)
    stale_missing_artifacts = sorted(missing_artifact_keys & manifest_keys)
    missing_known_indices = sorted(known_index_keys - manifest_keys)
    missing_known_pointers = sorted(known_pointer_keys - manifest_keys)
    manifest_report = cast(dict[str, object], report["sourceManifest"])
    manifest_report["objectCount"] = len(manifest_keys)
    manifest_report["historyIndexCount"] = len(manifest_index_keys)
    manifest_report["orphanTimelineCount"] = len(orphan_timelines)
    manifest_report["orphanTimelineKeys"] = orphan_timelines
    manifest_report["missingReadyArtifactKeys"] = missing_ready_artifacts
    manifest_report["staleMissingArtifactKeys"] = stale_missing_artifacts
    manifest_report["missingKnownIndexKeys"] = missing_known_indices
    manifest_report["missingKnownPointerKeys"] = missing_known_pointers
    preserved_history = cast(int, index_report["preserved"]) + cast(
        int, manifest_report["orphanIndexesPreserved"]
    )
    manifest_report["historyPreservedCount"] = preserved_history
    pointer_report = cast(dict[str, object], report["pointer"])
    current_pointer_preserved = int(
        (bool(pointer_report.get("verified")) and str(report["mode"]) == "dry-run")
        or bool(pointer_report.get("stagingVerified"))
    )
    preserved_pointers = current_pointer_preserved + cast(
        int, manifest_report["additionalPointersPreserved"]
    )
    manifest_report["pointerPreservedCount"] = preserved_pointers
    manifest_report["complete"] = (
        not missing_ready_artifacts
        and not stale_missing_artifacts
        and not missing_known_pointers
        and preserved_history == len(manifest_index_keys)
        and preserved_pointers == len(manifest_pointer_keys)
    )


def _is_index_key(key: str) -> bool:
    return "/index." in key and key.endswith(".json")


def _is_pointer_key(key: str) -> bool:
    return "/channels/" in key and key.endswith(".json")


def _legacy_artifact_build_key(artifact_id: int, sha256: str) -> str:
    return f"legacy-artifact:{artifact_id}:sha256:{sha256}"


def _manifest_keys(path: Path) -> set[str]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Source object manifest is invalid: {path}") from exc
    entries = value.get("objects") if isinstance(value, dict) else value
    if not isinstance(entries, list):
        raise ValueError("Source object manifest must be a list or contain an objects list.")
    keys: set[str] = set()
    for item in entries:
        if isinstance(item, str):
            keys.add(item)
        elif isinstance(item, dict) and isinstance(item.get("key"), str):
            keys.add(item["key"])
    return keys


def _finish_report(
    request: PublicationMigrationRequest,
    report: dict[str, object],
) -> None:
    artifacts = cast(dict[str, object], report["artifacts"])
    latest = cast(dict[str, object], report["latest"])
    catalog = cast(dict[str, object], report["catalog"])
    manifest = cast(dict[str, object], report["sourceManifest"])
    expectations = cast(dict[str, object], report["expectations"])
    if request.mode == "dry-run":
        catalog_actual = catalog["localWouldReplay"]
        remote_catalog_actual = catalog["remoteWouldCheckpoint"]
    elif request.mode == "verify":
        catalog_actual = catalog["localVerified"]
        remote_catalog_actual = catalog["remoteCheckpointed"]
    else:
        replayed = catalog["localReplayed"]
        reused = catalog["localReused"]
        if not isinstance(replayed, int) or not isinstance(reused, int):
            raise TypeError("Migration catalog counters are invalid.")
        catalog_actual = replayed + reused
        remote_catalog_actual = catalog["remoteCheckpointed"]
    checks = {
        "artifactCount": (request.expected_artifact_count, artifacts["total"]),
        "readyCount": (request.expected_ready_count, artifacts["ready"]),
        "unavailableCount": (
            request.expected_unavailable_count,
            artifacts["unavailable"],
        ),
        "latestCount": (request.expected_latest_count, latest["selected"]),
        "localCatalogCount": (request.expected_latest_count, catalog_actual),
        "remoteCatalogCheckpointCount": (
            request.expected_ready_count,
            remote_catalog_actual,
        ),
        "historyIndexCount": (
            request.expected_history_count,
            manifest["historyIndexCount"],
        ),
        "historyPreservedCount": (
            request.expected_history_count,
            manifest["historyPreservedCount"],
        ),
        "shaMismatchCount": (
            0,
            len(cast(list[object], artifacts["mismatches"]))
            + len(
                cast(
                    list[object],
                    cast(dict[str, object], report["indices"])["mismatches"],
                )
            ),
        ),
    }
    if request.source_manifest is not None or manifest["required"]:
        checks["sourceManifestComplete"] = (True, manifest["complete"])
    all_passed = True
    for name, (expected, actual) in checks.items():
        passed = expected is None or expected == actual
        expectations[name] = {
            "expected": expected,
            "actual": actual,
            "passed": passed,
        }
        all_passed = all_passed and passed
    report["ok"] = all_passed and not cast(list[object], report["blockers"])


def _migration_latest_identity(
    *,
    route: ResolvedPublishRoute,
    schema_version: int,
    membership: str,
) -> str:
    return (
        f"migration-latest:{route.profile_revision_id}:"
        f"{route.route_id}:{schema_version}:{membership}"
    )


def _validate_current_remote_membership(
    *,
    request: PublicationMigrationRequest,
    current_index_url: str | None,
    historical_memberships: dict[str, tuple[int, ...]],
    latest_ids: tuple[int, ...],
    report: dict[str, object],
) -> bool:
    verification = validate_current_remote_membership(
        expected_latest_count=request.expected_latest_count,
        current_index_url=current_index_url,
        historical_memberships=historical_memberships,
        latest_ids=latest_ids,
    )
    latest_report = cast(dict[str, object], report["latest"])
    latest_report["remoteCurrentIndexUrl"] = verification.current_index_url
    latest_report["remoteArtifactIds"] = list(verification.remote_artifact_ids)
    latest_report["remoteMembershipMatches"] = verification.matches
    if verification.issue is not None:
        _block(report, verification.issue.code, **verification.issue.detail)
    return verification.matches


def _block(report: dict[str, object], code: str, **detail: object) -> None:
    blockers = cast(list[dict[str, object]], report["blockers"])
    blockers.append({"code": code, **detail})


def _increment(values: dict[str, object], key: str, amount: int = 1) -> None:
    current = values.get(key)
    if not isinstance(current, int) or isinstance(current, bool):
        raise TypeError(f"Migration report counter is invalid: {key}")
    values[key] = current + amount


def _record_catalog_verification(
    report: dict[str, object],
    verification: PublicationCatalogRowVerification,
) -> None:
    if verification.exists:
        _increment(report, "localRowsFound")
    if verification.matches:
        _increment(report, "localRowsMatched")


def _string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _json_bytes(payload: dict[str, object]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _now() -> datetime:
    return datetime.now(UTC)


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, text=True
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary_path.replace(path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
