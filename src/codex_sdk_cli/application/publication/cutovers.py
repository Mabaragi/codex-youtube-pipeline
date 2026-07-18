from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from codex_sdk_cli.application.publication.cutover_ports import (
    PublicationCutoverAdvance,
    PublicationCutoverCreate,
    PublicationCutoverRecord,
    PublicationCutoverRepositoryPort,
    PublicationCutoverStep,
)
from codex_sdk_cli.application.publication.errors import (
    PublicationCutoverConflict,
    PublicationCutoverNotFound,
    PublicationCutoverStepFailed,
)
from codex_sdk_cli.application.publication.models import (
    PublicationMembershipAuthorization,
    PublicationStageResult,
)
from codex_sdk_cli.application.publication_config.ports import (
    PublishConfigurationRepositoryPort,
    ResolvedPublishRoute,
)
from codex_sdk_cli.domains.operation_events.ports import (
    OperationEventCreate,
    OperationEventRecorderPort,
)
from codex_sdk_cli.domains.operation_events.recording import record_operation_event
from codex_sdk_cli.domains.streamers.ports import StreamerRepositoryPort


@dataclass(frozen=True, slots=True)
class PreparePublicationCutover:
    streamer_id: int
    target_profile_id: int
    publish_mode: str
    environment: str
    schema_version: int
    operator_reason: str


class CutoverArtifact(Protocol):
    @property
    def id(self) -> int: ...


class CutoverArtifactMembership(Protocol):
    @property
    def artifact(self) -> CutoverArtifact: ...


class CutoverMembershipRepositoryPort(Protocol):
    async def list_latest_video_artifacts(
        self,
        *,
        environment: str,
        schema_version: int,
        publish_profile_id: int | None = None,
        streamer_id: int | None = None,
        ready_only: bool = False,
    ) -> Sequence[CutoverArtifactMembership]: ...


class PublicationCutoverStagesPort(Protocol):
    async def active_route(
        self,
        *,
        streamer_id: int,
        publish_mode: str,
        environment: str,
    ) -> ResolvedPublishRoute: ...

    async def revision_route(
        self,
        *,
        profile_revision_id: int,
        publish_mode: str,
        environment: str,
    ) -> ResolvedPublishRoute: ...

    async def deliver_objects(
        self,
        *,
        artifact_ids: tuple[int, ...],
        route: ResolvedPublishRoute,
        destination_ids: tuple[int, ...] | None = None,
        membership_authorization: PublicationMembershipAuthorization | None = None,
    ) -> PublicationStageResult: ...

    async def publish_catalogs(
        self,
        *,
        artifact_ids: tuple[int, ...],
        route: ResolvedPublishRoute,
        destination_ids: tuple[int, ...] | None = None,
        membership_authorization: PublicationMembershipAuthorization | None = None,
        reconcile_scope: bool = False,
    ) -> PublicationStageResult: ...

    async def build_publication(
        self,
        *,
        artifact_ids: tuple[int, ...],
        route: ResolvedPublishRoute,
        schema_version: int,
        destination_ids: tuple[int, ...] | None = None,
        membership_authorization: PublicationMembershipAuthorization | None = None,
        publication_identity_key: str | None = None,
    ) -> PublicationStageResult: ...

    async def publish_pointer(
        self,
        *,
        publication_id: int,
        destination_ids: tuple[int, ...] | None = None,
    ) -> PublicationStageResult: ...


class GetPublicationCutoverUseCase:
    def __init__(self, repository: PublicationCutoverRepositoryPort) -> None:
        self._repository = repository

    async def execute(self, cutover_id: int) -> PublicationCutoverRecord:
        cutover = await self._repository.get(cutover_id)
        if cutover is None:
            raise PublicationCutoverNotFound(cutover_id)
        return cutover


class ListPublicationCutoversUseCase:
    def __init__(self, repository: PublicationCutoverRepositoryPort) -> None:
        self._repository = repository

    async def execute(self, *, limit: int = 100) -> list[PublicationCutoverRecord]:
        return await self._repository.list(limit=limit)


