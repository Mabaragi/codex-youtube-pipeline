from __future__ import annotations

from collections import defaultdict

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from typing_extensions import override

from codex_sdk_cli.application.publication.status import (
    PublicationDeliveryStatus,
    PublicationStatus,
    PublicationStatusList,
    PublicationStatusQuery,
    PublicationStatusRepositoryPort,
)
from codex_sdk_cli.infra.archive_publish.checkpoints import (
    ArchivePublicationArtifactModel,
    ArchivePublicationDeliveryModel,
    ArchivePublicationModel,
)
from codex_sdk_cli.infra.archive_publish.repository import ArchiveVideoArtifactModel
from codex_sdk_cli.infra.channels.repository import ChannelModel
from codex_sdk_cli.infra.publication_config.repository import (
    PublishObjectDestinationModel,
    PublishProfileModel,
    PublishProfileRevisionModel,
    PublishProfileRouteModel,
)
from codex_sdk_cli.infra.videos.repository import VideoModel


class SqlAlchemyPublicationStatusRepository(PublicationStatusRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def list_publications(
        self,
        query: PublicationStatusQuery,
    ) -> PublicationStatusList:
        statement = self._statement(query)
        total = await self._session.scalar(
            select(func.count()).select_from(statement.order_by(None).subquery())
        )
        rows = (
            await self._session.execute(
                statement.order_by(
                    ArchivePublicationModel.created_at.desc(),
                    ArchivePublicationModel.id.desc(),
                )
                .limit(query.limit)
                .offset(query.offset)
            )
        ).all()
        publication_ids = tuple(row[0].id for row in rows)
        deliveries = await self._deliveries(publication_ids)
        items = tuple(
            PublicationStatus(
                id=publication.id,
                profile_id=profile.id,
                profile_key=profile.key,
                profile_name=profile.name,
                profile_revision_id=publication.profile_revision_id,
                route_id=publication.route_id,
                publish_mode=route.publish_mode,
                environment=route.environment,
                schema_version=publication.schema_version,
                version=publication.version,
                status=publication.status,
                video_count=publication.video_count,
                artifact_count=publication.artifact_count,
                error_code=publication.error_code,
                error_message=publication.error_message,
                created_at=publication.created_at,
                updated_at=publication.updated_at,
                deliveries=tuple(deliveries[publication.id]),
            )
            for publication, profile, route in rows
        )
        return PublicationStatusList(
            items=items,
            total=total or 0,
            limit=query.limit,
            offset=query.offset,
        )

    def _statement(
        self,
        query: PublicationStatusQuery,
    ) -> Select[
        ArchivePublicationModel,
        PublishProfileModel,
        PublishProfileRouteModel,
    ]:
        statement = (
            select(
                ArchivePublicationModel,
                PublishProfileModel,
                PublishProfileRouteModel,
            )
            .join(
                PublishProfileRevisionModel,
                PublishProfileRevisionModel.id == ArchivePublicationModel.profile_revision_id,
            )
            .join(
                PublishProfileModel,
                PublishProfileModel.id == PublishProfileRevisionModel.profile_id,
            )
            .join(
                PublishProfileRouteModel,
                PublishProfileRouteModel.id == ArchivePublicationModel.route_id,
            )
        )
        if query.streamer_id is not None:
            membership = (
                select(1)
                .select_from(ArchivePublicationArtifactModel)
                .join(
                    ArchiveVideoArtifactModel,
                    ArchiveVideoArtifactModel.id == ArchivePublicationArtifactModel.artifact_id,
                )
                .join(VideoModel, VideoModel.id == ArchiveVideoArtifactModel.video_id)
                .join(ChannelModel, ChannelModel.id == VideoModel.channel_id)
                .where(
                    ArchivePublicationArtifactModel.publication_id == ArchivePublicationModel.id,
                    ChannelModel.streamer_id == query.streamer_id,
                )
                .exists()
            )
            statement = statement.where(membership)
        if query.profile_id is not None:
            statement = statement.where(PublishProfileModel.id == query.profile_id)
        if query.publish_mode is not None:
            statement = statement.where(PublishProfileRouteModel.publish_mode == query.publish_mode)
        if query.environment is not None:
            statement = statement.where(PublishProfileRouteModel.environment == query.environment)
        if query.status is not None:
            statement = statement.where(ArchivePublicationModel.status == query.status)
        return statement

    async def _deliveries(
        self,
        publication_ids: tuple[int, ...],
    ) -> dict[int, list[PublicationDeliveryStatus]]:
        grouped: dict[int, list[PublicationDeliveryStatus]] = defaultdict(list)
        if not publication_ids:
            return grouped
        rows = (
            await self._session.execute(
                select(
                    ArchivePublicationDeliveryModel,
                    PublishObjectDestinationModel,
                )
                .join(
                    PublishObjectDestinationModel,
                    PublishObjectDestinationModel.id
                    == ArchivePublicationDeliveryModel.destination_id,
                )
                .where(ArchivePublicationDeliveryModel.publication_id.in_(publication_ids))
                .order_by(
                    ArchivePublicationDeliveryModel.publication_id,
                    ArchivePublicationDeliveryModel.required.desc(),
                    ArchivePublicationDeliveryModel.id,
                )
            )
        ).all()
        for delivery, destination in rows:
            grouped[delivery.publication_id].append(
                PublicationDeliveryStatus(
                    id=delivery.id,
                    object_binding_id=delivery.object_binding_id,
                    destination_id=delivery.destination_id,
                    destination_key=destination.key,
                    destination_name=destination.name,
                    required=delivery.required,
                    status=delivery.status,
                    index_public_url=delivery.index_public_url,
                    pointer_public_url=delivery.pointer_public_url,
                    error_code=delivery.error_code,
                    error_message=delivery.error_message,
                    updated_at=delivery.updated_at,
                )
            )
        return grouped
