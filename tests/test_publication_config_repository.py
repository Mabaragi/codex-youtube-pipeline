from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from codex_sdk_cli.application.publication_config.ports import (
    CreateCatalogDestination,
    CreateObjectDestination,
    CreatePublishProfile,
    CreatePublishProfileRevision,
    CreatePublishProfileRoute,
    CreateRouteCatalogBinding,
    CreateRouteObjectBinding,
)
from codex_sdk_cli.application.publication_config.use_cases import (
    CreatePublishProfileRevisionUseCase,
)
from codex_sdk_cli.domains.publication_config.exceptions import PublishConfigurationConflict
from codex_sdk_cli.infra.database.session import create_database_engine, create_session_factory
from codex_sdk_cli.infra.publication_config.repository import (
    PublishProfileModel,
    PublishProfileRevisionModel,
    SqlAlchemyPublishConfigurationRepository,
)
from codex_sdk_cli.infra.streamers.repository import SqlAlchemyStreamerRepository


def test_publication_configuration_revisions_and_immutable_route_resolution(
    migrated_database_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{migrated_database_path.as_posix()}"
    asyncio.run(_exercise_publication_configuration(database_url))


def test_database_rejects_multiple_active_revisions_for_one_profile(
    migrated_database_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{migrated_database_path.as_posix()}"
    asyncio.run(_exercise_single_active_revision_constraint(database_url))


def test_seeded_dev_route_uses_dev_object_destination(
    migrated_database_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{migrated_database_path.as_posix()}"
    asyncio.run(_exercise_seeded_dev_route(database_url))


async def _exercise_publication_configuration(database_url: str) -> None:
    engine = create_database_engine(database_url)
    try:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            repository = SqlAlchemyPublishConfigurationRepository(session)
            streamers = SqlAlchemyStreamerRepository(session)

            object_destination = await repository.create_object_destination(
                CreateObjectDestination(
                    key="test-object",
                    name="Test Object",
                    connection_ref="test-object-connection",
                )
            )
            catalog_destination = await repository.create_catalog_destination(
                CreateCatalogDestination(
                    key="test-catalog",
                    name="Test Catalog",
                    connection_ref="test-catalog-connection",
                )
            )
            profile = await repository.create_profile(
                CreatePublishProfile(
                    key="test-profile",
                    name="Test Profile",
                    description="A profile used for repository coverage.",
                )
            )
            first_revision = await repository.create_revision(
                _revision_create(
                    profile_id=profile.id,
                    object_destination_id=object_destination.id,
                    catalog_destination_id=catalog_destination.id,
                    key_prefix="archive-v1",
                )
            )
            assert first_revision is not None
            assert first_revision.state == "draft"

            active_first_revision = await repository.activate_revision(
                profile_id=profile.id,
                revision_id=first_revision.id,
            )
            assert active_first_revision is not None
            assert active_first_revision.state == "active"

            streamer = await streamers.create_streamer(
                name="Configured Streamer",
                publish_profile_id=profile.id,
            )
            assert await streamers.is_publish_profile_active(profile.id) is True
            active_route = await repository.resolve_active_route(
                streamer_id=streamer.id,
                publish_mode="prod",
                environment="production",
            )
            assert active_route is not None
            assert active_route.profile_revision_id == first_revision.id
            assert active_route.object_bindings[0].key_prefix == "archive-v1"

            second_revision = await repository.create_revision(
                _revision_create(
                    profile_id=profile.id,
                    object_destination_id=object_destination.id,
                    catalog_destination_id=catalog_destination.id,
                    key_prefix="archive-v2",
                )
            )
            assert second_revision is not None
            assert (
                await repository.activate_revision(
                    profile_id=profile.id,
                    revision_id=second_revision.id,
                )
                is not None
            )

            snapshotted_route = await repository.resolve_revision_route(
                profile_revision_id=first_revision.id,
                publish_mode="prod",
                environment="production",
            )
            assert snapshotted_route is not None
            assert snapshotted_route.object_bindings[0].key_prefix == "archive-v1"

            route_by_id = await repository.get_route(snapshotted_route.route_id)
            assert route_by_id == snapshotted_route

            current_route = await repository.resolve_active_route(
                streamer_id=streamer.id,
                publish_mode="prod",
                environment="production",
            )
            assert current_route is not None
            assert current_route.profile_revision_id == second_revision.id
            assert current_route.object_bindings[0].key_prefix == "archive-v2"
            detail = await repository.get_profile(profile.id)
            assert detail is not None
            assert [revision.id for revision in detail.revisions if revision.state == "active"] == [
                second_revision.id
            ]

            with pytest.raises(PublishConfigurationConflict, match="exactly one primary"):
                await CreatePublishProfileRevisionUseCase(repository).execute(
                    CreatePublishProfileRevision(
                        profile_id=profile.id,
                        routes=(
                            CreatePublishProfileRoute(
                                publish_mode="dev",
                                environment="development",
                                object_bindings=(
                                    CreateRouteObjectBinding(
                                        destination_id=object_destination.id,
                                        key_prefix="invalid",
                                        required=True,
                                        is_primary=False,
                                    ),
                                ),
                                catalog_bindings=(),
                            ),
                        ),
                    )
                )
    finally:
        await engine.dispose()


async def _exercise_seeded_dev_route(database_url: str) -> None:
    engine = create_database_engine(database_url)
    try:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            route = await SqlAlchemyPublishConfigurationRepository(session).resolve_revision_route(
                profile_revision_id=1,
                publish_mode="dev",
                environment="dev",
            )
            assert route is not None
            assert route.object_bindings[0].connection_ref == "legacy-dev-remote-object"
            assert route.object_bindings[0].is_primary is True
    finally:
        await engine.dispose()


async def _exercise_single_active_revision_constraint(database_url: str) -> None:
    engine = create_database_engine(database_url)
    try:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            profile = PublishProfileModel(
                key="single-active-guard",
                name="Single Active Guard",
            )
            session.add(profile)
            await session.flush()
            session.add_all(
                (
                    PublishProfileRevisionModel(
                        profile_id=profile.id,
                        revision_number=1,
                        state="active",
                    ),
                    PublishProfileRevisionModel(
                        profile_id=profile.id,
                        revision_number=2,
                        state="active",
                    ),
                )
            )
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()
    finally:
        await engine.dispose()


def _revision_create(
    *,
    profile_id: int,
    object_destination_id: int,
    catalog_destination_id: int,
    key_prefix: str,
) -> CreatePublishProfileRevision:
    return CreatePublishProfileRevision(
        profile_id=profile_id,
        routes=(
            CreatePublishProfileRoute(
                publish_mode="prod",
                environment="production",
                object_bindings=(
                    CreateRouteObjectBinding(
                        destination_id=object_destination_id,
                        key_prefix=key_prefix,
                        required=True,
                        is_primary=True,
                    ),
                ),
                catalog_bindings=(
                    CreateRouteCatalogBinding(
                        destination_id=catalog_destination_id,
                        source_object_destination_id=object_destination_id,
                        required=True,
                    ),
                ),
            ),
        ),
    )