class PublicationCutoverService:
    def __init__(
        self,
        *,
        repository: PublicationCutoverRepositoryPort,
        configuration: PublishConfigurationRepositoryPort,
        archive: CutoverMembershipRepositoryPort,
        streamers: StreamerRepositoryPort,
        stages: PublicationCutoverStagesPort,
        events: OperationEventRecorderPort,
    ) -> None:
        self._repository = repository
        self._configuration = configuration
        self._archive = archive
        self._streamers = streamers
        self._stages = stages
        self._events = events

    async def prepare(
        self,
        command: PreparePublicationCutover,
    ) -> PublicationCutoverRecord:
        streamer = await self._streamers.get_streamer(command.streamer_id)
        if streamer is None:
            raise PublicationCutoverConflict(
                "Streamer does not exist.",
                details={"streamerId": command.streamer_id},
            )
        if streamer.publish_profile_id == command.target_profile_id:
            raise PublicationCutoverConflict(
                "Streamer is already assigned to the target publish profile.",
                details={"streamerId": command.streamer_id},
            )
        open_cutover = await self._repository.find_open(
            streamer_id=command.streamer_id,
            publish_mode=command.publish_mode,
            environment=command.environment,
        )
        if open_cutover is not None:
            self._require_same_request(open_cutover, command)
            await self._event(
                open_cutover,
                "publication.cutover_prepare_requested",
                reason=command.operator_reason,
            )
            return await self._prepare_target(open_cutover)

        source_route = await self._stages.active_route(
            streamer_id=command.streamer_id,
            publish_mode=command.publish_mode,
            environment=command.environment,
        )
        target_profile = await self._configuration.get_profile(command.target_profile_id)
        if target_profile is None or target_profile.profile.active_revision_id is None:
            raise PublicationCutoverConflict(
                "Target publish profile does not have an active revision.",
                details={"targetProfileId": command.target_profile_id},
            )
        target_route = await self._stages.revision_route(
            profile_revision_id=target_profile.profile.active_revision_id,
            publish_mode=command.publish_mode,
            environment=command.environment,
        )
        target_artifact_ids = await self._target_membership(
            streamer_id=command.streamer_id,
            target_profile_id=command.target_profile_id,
            environment=command.environment,
            schema_version=command.schema_version,
        )
        request_key = _request_key(
            command=command,
            source_revision_id=source_route.profile_revision_id,
            target_revision_id=target_route.profile_revision_id,
            artifact_ids=target_artifact_ids,
        )
        cutover = await self._repository.create_or_get(
            PublicationCutoverCreate(
                request_key=request_key,
                streamer_id=command.streamer_id,
                source_profile_id=source_route.profile_id,
                target_profile_id=target_route.profile_id,
                source_profile_revision_id=source_route.profile_revision_id,
                target_profile_revision_id=target_route.profile_revision_id,
                source_route_id=source_route.route_id,
                target_route_id=target_route.route_id,
                publish_mode=command.publish_mode,
                environment=command.environment,
                schema_version=command.schema_version,
                artifact_ids=target_artifact_ids,
                operator_reason=command.operator_reason,
            )
        )
        if cutover.request_key != request_key:
            raise PublicationCutoverConflict(
                "An unfinished cutover already exists for this streamer route.",
                details={"cutoverId": cutover.id},
            )
        await self._event(cutover, "publication.cutover_preparing")
        return await self._prepare_target(cutover)

    async def resume(
        self,
        cutover_id: int,
        *,
        operator_reason: str,
    ) -> PublicationCutoverRecord:
        cutover = await self._required(cutover_id)
        if cutover.status == "completed":
            return cutover
        await self._event(
            cutover,
            "publication.cutover_resume_requested",
            reason=operator_reason,
        )
        if cutover.target_publication_id is None:
            cutover = await self._prepare_target(cutover)
        cutover = await self._publish_target_pointer(cutover)
        cutover = await self._assign_streamer(cutover)
        cutover = await self._rebuild_source(cutover)
        cutover = await self._publish_source_pointer(cutover)
        await self._event(
            cutover,
            "publication.cutover_completed",
            reason=operator_reason,
        )
        return cutover

    async def get(self, cutover_id: int) -> PublicationCutoverRecord:
        return await self._required(cutover_id)

    async def list(self, *, limit: int = 100) -> list[PublicationCutoverRecord]:
        return await self._repository.list(limit=limit)

    async def _prepare_target(
        self,
        cutover: PublicationCutoverRecord,
    ) -> PublicationCutoverRecord:
        if cutover.target_publication_id is not None:
            return cutover
        try:
            route = await self._snapshotted_route(cutover, target=True)
            authorization = _target_membership_authorization(cutover)
            self._ensure_stage(
                cutover,
                "target_prepare",
                await self._stages.deliver_objects(
                    artifact_ids=cutover.artifact_ids,
                    route=route,
                    membership_authorization=authorization,
                ),
            )
            self._ensure_stage(
                cutover,
                "target_prepare",
                await self._stages.publish_catalogs(
                    artifact_ids=cutover.artifact_ids,
                    route=route,
                    membership_authorization=authorization,
                ),
            )
            result = await self._stages.build_publication(
                artifact_ids=cutover.artifact_ids,
                route=route,
                schema_version=cutover.schema_version,
                membership_authorization=authorization,
                publication_identity_key=f"cutover:{cutover.id}:target",
            )
            self._ensure_stage(cutover, "target_prepare", result)
            if result.publication_id is None:
                raise PublicationCutoverStepFailed(
                    cutover_id=cutover.id,
                    step="target_prepare",
                    message="Target publication build returned no publication ID.",
                )
            prepared = await self._repository.advance(
                cutover.id,
                PublicationCutoverAdvance(
                    status="prepared",
                    last_completed_step="target_prepare",
                    target_publication_id=result.publication_id,
                ),
            )
            await self._event(prepared, "publication.cutover_prepared")
            return prepared
        except Exception as exc:  # noqa: BLE001
            await self._record_failure(cutover, "target_prepare", exc)
            raise

    async def _publish_target_pointer(
        self,
        cutover: PublicationCutoverRecord,
    ) -> PublicationCutoverRecord:
        if cutover.target_pointer_published_at is not None:
            return cutover
        if cutover.target_publication_id is None:
            raise PublicationCutoverConflict("Target publication has not been prepared.")
        try:
            result = await self._stages.publish_pointer(
                publication_id=cutover.target_publication_id
            )
            self._ensure_stage(cutover, "target_pointer", result)
            advanced = await self._repository.advance(
                cutover.id,
                PublicationCutoverAdvance(
                    status="target_pointer_published",
                    last_completed_step="target_pointer",
                    target_pointer_published_at=datetime.now(UTC),
                ),
            )
            await self._event(advanced, "publication.cutover_target_pointer_published")
            return advanced
        except Exception as exc:  # noqa: BLE001
            await self._record_failure(cutover, "target_pointer", exc)
            raise

    async def _assign_streamer(
        self,
        cutover: PublicationCutoverRecord,
    ) -> PublicationCutoverRecord:
        if cutover.streamer_assigned_at is not None:
            return cutover
        try:
            streamer = await self._streamers.get_streamer(cutover.streamer_id)
            if streamer is None:
                raise PublicationCutoverConflict("Streamer no longer exists.")
            if streamer.publish_profile_id == cutover.source_profile_id:
                updated = await self._streamers.update_streamer(
                    cutover.streamer_id,
                    publish_profile_id=cutover.target_profile_id,
                )
                if updated is None:
                    raise PublicationCutoverConflict("Streamer no longer exists.")
            elif streamer.publish_profile_id != cutover.target_profile_id:
                raise PublicationCutoverConflict(
                    "Streamer profile changed outside this cutover.",
                    details={
                        "currentProfileId": streamer.publish_profile_id,
                        "sourceProfileId": cutover.source_profile_id,
                        "targetProfileId": cutover.target_profile_id,
                    },
                )
            advanced = await self._repository.advance(
                cutover.id,
                PublicationCutoverAdvance(
                    status="streamer_assigned",
                    last_completed_step="streamer_assignment",
                    streamer_assigned_at=datetime.now(UTC),
                ),
            )
            await self._event(advanced, "publication.cutover_streamer_assigned")
            return advanced
        except Exception as exc:  # noqa: BLE001
            await self._record_failure(cutover, "streamer_assignment", exc)
            raise

    async def _rebuild_source(
        self,
        cutover: PublicationCutoverRecord,
    ) -> PublicationCutoverRecord:
        if cutover.source_publication_id is not None:
            return cutover
        try:
            route = await self._snapshotted_route(cutover, target=False)
            artifacts = await self._archive.list_latest_video_artifacts(
                environment=cutover.environment,
                schema_version=cutover.schema_version,
                publish_profile_id=cutover.source_profile_id,
                ready_only=True,
            )
            artifact_ids = tuple(sorted({item.artifact.id for item in artifacts}))
            self._ensure_stage(
                cutover,
                "source_rebuild",
                await self._stages.deliver_objects(artifact_ids=artifact_ids, route=route),
            )
            self._ensure_stage(
                cutover,
                "source_rebuild",
                await self._stages.publish_catalogs(
                    artifact_ids=artifact_ids,
                    route=route,
                    reconcile_scope=True,
                ),
            )
            result = await self._stages.build_publication(
                artifact_ids=artifact_ids,
                route=route,
                schema_version=cutover.schema_version,
                publication_identity_key=f"cutover:{cutover.id}:source",
            )
            self._ensure_stage(cutover, "source_rebuild", result)
            if result.publication_id is None:
                raise PublicationCutoverStepFailed(
                    cutover_id=cutover.id,
                    step="source_rebuild",
                    message="Source publication rebuild returned no publication ID.",
                )
            advanced = await self._repository.advance(
                cutover.id,
                PublicationCutoverAdvance(
                    status="source_ready",
                    last_completed_step="source_rebuild",
                    source_publication_id=result.publication_id,
                ),
            )
            await self._event(advanced, "publication.cutover_source_ready")
            return advanced
        except Exception as exc:  # noqa: BLE001
            await self._record_failure(cutover, "source_rebuild", exc)
            raise

    async def _publish_source_pointer(
        self,
        cutover: PublicationCutoverRecord,
    ) -> PublicationCutoverRecord:
        if cutover.source_pointer_published_at is not None:
            return cutover
        if cutover.source_publication_id is None:
            raise PublicationCutoverConflict("Source publication has not been rebuilt.")
        try:
            result = await self._stages.publish_pointer(
                publication_id=cutover.source_publication_id
            )
            self._ensure_stage(cutover, "source_pointer", result)
            return await self._repository.advance(
                cutover.id,
                PublicationCutoverAdvance(
                    status="completed",
                    last_completed_step="source_pointer",
                    source_pointer_published_at=datetime.now(UTC),
                ),
            )
        except Exception as exc:  # noqa: BLE001
            await self._record_failure(cutover, "source_pointer", exc)
            raise

    async def _target_membership(
        self,
        *,
        streamer_id: int,
        target_profile_id: int,
        environment: str,
        schema_version: int,
    ) -> tuple[int, ...]:
        target = await self._archive.list_latest_video_artifacts(
            environment=environment,
            schema_version=schema_version,
            publish_profile_id=target_profile_id,
            ready_only=True,
        )
        moving = await self._archive.list_latest_video_artifacts(
            environment=environment,
            schema_version=schema_version,
            streamer_id=streamer_id,
            ready_only=True,
        )
        return tuple(sorted({item.artifact.id for item in (*target, *moving)}))

    async def _snapshotted_route(
        self,
        cutover: PublicationCutoverRecord,
        *,
        target: bool,
    ) -> ResolvedPublishRoute:
        revision_id = (
            cutover.target_profile_revision_id if target else cutover.source_profile_revision_id
        )
        expected_route_id = cutover.target_route_id if target else cutover.source_route_id
        route = await self._stages.revision_route(
            profile_revision_id=revision_id,
            publish_mode=cutover.publish_mode,
            environment=cutover.environment,
        )
        if route.route_id != expected_route_id:
            raise PublicationCutoverConflict(
                "Snapshotted cutover route no longer resolves to the expected route.",
                details={
                    "expectedRouteId": expected_route_id,
                    "resolvedRouteId": route.route_id,
                },
            )
        return route

    async def _required(self, cutover_id: int) -> PublicationCutoverRecord:
        cutover = await self._repository.get(cutover_id)
        if cutover is None:
            raise PublicationCutoverNotFound(cutover_id)
        return cutover

    async def _record_failure(
        self,
        cutover: PublicationCutoverRecord,
        step: PublicationCutoverStep,
        exc: Exception,
    ) -> None:
        failed = await self._repository.mark_failed(
            cutover.id,
            step=step,
            error_code=exc.__class__.__name__,
            error_message=str(exc) or exc.__class__.__name__,
        )
        await self._event(failed, "publication.cutover_failed")

    async def _event(
        self,
        cutover: PublicationCutoverRecord,
        event_type: str,
        *,
        reason: str | None = None,
    ) -> None:
        await record_operation_event(
            self._events,
            OperationEventCreate(
                event_type=event_type,
                severity="warning" if cutover.status == "failed" else "info",
                message=f"Publication cutover {cutover.id} is {cutover.status}.",
                actor_type="manual_api",
                source="ops_api",
                subject_type="publish_profile_cutover",
                subject_id=cutover.id,
                metadata_json={
                    "cutoverId": cutover.id,
                    "streamerId": cutover.streamer_id,
                    "sourceProfileId": cutover.source_profile_id,
                    "targetProfileId": cutover.target_profile_id,
                    "status": cutover.status,
                    "reason": reason or cutover.operator_reason,
                    "lastCompletedStep": cutover.last_completed_step,
                    "lastErrorStep": cutover.last_error_step,
                },
            ),
        )

    @staticmethod
    def _ensure_stage(
        cutover: PublicationCutoverRecord,
        step: PublicationCutoverStep,
        result: PublicationStageResult,
    ) -> None:
        if result.status != "failed":
            return
        failures = [
            {
                "destinationId": item.destination_id,
                "bindingId": item.binding_id,
                "errorCode": item.error_code,
                "errorMessage": item.error_message,
            }
            for item in result.destination_results
            if item.required and item.status not in {"succeeded", "ready", "published"}
        ]
        raise PublicationCutoverStepFailed(
            cutover_id=cutover.id,
            step=step,
            message=f"Publication cutover stage {result.stage} failed.",
            details={"stage": result.stage, "destinations": failures},
        )

    @staticmethod
    def _require_same_request(
        cutover: PublicationCutoverRecord,
        command: PreparePublicationCutover,
    ) -> None:
        if (
            cutover.target_profile_id != command.target_profile_id
            or cutover.schema_version != command.schema_version
        ):
            raise PublicationCutoverConflict(
                "An unfinished cutover already exists for this streamer route.",
                details={
                    "cutoverId": cutover.id,
                    "targetProfileId": cutover.target_profile_id,
                },
            )


def _request_key(
    *,
    command: PreparePublicationCutover,
    source_revision_id: int,
    target_revision_id: int,
    artifact_ids: tuple[int, ...],
) -> str:
    parts = (
        str(command.streamer_id),
        str(source_revision_id),
        str(target_revision_id),
        command.publish_mode,
        command.environment,
        str(command.schema_version),
        ",".join(str(value) for value in artifact_ids),
    )
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


def _target_membership_authorization(
    cutover: PublicationCutoverRecord,
) -> PublicationMembershipAuthorization:
    return PublicationMembershipAuthorization(
        purpose="cutover_target",
        cutover_id=cutover.id,
        streamer_id=cutover.streamer_id,
        source_profile_id=cutover.source_profile_id,
        target_profile_id=cutover.target_profile_id,
        artifact_ids=cutover.artifact_ids,
    )
