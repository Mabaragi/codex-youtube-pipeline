from __future__ import annotations

import asyncio
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from codex_sdk_cli.api.main import app
from codex_sdk_cli.application.publication.cutover_ports import (
    PublicationCutoverAdvance,
    PublicationCutoverCreate,
    PublicationCutoverRecord,
    PublicationCutoverRepositoryPort,
    PublicationCutoverStep,
)
from codex_sdk_cli.application.publication.cutovers import (
    PreparePublicationCutover,
    PublicationCutoverService,
)
from codex_sdk_cli.application.publication.errors import PublicationCutoverStepFailed
from codex_sdk_cli.application.publication.models import (
    PublicationMembershipAuthorization,
    PublicationStageResult,
)
from codex_sdk_cli.application.publication_config.ports import ResolvedPublishRoute
from codex_sdk_cli.domains.archive_publish.ports import (
    ArchiveVideoArtifactWithVideoRecord,
)
from codex_sdk_cli.domains.operation_events.ports import OperationEventCreate
from codex_sdk_cli.domains.publication_config.models import (
    PublishProfile,
    PublishProfileDetail,
)
from codex_sdk_cli.domains.streamers.exceptions import (
    StreamerPublishProfileCutoverRequired,
)
from codex_sdk_cli.domains.streamers.ports import StreamerRecord
from codex_sdk_cli.domains.streamers.schemas import StreamerUpdateRequest
from codex_sdk_cli.domains.streamers.use_cases import UpdateStreamerUseCase
from codex_sdk_cli.infra.database.session import create_database_engine, create_session_factory
from codex_sdk_cli.infra.publication.cutovers import (
    SqlAlchemyPublicationCutoverRepository,
)
from codex_sdk_cli.infra.streamers.repository import SqlAlchemyStreamerRepository

NOW = datetime(2026, 7, 18, tzinfo=UTC)


def test_cutover_openapi_exposes_prepare_resume_and_required_reason() -> None:
    paths = app.openapi()["paths"]
    prepare = paths["/ops/publish/cutovers"]["post"]
    resume = paths["/ops/publish/cutovers/{cutoverId}/resume"]["post"]

    assert any(
        parameter["name"] == "X-Operator-Reason" and parameter["required"] is True
        for parameter in prepare["parameters"]
    )
    assert any(
        parameter["name"] == "X-Operator-Reason" and parameter["required"] is True
        for parameter in resume["parameters"]
    )


def test_cutover_resume_persists_partial_failure_and_resumes_only_source_pointer() -> None:
    asyncio.run(_exercise_resume_order())


async def _exercise_resume_order() -> None:
    log: list[str] = []
    repository = FakeCutoverRepository()
    streamers = FakeStreamers(log)
    stages = FakeStages(log)
    service = PublicationCutoverService(
        repository=repository,
        configuration=FakeConfiguration(),  # type: ignore[arg-type]
        archive=FakeArchive(),  # type: ignore[arg-type]
        streamers=streamers,  # type: ignore[arg-type]
        stages=stages,
        events=FakeEvents(),  # type: ignore[arg-type]
    )

    prepared = await service.prepare(
        PreparePublicationCutover(
            streamer_id=7,
            target_profile_id=2,
            publish_mode="prod",
            environment="prod",
            schema_version=1,
            operator_reason="move channel to isolated publication route",
        )
    )
    assert prepared.status == "prepared"
    assert prepared.artifact_ids == (11, 21)
    assert log == ["target:objects", "target:catalog", "target:index"]
    assert (
        stages.target_authorizations
        == [
            PublicationMembershipAuthorization(
                purpose="cutover_target",
                cutover_id=prepared.id,
                streamer_id=7,
                source_profile_id=1,
                target_profile_id=2,
                artifact_ids=(11, 21),
            )
        ]
        * 3
    )
    assert stages.publication_identities == ["cutover:1:target"]

    with pytest.raises(PublicationCutoverStepFailed):
        await service.resume(prepared.id, operator_reason="perform cutover")

    failed = await service.get(prepared.id)
    assert failed.status == "failed"
    assert failed.last_error_step == "source_pointer"
    assert failed.target_pointer_published_at is not None
    assert failed.streamer_assigned_at is not None
    assert failed.source_publication_id == 202
    assert streamers.streamers[7].publish_profile_id == 2
    assert log == [
        "target:objects",
        "target:catalog",
        "target:index",
        "target:pointer",
        "streamer:assign",
        "source:objects",
        "source:catalog",
        "source:index",
        "source:pointer:failed",
    ]

    completed = await service.resume(prepared.id, operator_reason="resume source pointer")
    assert completed.status == "completed"
    assert completed.source_pointer_published_at is not None
    assert log[-1] == "source:pointer"
    assert log.count("target:pointer") == 1
    assert log.count("streamer:assign") == 1
    assert log.count("source:index") == 1
    assert stages.publication_identities == [
        "cutover:1:target",
        "cutover:1:source",
    ]
    assert stages.reconciled_profiles == ["source"]


