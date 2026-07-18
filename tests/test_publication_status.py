from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from httpx import ASGITransport, AsyncClient

from codex_sdk_cli.api.main import create_app
from codex_sdk_cli.api.use_case_dependencies.publication import (
    get_publication_status_repository,
)
from codex_sdk_cli.application.publication.status import (
    PublicationDeliveryStatus,
    PublicationStatus,
    PublicationStatusList,
    PublicationStatusQuery,
)
from codex_sdk_cli.infra.archive_publish.checkpoints import (
    ArchivePublicationArtifactModel,
    ArchivePublicationDeliveryModel,
    ArchivePublicationModel,
)
from codex_sdk_cli.infra.archive_publish.repository import ArchiveVideoArtifactModel
from codex_sdk_cli.infra.channels.repository import ChannelModel
from codex_sdk_cli.infra.database.session import (
    create_database_engine,
    create_session_factory,
)
from codex_sdk_cli.infra.publication.status_repository import (
    SqlAlchemyPublicationStatusRepository,
)
from codex_sdk_cli.infra.publication_config.repository import (
    PublishObjectDestinationModel,
    PublishProfileModel,
    PublishProfileRevisionModel,
    PublishProfileRouteModel,
    PublishRouteObjectBindingModel,
)
from codex_sdk_cli.infra.streamers.repository import StreamerModel
from codex_sdk_cli.infra.videos.repository import VideoModel

NOW = datetime(2026, 7, 18, 6, 0, tzinfo=UTC)


class FakePublicationStatusRepository:
    def __init__(self) -> None:
        self.query: PublicationStatusQuery | None = None

    async def list_publications(
        self,
        query: PublicationStatusQuery,
    ) -> PublicationStatusList:
        self.query = query
        return PublicationStatusList(
            items=(
                PublicationStatus(
                    id=41,
                    profile_id=7,
                    profile_key="creator-a",
                    profile_name="Creator A",
                    profile_revision_id=9,
                    route_id=11,
                    publish_mode="prod",
                    environment="local",
                    schema_version=1,
                    version="20260718T060000Z",
                    status="partially_published",
                    video_count=180,
                    artifact_count=180,
                    error_code=None,
                    error_message=None,
                    created_at=NOW,
                    updated_at=NOW,
                    deliveries=(
                        PublicationDeliveryStatus(
                            id=51,
                            object_binding_id=13,
                            destination_id=17,
                            destination_key="local-public",
                            destination_name="Local public",
                            required=True,
                            status="failed",
                            index_public_url="http://localhost/index.json",
                            pointer_public_url=None,
                            error_code="pointer_failed",
                            error_message="pointer write failed",
                            updated_at=NOW,
                        ),
                    ),
                ),
            ),
            total=1,
            limit=query.limit,
            offset=query.offset,
        )


def test_publication_status_api_preserves_filters_and_destination_errors() -> None:
    repository = FakePublicationStatusRepository()

    response = asyncio.run(_request_status(repository))

    assert response["total"] == 1
    assert response["items"][0]["profileKey"] == "creator-a"
    delivery = response["items"][0]["deliveries"][0]
    assert delivery["destinationKey"] == "local-public"
    assert delivery["errorCode"] == "pointer_failed"
    assert repository.query == PublicationStatusQuery(
        streamer_id=3,
        profile_id=7,
        publish_mode="prod",
        environment="local",
        status="partially_published",
        limit=25,
        offset=5,
    )


def test_publication_status_repository_filters_and_loads_deliveries(
    migrated_database_path: Path,
) -> None:
    result, empty = asyncio.run(_exercise_repository(migrated_database_path))

    assert result.total == 1
    assert result.items[0].profile_key == "status-profile"
    assert result.items[0].deliveries[0].destination_key == "status-object"
    assert result.items[0].deliveries[0].error_code == "pointer_failed"
    assert empty.total == 0