def test_direct_profile_change_is_blocked_for_published_streamer() -> None:
    async def exercise() -> None:
        streamers = FakeStreamers([])
        streamers.has_artifacts = True
        with pytest.raises(StreamerPublishProfileCutoverRequired):
            await UpdateStreamerUseCase(streamers).execute(  # type: ignore[arg-type]
                7,
                StreamerUpdateRequest(publishProfileId=2),
            )

    asyncio.run(exercise())


def test_cutover_repository_round_trip_on_migrated_sqlite(
    migrated_database_path: Path,
) -> None:
    asyncio.run(_exercise_repository(migrated_database_path))


async def _exercise_repository(database_path: Path) -> None:
    engine = create_database_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")
    try:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            streamer = await SqlAlchemyStreamerRepository(session).create_streamer(
                name="Cutover Repository Test",
                publish_profile_id=1,
            )
            repository = SqlAlchemyPublicationCutoverRepository(session)
            record = await repository.create_or_get(
                PublicationCutoverCreate(
                    request_key="a" * 64,
                    streamer_id=streamer.id,
                    source_profile_id=1,
                    target_profile_id=1,
                    source_profile_revision_id=1,
                    target_profile_revision_id=1,
                    source_route_id=1,
                    target_route_id=1,
                    publish_mode="prod",
                    environment="prod",
                    schema_version=1,
                    artifact_ids=(4, 9),
                    operator_reason="repository round trip",
                )
            )
            prepared = await repository.advance(
                record.id,
                PublicationCutoverAdvance(
                    status="prepared",
                    last_completed_step="target_prepare",
                ),
            )
            assert prepared.artifact_ids == (4, 9)
            assert (await repository.get(record.id)) == prepared
            assert (
                await repository.create_or_get(
                    replace(
                        PublicationCutoverCreate(
                            request_key="a" * 64,
                            streamer_id=streamer.id,
                            source_profile_id=1,
                            target_profile_id=1,
                            source_profile_revision_id=1,
                            target_profile_revision_id=1,
                            source_route_id=1,
                            target_route_id=1,
                            publish_mode="prod",
                            environment="prod",
                            schema_version=1,
                            artifact_ids=(4, 9),
                            operator_reason="repository round trip",
                        )
                    )
                )
                == prepared
            )
    finally:
        await engine.dispose()