async def _request_status(repository: FakePublicationStatusRepository) -> dict[str, Any]:
    app = create_app()
    app.dependency_overrides[get_publication_status_repository] = lambda: repository
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            "/ops/publish/publications",
            params={
                "streamerId": 3,
                "profileId": 7,
                "publishMode": "prod",
                "environment": "local",
                "status": "partially_published",
                "limit": 25,
                "offset": 5,
            },
        )
    assert response.status_code == 200, response.text
    return response.json()


async def _exercise_repository(
    database_path: Path,
) -> tuple[PublicationStatusList, PublicationStatusList]:
    database_url = f"sqlite+aiosqlite:///{database_path.as_posix()}"
    engine = create_database_engine(database_url)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            profile = PublishProfileModel(
                key="status-profile",
                name="Status profile",
                description=None,
            )
            session.add(profile)
            await session.flush()
            revision = PublishProfileRevisionModel(
                profile_id=profile.id,
                revision_number=1,
                state="active",
                activated_at=NOW,
            )
            session.add(revision)
            await session.flush()
            profile.active_revision_id = revision.id
            route = PublishProfileRouteModel(
                profile_revision_id=revision.id,
                publish_mode="prod",
                environment="local",
            )
            destination = PublishObjectDestinationModel(
                key="status-object",
                name="Status object",
                connection_ref="local-public-object",
            )
            streamer = StreamerModel(name="Status streamer", publish_profile_id=profile.id)
            unrelated_streamer = StreamerModel(
                name="Unrelated streamer",
                publish_profile_id=profile.id,
            )
            session.add_all((route, destination, streamer, unrelated_streamer))
            await session.flush()
            channel = ChannelModel(
                streamer_id=streamer.id,
                handle="@status",
                name="Status channel",
            )
            session.add(channel)
            await session.flush()
            video = VideoModel(
                channel_id=channel.id,
                youtube_video_id="status-video",
                title="Status video",
                description="",
                published_at=NOW,
                is_embeddable=True,
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
                environment="local",
                variant="control",
                schema_version=1,
                version="artifact-v1",
                object_key="archive/videos/status.json",
                public_url="http://localhost/archive/videos/status.json",
                sha256="b" * 64,
                byte_size=2,
                block_count=0,
                episode_count=0,
                topic_cluster_count=0,
                review_flag_count=0,
                micro_event_count=0,
            )
            session.add(artifact)
            await session.flush()
            binding = PublishRouteObjectBindingModel(
                route_id=route.id,
                destination_id=destination.id,
                key_prefix="archive",
                required=True,
                is_primary=True,
            )
            session.add(binding)
            await session.flush()
            publication = ArchivePublicationModel(
                profile_revision_id=revision.id,
                route_id=route.id,
                schema_version=1,
                version="20260718T060000Z",
                membership_sha256="a" * 64,
                identity_key="status-publication:1",
                status="partially_published",
                video_count=180,
                artifact_count=180,
            )
            session.add(publication)
            await session.flush()
            session.add(
                ArchivePublicationArtifactModel(
                    publication_id=publication.id,
                    artifact_id=artifact.id,
                    position=1,
                )
            )
            session.add(
                ArchivePublicationDeliveryModel(
                    publication_id=publication.id,
                    route_id=route.id,
                    object_binding_id=binding.id,
                    destination_id=destination.id,
                    required=True,
                    status="failed",
                    index_public_url="http://localhost/archive/index.json",
                    error_code="pointer_failed",
                    error_message="pointer write failed",
                )
            )
            await session.commit()

            repository = SqlAlchemyPublicationStatusRepository(session)
            result = await repository.list_publications(
                PublicationStatusQuery(
                    streamer_id=streamer.id,
                    profile_id=profile.id,
                    publish_mode="prod",
                    environment="local",
                    status="partially_published",
                )
            )
            empty = await repository.list_publications(
                PublicationStatusQuery(streamer_id=unrelated_streamer.id)
            )
            return result, empty
    finally:
        await engine.dispose()