class FakeCutoverRepository(PublicationCutoverRepositoryPort):
    def __init__(self) -> None:
        self.record: PublicationCutoverRecord | None = None

    async def create_or_get(
        self,
        create: PublicationCutoverCreate,
    ) -> PublicationCutoverRecord:
        if self.record is not None:
            return self.record
        self.record = PublicationCutoverRecord(
            **asdict(create),
            id=1,
            status="preparing",
            last_completed_step=None,
            target_publication_id=None,
            source_publication_id=None,
            target_pointer_published_at=None,
            streamer_assigned_at=None,
            source_pointer_published_at=None,
            last_error_step=None,
            last_error_code=None,
            last_error_message=None,
            created_at=NOW,
            updated_at=NOW,
        )
        return self.record

    async def get(self, cutover_id: int) -> PublicationCutoverRecord | None:
        return self.record if self.record is not None and self.record.id == cutover_id else None

    async def list(self, *, limit: int = 100) -> list[PublicationCutoverRecord]:
        return [self.record] if self.record is not None and limit else []

    async def find_open(
        self,
        *,
        streamer_id: int,
        publish_mode: str,
        environment: str,
    ) -> PublicationCutoverRecord | None:
        if (
            self.record is not None
            and self.record.status != "completed"
            and self.record.streamer_id == streamer_id
            and self.record.publish_mode == publish_mode
            and self.record.environment == environment
        ):
            return self.record
        return None

    async def advance(
        self,
        cutover_id: int,
        advance: PublicationCutoverAdvance,
    ) -> PublicationCutoverRecord:
        assert self.record is not None and self.record.id == cutover_id
        values: dict[str, object] = {"status": advance.status, "updated_at": NOW}
        for name in (
            "last_completed_step",
            "target_publication_id",
            "source_publication_id",
            "target_pointer_published_at",
            "streamer_assigned_at",
            "source_pointer_published_at",
        ):
            value = getattr(advance, name)
            if value is not None:
                values[name] = value
        if advance.clear_error:
            values.update(
                last_error_step=None,
                last_error_code=None,
                last_error_message=None,
            )
        self.record = replace(self.record, **values)  # type: ignore[arg-type]
        return self.record

    async def mark_failed(
        self,
        cutover_id: int,
        *,
        step: PublicationCutoverStep,
        error_code: str,
        error_message: str,
    ) -> PublicationCutoverRecord:
        assert self.record is not None and self.record.id == cutover_id
        self.record = replace(
            self.record,
            status="failed",
            last_error_step=step,
            last_error_code=error_code,
            last_error_message=error_message,
        )
        return self.record


class FakeStreamers:
    def __init__(self, log: list[str]) -> None:
        self.log = log
        self.has_artifacts = False
        self.streamers = {7: StreamerRecord(id=7, name="Streamer", publish_profile_id=1)}

    async def get_streamer(self, streamer_id: int) -> StreamerRecord | None:
        return self.streamers.get(streamer_id)

    async def update_streamer(
        self,
        streamer_id: int,
        *,
        name: str | None = None,
        publish_profile_id: int | None = None,
    ) -> StreamerRecord | None:
        current = self.streamers.get(streamer_id)
        if current is None:
            return None
        self.log.append("streamer:assign")
        updated = replace(
            current,
            name=name if name is not None else current.name,
            publish_profile_id=(
                publish_profile_id if publish_profile_id is not None else current.publish_profile_id
            ),
        )
        self.streamers[streamer_id] = updated
        return updated

    async def is_publish_profile_active(self, publish_profile_id: int) -> bool:
        return publish_profile_id in {1, 2}

    async def has_archive_artifacts(self, streamer_id: int) -> bool:
        return streamer_id in self.streamers and self.has_artifacts


class FakeConfiguration:
    async def get_profile(self, profile_id: int) -> PublishProfileDetail | None:
        if profile_id != 2:
            return None
        return PublishProfileDetail(
            profile=PublishProfile(
                id=2,
                key="target",
                name="Target",
                description=None,
                active_revision_id=22,
                created_at=NOW,
            ),
            revisions=(),
        )


class FakeArchive:
    async def list_latest_video_artifacts(
        self,
        *,
        environment: str,
        schema_version: int,
        publish_profile_id: int | None = None,
        streamer_id: int | None = None,
        ready_only: bool = False,
    ) -> list[ArchiveVideoArtifactWithVideoRecord]:
        del environment, schema_version, ready_only
        ids = [11] if streamer_id is not None else [21] if publish_profile_id == 2 else [31]
        return cast(
            list[ArchiveVideoArtifactWithVideoRecord],
            [SimpleNamespace(artifact=SimpleNamespace(id=value)) for value in ids],
        )


class FakeStages:
    def __init__(self, log: list[str]) -> None:
        self.log = log
        self.fail_source_pointer_once = True
        self.target_authorizations: list[PublicationMembershipAuthorization] = []
        self.publication_identities: list[str] = []
        self.reconciled_profiles: list[str] = []
        self.source = _route(profile_id=1, revision_id=11, route_id=111, key="source")
        self.target = _route(profile_id=2, revision_id=22, route_id=222, key="target")

    async def active_route(self, **_: object) -> ResolvedPublishRoute:
        return self.source

    async def revision_route(
        self,
        *,
        profile_revision_id: int,
        publish_mode: str,
        environment: str,
    ) -> ResolvedPublishRoute:
        del publish_mode, environment
        return self.target if profile_revision_id == 22 else self.source

    async def deliver_objects(
        self,
        *,
        artifact_ids: tuple[int, ...],
        route: ResolvedPublishRoute,
        destination_ids: tuple[int, ...] | None = None,
        membership_authorization: PublicationMembershipAuthorization | None = None,
    ) -> PublicationStageResult:
        del destination_ids
        if membership_authorization is not None:
            self.target_authorizations.append(membership_authorization)
        self.log.append(f"{route.profile_key}:objects")
        return _result("objectDeliver", route, artifact_ids)

    async def publish_catalogs(
        self,
        *,
        artifact_ids: tuple[int, ...],
        route: ResolvedPublishRoute,
        destination_ids: tuple[int, ...] | None = None,
        membership_authorization: PublicationMembershipAuthorization | None = None,
        reconcile_scope: bool = False,
    ) -> PublicationStageResult:
        del destination_ids
        if membership_authorization is not None:
            self.target_authorizations.append(membership_authorization)
        if reconcile_scope:
            self.reconciled_profiles.append(route.profile_key)
        self.log.append(f"{route.profile_key}:catalog")
        return _result("catalogPublish", route, artifact_ids)

    async def build_publication(
        self,
        *,
        artifact_ids: tuple[int, ...],
        route: ResolvedPublishRoute,
        schema_version: int,
        destination_ids: tuple[int, ...] | None = None,
        membership_authorization: PublicationMembershipAuthorization | None = None,
        publication_identity_key: str | None = None,
    ) -> PublicationStageResult:
        del schema_version, destination_ids
        if membership_authorization is not None:
            self.target_authorizations.append(membership_authorization)
        assert publication_identity_key is not None
        self.publication_identities.append(publication_identity_key)
        self.log.append(f"{route.profile_key}:index")
        return _result(
            "publicationBuild",
            route,
            artifact_ids,
            publication_id=101 if route.profile_id == 2 else 202,
        )

    async def publish_pointer(
        self,
        *,
        publication_id: int,
        destination_ids: tuple[int, ...] | None = None,
    ) -> PublicationStageResult:
        del destination_ids
        if publication_id == 202 and self.fail_source_pointer_once:
            self.fail_source_pointer_once = False
            self.log.append("source:pointer:failed")
            return PublicationStageResult(stage="pointerPublish", status="failed")
        label = "target" if publication_id == 101 else "source"
        self.log.append(f"{label}:pointer")
        route = self.target if publication_id == 101 else self.source
        return _result("pointerPublish", route, (), publication_id=publication_id)


class FakeEvents:
    def __init__(self) -> None:
        self.items: list[OperationEventCreate] = []

    async def record_event(self, event: OperationEventCreate) -> None:
        self.items.append(event)


def _route(
    *,
    profile_id: int,
    revision_id: int,
    route_id: int,
    key: str,
) -> ResolvedPublishRoute:
    return ResolvedPublishRoute(
        profile_id=profile_id,
        profile_key=key,
        profile_revision_id=revision_id,
        revision_number=1,
        route_id=route_id,
        publish_mode="prod",
        environment="prod",
        object_bindings=(),
        catalog_bindings=(),
    )


def _result(
    stage: str,
    route: ResolvedPublishRoute,
    artifact_ids: tuple[int, ...],
    *,
    publication_id: int | None = None,
) -> PublicationStageResult:
    return PublicationStageResult(
        stage=stage,  # type: ignore[arg-type]
        status="succeeded",
        artifact_ids=artifact_ids,
        profile_revision_id=route.profile_revision_id,
        route_id=route.route_id,
        publication_id=publication_id,
    )
