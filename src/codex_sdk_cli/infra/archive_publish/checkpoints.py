from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    select,
    text,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from typing_extensions import override

from codex_sdk_cli.domains.archive_publish.checkpoints import (
    ArchivePublicationCheckpointPort,
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
from codex_sdk_cli.infra.channels.repository import ChannelModel
from codex_sdk_cli.infra.database.base import Base
from codex_sdk_cli.infra.publication_config.repository import (
    PublishProfileRouteModel,
    PublishRouteCatalogBindingModel,
    PublishRouteObjectBindingModel,
)
from codex_sdk_cli.infra.streamers.repository import StreamerModel
from codex_sdk_cli.infra.videos.repository import VideoModel

from .repository import ArchiveVideoArtifactModel, _artifact_record

_LOCAL_POINTER_LOCKS: dict[tuple[int, int], asyncio.Lock] = {}


class ArchiveArtifactObjectDeliveryModel(Base):
    __tablename__ = "archive_artifact_object_deliveries"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','running','succeeded','failed','unavailable')",
            name="archive_object_delivery_status_allowed",
        ),
        UniqueConstraint(
            "artifact_id", "object_binding_id", name="uq_archive_object_delivery_binding"
        ),
        UniqueConstraint("id", "artifact_id", name="uq_archive_object_delivery_artifact"),
        UniqueConstraint(
            "id",
            "artifact_id",
            "profile_revision_id",
            "route_id",
            "object_binding_id",
            name="uq_archive_object_delivery_source_scope",
        ),
        ForeignKeyConstraint(
            ["route_id", "profile_revision_id"],
            ["publish_profile_routes.id", "publish_profile_routes.profile_revision_id"],
            ondelete="RESTRICT",
            name="fk_archive_object_delivery_route_revision",
        ),
        ForeignKeyConstraint(
            ["object_binding_id", "route_id", "destination_id", "required"],
            [
                "publish_route_object_bindings.id",
                "publish_route_object_bindings.route_id",
                "publish_route_object_bindings.destination_id",
                "publish_route_object_bindings.required",
            ],
            ondelete="RESTRICT",
            name="fk_archive_object_delivery_binding_scope",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    artifact_id: Mapped[int] = mapped_column(
        ForeignKey("archive_video_artifacts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    profile_revision_id: Mapped[int] = mapped_column(
        ForeignKey("publish_profile_revisions.id", ondelete="RESTRICT"), nullable=False
    )
    route_id: Mapped[int] = mapped_column(
        ForeignKey("publish_profile_routes.id", ondelete="RESTRICT"), nullable=False
    )
    object_binding_id: Mapped[int] = mapped_column(
        ForeignKey("publish_route_object_bindings.id", ondelete="RESTRICT"), nullable=False
    )
    destination_id: Mapped[int] = mapped_column(
        ForeignKey("publish_object_destinations.id", ondelete="RESTRICT"), nullable=False
    )
    required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    public_url: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_work_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_items.id", ondelete="SET NULL"), nullable=True
    )
    last_work_attempt_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_attempts.id", ondelete="SET NULL"), nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    succeeded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ArchiveArtifactCatalogDeliveryModel(Base):
    __tablename__ = "archive_artifact_catalog_deliveries"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','running','succeeded','failed','unavailable')",
            name="archive_catalog_delivery_status_allowed",
        ),
        UniqueConstraint(
            "artifact_id", "catalog_binding_id", name="uq_archive_catalog_delivery_binding"
        ),
        ForeignKeyConstraint(
            ["route_id", "profile_revision_id"],
            ["publish_profile_routes.id", "publish_profile_routes.profile_revision_id"],
            ondelete="RESTRICT",
            name="fk_archive_catalog_delivery_route_revision",
        ),
        ForeignKeyConstraint(
            [
                "catalog_binding_id",
                "route_id",
                "destination_id",
                "source_object_binding_id",
                "required",
            ],
            [
                "publish_route_catalog_bindings.id",
                "publish_route_catalog_bindings.route_id",
                "publish_route_catalog_bindings.destination_id",
                "publish_route_catalog_bindings.source_object_binding_id",
                "publish_route_catalog_bindings.required",
            ],
            ondelete="RESTRICT",
            name="fk_archive_catalog_delivery_binding_scope",
        ),
        ForeignKeyConstraint(
            [
                "source_object_delivery_id",
                "artifact_id",
                "profile_revision_id",
                "route_id",
                "source_object_binding_id",
            ],
            [
                "archive_artifact_object_deliveries.id",
                "archive_artifact_object_deliveries.artifact_id",
                "archive_artifact_object_deliveries.profile_revision_id",
                "archive_artifact_object_deliveries.route_id",
                "archive_artifact_object_deliveries.object_binding_id",
            ],
            ondelete="RESTRICT",
            name="fk_archive_catalog_delivery_source_scope",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    artifact_id: Mapped[int] = mapped_column(
        ForeignKey("archive_video_artifacts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    profile_revision_id: Mapped[int] = mapped_column(
        ForeignKey("publish_profile_revisions.id", ondelete="RESTRICT"), nullable=False
    )
    route_id: Mapped[int] = mapped_column(
        ForeignKey("publish_profile_routes.id", ondelete="RESTRICT"), nullable=False
    )
    catalog_binding_id: Mapped[int] = mapped_column(
        ForeignKey("publish_route_catalog_bindings.id", ondelete="RESTRICT"), nullable=False
    )
    destination_id: Mapped[int] = mapped_column(
        ForeignKey("publish_catalog_destinations.id", ondelete="RESTRICT"), nullable=False
    )
    source_object_delivery_id: Mapped[int] = mapped_column(Integer, nullable=False)
    source_object_binding_id: Mapped[int] = mapped_column(Integer, nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_work_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_items.id", ondelete="SET NULL"), nullable=True
    )
    last_work_attempt_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_attempts.id", ondelete="SET NULL"), nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    receipt_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    succeeded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ArchivePublicationModel(Base):
    __tablename__ = "archive_publications"
    __table_args__ = (
        CheckConstraint(
            "status IN ('building','ready','partially_published',"
            "'published','failed','unavailable')",
            name="archive_publication_status_allowed",
        ),
        UniqueConstraint("route_id", "identity_key", name="uq_archive_publication_identity"),
        UniqueConstraint(
            "route_id",
            "legacy_index_publication_id",
            name="uq_archive_publication_legacy_index",
        ),
        UniqueConstraint("id", "route_id", name="uq_archive_publication_id_route"),
        ForeignKeyConstraint(
            ["route_id", "profile_revision_id"],
            ["publish_profile_routes.id", "publish_profile_routes.profile_revision_id"],
            ondelete="RESTRICT",
            name="fk_archive_publication_route_revision",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_revision_id: Mapped[int] = mapped_column(
        ForeignKey("publish_profile_revisions.id", ondelete="RESTRICT"), nullable=False
    )
    route_id: Mapped[int] = mapped_column(
        ForeignKey("publish_profile_routes.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    membership_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    identity_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    video_count: Mapped[int] = mapped_column(Integer, nullable=False)
    artifact_count: Mapped[int] = mapped_column(Integer, nullable=False)
    work_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_items.id", ondelete="SET NULL"), nullable=True
    )
    work_attempt_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_attempts.id", ondelete="SET NULL"), nullable=True
    )
    legacy_index_publication_id: Mapped[int | None] = mapped_column(
        ForeignKey("archive_index_publications.id", ondelete="SET NULL"), nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ArchivePublicationArtifactModel(Base):
    __tablename__ = "archive_publication_artifacts"
    __table_args__ = (
        UniqueConstraint("publication_id", "position", name="uq_archive_publication_position"),
    )

    publication_id: Mapped[int] = mapped_column(
        ForeignKey("archive_publications.id", ondelete="CASCADE"), primary_key=True
    )
    artifact_id: Mapped[int] = mapped_column(
        ForeignKey("archive_video_artifacts.id", ondelete="RESTRICT"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class ArchivePublicationDeliveryModel(Base):
    __tablename__ = "archive_publication_deliveries"
    __table_args__ = (
        CheckConstraint(
            "status IN ('building','ready','partially_published',"
            "'published','failed','unavailable')",
            name="archive_publication_delivery_status_allowed",
        ),
        CheckConstraint(
            "pointer_succeeded_at IS NULL OR index_succeeded_at IS NOT NULL",
            name="archive_publication_pointer_after_index",
        ),
        UniqueConstraint(
            "publication_id", "object_binding_id", name="uq_archive_publication_delivery_binding"
        ),
        ForeignKeyConstraint(
            ["publication_id", "route_id"],
            ["archive_publications.id", "archive_publications.route_id"],
            ondelete="CASCADE",
            name="fk_archive_publication_delivery_publication_route",
        ),
        ForeignKeyConstraint(
            ["object_binding_id", "route_id", "destination_id", "required"],
            [
                "publish_route_object_bindings.id",
                "publish_route_object_bindings.route_id",
                "publish_route_object_bindings.destination_id",
                "publish_route_object_bindings.required",
            ],
            ondelete="RESTRICT",
            name="fk_archive_publication_delivery_binding_scope",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    publication_id: Mapped[int] = mapped_column(
        ForeignKey("archive_publications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    route_id: Mapped[int] = mapped_column(Integer, nullable=False)
    object_binding_id: Mapped[int] = mapped_column(
        ForeignKey("publish_route_object_bindings.id", ondelete="RESTRICT"), nullable=False
    )
    destination_id: Mapped[int] = mapped_column(
        ForeignKey("publish_object_destinations.id", ondelete="RESTRICT"), nullable=False
    )
    required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    index_staging_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    index_object_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    index_public_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    index_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    index_byte_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    index_succeeded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    pointer_staging_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    pointer_object_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    pointer_public_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    pointer_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pointer_byte_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    pointer_succeeded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_work_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_items.id", ondelete="SET NULL"), nullable=True
    )
    last_work_attempt_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_attempts.id", ondelete="SET NULL"), nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class SqlAlchemyArchivePublicationCheckpointRepository(ArchivePublicationCheckpointPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def get_artifacts(
        self, artifact_ids: tuple[int, ...]
    ) -> list[ArchiveVideoArtifactRecord]:
        if not artifact_ids:
            return []
        models = list(
            (
                await self._session.scalars(
                    select(ArchiveVideoArtifactModel).where(
                        ArchiveVideoArtifactModel.id.in_(artifact_ids)
                    )
                )
            ).all()
        )
        by_id = {model.id: model for model in models}
        return [_artifact_record(by_id[item]) for item in artifact_ids if item in by_id]

    @override
    async def get_artifact_publish_profile_assignments(
        self,
        artifact_ids: tuple[int, ...],
    ) -> tuple[ArtifactPublishProfileAssignment, ...]:
        if not artifact_ids:
            return ()
        rows = await self._session.execute(
            select(
                ArchiveVideoArtifactModel.id,
                StreamerModel.id,
                StreamerModel.publish_profile_id,
            )
            .join(VideoModel, VideoModel.id == ArchiveVideoArtifactModel.video_id)
            .join(ChannelModel, ChannelModel.id == VideoModel.channel_id)
            .join(StreamerModel, StreamerModel.id == ChannelModel.streamer_id)
            .where(ArchiveVideoArtifactModel.id.in_(artifact_ids))
        )
        by_artifact_id = {
            artifact_id: ArtifactPublishProfileAssignment(
                artifact_id=artifact_id,
                streamer_id=streamer_id,
                publish_profile_id=publish_profile_id,
            )
            for artifact_id, streamer_id, publish_profile_id in rows
        }
        return tuple(
            by_artifact_id[artifact_id]
            for artifact_id in artifact_ids
            if artifact_id in by_artifact_id
        )

    @override
    async def set_artifact_canonical(
        self,
        *,
        artifact_id: int,
        build_key: str,
        store_ref: str,
        artifact_key: str,
    ) -> None:
        model = await self._required_artifact(artifact_id)
        model.build_key = build_key
        model.artifact_status = "ready"
        model.artifact_store_ref = store_ref
        model.artifact_key = artifact_key
        model.unavailable_code = None
        model.unavailable_detail = None
        await self._session.commit()

    @override
    async def set_artifact_unavailable(
        self,
        *,
        artifact_id: int,
        code: str,
        detail: str,
    ) -> None:
        model = await self._required_artifact(artifact_id)
        model.artifact_status = "unavailable"
        model.artifact_store_ref = None
        model.artifact_key = None
        model.unavailable_code = code
        model.unavailable_detail = detail
        await self._session.commit()

    @override
    async def set_artifact_failed(
        self,
        *,
        artifact_id: int,
        code: str,
        detail: str,
    ) -> None:
        model = await self._required_artifact(artifact_id)
        model.artifact_status = "failed"
        model.artifact_store_ref = None
        model.artifact_key = None
        model.unavailable_code = code
        model.unavailable_detail = detail
        await self._session.commit()

    @override
    async def get_object_delivery(
        self, *, artifact_id: int, object_binding_id: int
    ) -> ObjectDeliveryRecord | None:
        model = await self._session.scalar(
            select(ArchiveArtifactObjectDeliveryModel).where(
                ArchiveArtifactObjectDeliveryModel.artifact_id == artifact_id,
                ArchiveArtifactObjectDeliveryModel.object_binding_id == object_binding_id,
            )
        )
        return _object_record(model) if model is not None else None

    @override
    async def upsert_object_delivery(self, delivery: ObjectDeliveryUpsert) -> ObjectDeliveryRecord:
        await self._validate_object_delivery_scope(delivery)
        model = await self._session.scalar(
            select(ArchiveArtifactObjectDeliveryModel).where(
                ArchiveArtifactObjectDeliveryModel.artifact_id == delivery.artifact_id,
                ArchiveArtifactObjectDeliveryModel.object_binding_id == delivery.object_binding_id,
            )
        )
        if model is None:
            model = ArchiveArtifactObjectDeliveryModel(
                artifact_id=delivery.artifact_id,
                profile_revision_id=delivery.profile_revision_id,
                route_id=delivery.route_id,
                object_binding_id=delivery.object_binding_id,
                destination_id=delivery.destination_id,
                required=delivery.required,
                object_key=delivery.object_key,
                public_url=delivery.public_url,
                sha256=delivery.sha256,
                byte_size=delivery.byte_size,
                status=delivery.status,
            )
            self._session.add(model)
        _apply_delivery_state(model, delivery)
        await self._session.commit()
        await self._session.refresh(model)
        return _object_record(model)

    @override
    async def get_catalog_delivery(
        self, *, artifact_id: int, catalog_binding_id: int
    ) -> CatalogDeliveryRecord | None:
        model = await self._session.scalar(
            select(ArchiveArtifactCatalogDeliveryModel).where(
                ArchiveArtifactCatalogDeliveryModel.artifact_id == artifact_id,
                ArchiveArtifactCatalogDeliveryModel.catalog_binding_id == catalog_binding_id,
            )
        )
        return _catalog_record(model) if model is not None else None

    @override
    async def upsert_catalog_delivery(
        self, delivery: CatalogDeliveryUpsert
    ) -> CatalogDeliveryRecord:
        source_object_binding_id = await self._validate_catalog_delivery_scope(delivery)
        model = await self._session.scalar(
            select(ArchiveArtifactCatalogDeliveryModel).where(
                ArchiveArtifactCatalogDeliveryModel.artifact_id == delivery.artifact_id,
                ArchiveArtifactCatalogDeliveryModel.catalog_binding_id
                == delivery.catalog_binding_id,
            )
        )
        if model is None:
            model = ArchiveArtifactCatalogDeliveryModel(
                artifact_id=delivery.artifact_id,
                profile_revision_id=delivery.profile_revision_id,
                route_id=delivery.route_id,
                catalog_binding_id=delivery.catalog_binding_id,
                destination_id=delivery.destination_id,
                source_object_delivery_id=delivery.source_object_delivery_id,
                source_object_binding_id=source_object_binding_id,
                required=delivery.required,
                status=delivery.status,
            )
            self._session.add(model)
        _apply_delivery_state(model, delivery)
        await self._session.commit()
        await self._session.refresh(model)
        return _catalog_record(model)

    @override
    async def create_or_get_publication(
        self,
        publication: PublicationUpsert,
        *,
        artifact_ids: tuple[int, ...],
    ) -> PublicationRecord:
        await self._validate_publication_scope(publication)
        model = await self._publication_by_identity(
            route_id=publication.route_id,
            identity_key=publication.identity_key,
        )
        if model is not None:
            await self._ensure_matching_publication_identity(
                model,
                publication=publication,
                artifact_ids=artifact_ids,
            )
            return _publication_record(model)
        model = ArchivePublicationModel(
            profile_revision_id=publication.profile_revision_id,
            route_id=publication.route_id,
            schema_version=publication.schema_version,
            version=publication.version,
            membership_sha256=publication.membership_sha256,
            identity_key=publication.identity_key,
            status=publication.status,
            video_count=publication.video_count,
            artifact_count=publication.artifact_count,
            work_item_id=publication.work_item_id,
            work_attempt_id=publication.work_attempt_id,
            legacy_index_publication_id=publication.legacy_index_publication_id,
            error_code=publication.error_code,
            error_message=publication.error_message,
        )
        self._session.add(model)
        try:
            await self._session.flush()
            self._session.add_all(
                ArchivePublicationArtifactModel(
                    publication_id=model.id,
                    artifact_id=artifact_id,
                    position=position,
                )
                for position, artifact_id in enumerate(artifact_ids, start=1)
            )
            await self._session.commit()
            await self._session.refresh(model)
        except IntegrityError:
            await self._session.rollback()
            concurrent = await self._publication_by_identity(
                route_id=publication.route_id,
                identity_key=publication.identity_key,
            )
            if concurrent is None:
                raise
            await self._ensure_matching_publication_identity(
                concurrent,
                publication=publication,
                artifact_ids=artifact_ids,
            )
            model = concurrent
        return _publication_record(model)

    @override
    async def list_publication_artifact_ids(self, publication_id: int) -> tuple[int, ...]:
        values = await self._session.scalars(
            select(ArchivePublicationArtifactModel.artifact_id)
            .where(ArchivePublicationArtifactModel.publication_id == publication_id)
            .order_by(ArchivePublicationArtifactModel.position)
        )
        return tuple(values.all())

    @override
    async def get_publication(self, publication_id: int) -> PublicationRecord | None:
        model = await self._session.get(ArchivePublicationModel, publication_id)
        return _publication_record(model) if model is not None else None

    @override
    async def upsert_publication_delivery(
        self, delivery: PublicationDeliveryUpsert
    ) -> PublicationDeliveryRecord:
        route_id = await self._validate_publication_delivery_scope(delivery)
        model = await self._session.scalar(
            select(ArchivePublicationDeliveryModel).where(
                ArchivePublicationDeliveryModel.publication_id == delivery.publication_id,
                ArchivePublicationDeliveryModel.object_binding_id == delivery.object_binding_id,
            )
        )
        if model is None:
            model = ArchivePublicationDeliveryModel(
                publication_id=delivery.publication_id,
                route_id=route_id,
                object_binding_id=delivery.object_binding_id,
                destination_id=delivery.destination_id,
                required=delivery.required,
                status=delivery.status,
            )
            self._session.add(model)
        for name in (
            "status",
            "index_staging_key",
            "index_object_key",
            "index_public_url",
            "index_sha256",
            "index_byte_size",
            "index_succeeded_at",
            "pointer_staging_key",
            "pointer_object_key",
            "pointer_public_url",
            "pointer_sha256",
            "pointer_byte_size",
            "pointer_succeeded_at",
            "error_code",
            "error_message",
        ):
            setattr(model, name, getattr(delivery, name))
        model.last_work_item_id = delivery.work_item_id
        model.last_work_attempt_id = delivery.work_attempt_id
        model.attempt_count = (model.attempt_count or 0) + 1
        await self._session.commit()
        await self._session.refresh(model)
        return _publication_delivery_record(model)

    @override
    async def list_publication_deliveries(
        self, publication_id: int
    ) -> tuple[PublicationDeliveryRecord, ...]:
        models = await self._session.scalars(
            select(ArchivePublicationDeliveryModel)
            .where(ArchivePublicationDeliveryModel.publication_id == publication_id)
            .order_by(
                ArchivePublicationDeliveryModel.required.desc(),
                ArchivePublicationDeliveryModel.id,
            )
        )
        return tuple(_publication_delivery_record(model) for model in models)

    @override
    async def set_publication_status(
        self,
        publication_id: int,
        *,
        status: PublicationStatus,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        model = await self._session.get(ArchivePublicationModel, publication_id)
        if model is None:
            raise LookupError(f"Archive publication not found: {publication_id}")
        model.status = status
        model.error_code = error_code
        model.error_message = error_message
        await self._session.commit()

    @override
    async def has_newer_pointer_delivery(
        self,
        *,
        route_id: int,
        schema_version: int,
        object_binding_id: int,
        publication_id: int,
    ) -> bool:
        newer_id = await self._session.scalar(
            select(ArchivePublicationDeliveryModel.id)
            .join(
                ArchivePublicationModel,
                ArchivePublicationModel.id == ArchivePublicationDeliveryModel.publication_id,
            )
            .where(
                ArchivePublicationModel.route_id == route_id,
                ArchivePublicationModel.schema_version == schema_version,
                ArchivePublicationDeliveryModel.object_binding_id == object_binding_id,
                ArchivePublicationDeliveryModel.pointer_succeeded_at.is_not(None),
                ArchivePublicationModel.id > publication_id,
            )
            .limit(1)
        )
        return newer_id is not None

    async def _validate_object_delivery_scope(self, delivery: ObjectDeliveryUpsert) -> None:
        binding_id = await self._session.scalar(
            select(PublishRouteObjectBindingModel.id)
            .join(
                PublishProfileRouteModel,
                PublishProfileRouteModel.id == PublishRouteObjectBindingModel.route_id,
            )
            .where(
                PublishProfileRouteModel.id == delivery.route_id,
                PublishProfileRouteModel.profile_revision_id == delivery.profile_revision_id,
                PublishRouteObjectBindingModel.id == delivery.object_binding_id,
                PublishRouteObjectBindingModel.destination_id == delivery.destination_id,
                PublishRouteObjectBindingModel.required == delivery.required,
            )
        )
        if binding_id is None:
            raise ValueError(
                "Object delivery does not match its profile revision, route, binding, "
                "destination, and required snapshot."
            )

    async def _validate_catalog_delivery_scope(self, delivery: CatalogDeliveryUpsert) -> int:
        source_binding_id = await self._session.scalar(
            select(PublishRouteCatalogBindingModel.source_object_binding_id)
            .join(
                PublishProfileRouteModel,
                PublishProfileRouteModel.id == PublishRouteCatalogBindingModel.route_id,
            )
            .join(
                ArchiveArtifactObjectDeliveryModel,
                ArchiveArtifactObjectDeliveryModel.id == delivery.source_object_delivery_id,
            )
            .where(
                PublishProfileRouteModel.id == delivery.route_id,
                PublishProfileRouteModel.profile_revision_id == delivery.profile_revision_id,
                PublishRouteCatalogBindingModel.id == delivery.catalog_binding_id,
                PublishRouteCatalogBindingModel.destination_id == delivery.destination_id,
                PublishRouteCatalogBindingModel.required == delivery.required,
                ArchiveArtifactObjectDeliveryModel.artifact_id == delivery.artifact_id,
                ArchiveArtifactObjectDeliveryModel.profile_revision_id
                == delivery.profile_revision_id,
                ArchiveArtifactObjectDeliveryModel.route_id == delivery.route_id,
                ArchiveArtifactObjectDeliveryModel.object_binding_id
                == PublishRouteCatalogBindingModel.source_object_binding_id,
            )
        )
        if source_binding_id is None:
            raise ValueError(
                "Catalog delivery does not match its profile revision, route, binding, "
                "destination, or configured source object delivery."
            )
        return source_binding_id

    async def _validate_publication_scope(self, publication: PublicationUpsert) -> None:
        route_id = await self._session.scalar(
            select(PublishProfileRouteModel.id).where(
                PublishProfileRouteModel.id == publication.route_id,
                PublishProfileRouteModel.profile_revision_id == publication.profile_revision_id,
            )
        )
        if route_id is None:
            raise ValueError("Archive publication route does not belong to its profile revision.")

    async def _validate_publication_delivery_scope(
        self,
        delivery: PublicationDeliveryUpsert,
    ) -> int:
        route_id = await self._session.scalar(
            select(ArchivePublicationModel.route_id)
            .join(
                PublishRouteObjectBindingModel,
                PublishRouteObjectBindingModel.route_id == ArchivePublicationModel.route_id,
            )
            .where(
                ArchivePublicationModel.id == delivery.publication_id,
                PublishRouteObjectBindingModel.id == delivery.object_binding_id,
                PublishRouteObjectBindingModel.destination_id == delivery.destination_id,
                PublishRouteObjectBindingModel.required == delivery.required,
            )
        )
        if route_id is None:
            raise ValueError(
                "Publication delivery binding and destination do not belong to the "
                "publication route."
            )
        return route_id

    async def _publication_by_identity(
        self,
        *,
        route_id: int,
        identity_key: str,
    ) -> ArchivePublicationModel | None:
        return await self._session.scalar(
            select(ArchivePublicationModel).where(
                ArchivePublicationModel.route_id == route_id,
                ArchivePublicationModel.identity_key == identity_key,
            )
        )

    async def _ensure_matching_publication_identity(
        self,
        model: ArchivePublicationModel,
        *,
        publication: PublicationUpsert,
        artifact_ids: tuple[int, ...],
    ) -> None:
        immutable_values_match = (
            model.profile_revision_id == publication.profile_revision_id
            and model.route_id == publication.route_id
            and model.schema_version == publication.schema_version
            and model.membership_sha256 == publication.membership_sha256
            and model.video_count == publication.video_count
            and model.artifact_count == publication.artifact_count
            and model.legacy_index_publication_id == publication.legacy_index_publication_id
        )
        stored_artifact_ids = await self.list_publication_artifact_ids(model.id)
        if immutable_values_match and stored_artifact_ids == artifact_ids:
            return
        raise ValueError(
            "Archive publication identity was reused with different immutable inputs: "
            f"route={publication.route_id}, identity={publication.identity_key}."
        )

    @override
    @asynccontextmanager
    async def pointer_lock(
        self,
        *,
        route_id: int,
        schema_version: int,
    ) -> AsyncGenerator[None]:
        bind = self._session.bind
        if bind is not None and bind.dialect.name == "postgresql":
            if isinstance(bind, AsyncEngine):
                async with bind.connect() as connection:
                    await _acquire_pg_pointer_lock(
                        connection,
                        route_id=route_id,
                        schema_version=schema_version,
                    )
                    try:
                        yield
                    finally:
                        await _release_pg_pointer_lock(
                            connection,
                            route_id=route_id,
                            schema_version=schema_version,
                        )
                return
            if isinstance(bind, AsyncConnection):
                await _acquire_pg_pointer_lock(
                    bind,
                    route_id=route_id,
                    schema_version=schema_version,
                )
                try:
                    yield
                finally:
                    await _release_pg_pointer_lock(
                        bind,
                        route_id=route_id,
                        schema_version=schema_version,
                    )
                return
        lock = _LOCAL_POINTER_LOCKS.setdefault((route_id, schema_version), asyncio.Lock())
        async with lock:
            yield

    async def _required_artifact(self, artifact_id: int) -> ArchiveVideoArtifactModel:
        model = await self._session.get(ArchiveVideoArtifactModel, artifact_id)
        if model is None:
            raise LookupError(f"Archive artifact not found: {artifact_id}")
        return model


def _apply_delivery_state(
    model: ArchiveArtifactObjectDeliveryModel | ArchiveArtifactCatalogDeliveryModel,
    delivery: ObjectDeliveryUpsert | CatalogDeliveryUpsert,
) -> None:
    model.status = delivery.status
    model.last_work_item_id = delivery.work_item_id
    model.last_work_attempt_id = delivery.work_attempt_id
    model.error_code = delivery.error_code
    model.error_message = delivery.error_message
    model.attempt_count = (model.attempt_count or 0) + 1
    model.succeeded_at = datetime.now(UTC) if delivery.status == "succeeded" else None


def _object_record(model: ArchiveArtifactObjectDeliveryModel) -> ObjectDeliveryRecord:
    return ObjectDeliveryRecord(
        id=model.id,
        artifact_id=model.artifact_id,
        profile_revision_id=model.profile_revision_id,
        route_id=model.route_id,
        object_binding_id=model.object_binding_id,
        destination_id=model.destination_id,
        required=model.required,
        object_key=model.object_key,
        public_url=model.public_url,
        sha256=model.sha256,
        byte_size=model.byte_size,
        status=model.status,  # type: ignore[arg-type]
        attempt_count=model.attempt_count,
        work_item_id=model.last_work_item_id,
        work_attempt_id=model.last_work_attempt_id,
        error_code=model.error_code,
        error_message=model.error_message,
        succeeded_at=model.succeeded_at,
        updated_at=model.updated_at,
    )


def _catalog_record(model: ArchiveArtifactCatalogDeliveryModel) -> CatalogDeliveryRecord:
    return CatalogDeliveryRecord(
        id=model.id,
        artifact_id=model.artifact_id,
        profile_revision_id=model.profile_revision_id,
        route_id=model.route_id,
        catalog_binding_id=model.catalog_binding_id,
        destination_id=model.destination_id,
        source_object_delivery_id=model.source_object_delivery_id,
        required=model.required,
        status=model.status,  # type: ignore[arg-type]
        attempt_count=model.attempt_count,
        work_item_id=model.last_work_item_id,
        work_attempt_id=model.last_work_attempt_id,
        error_code=model.error_code,
        error_message=model.error_message,
        succeeded_at=model.succeeded_at,
        updated_at=model.updated_at,
    )


def _publication_record(model: ArchivePublicationModel) -> PublicationRecord:
    return PublicationRecord(
        id=model.id,
        profile_revision_id=model.profile_revision_id,
        route_id=model.route_id,
        schema_version=model.schema_version,
        version=model.version,
        membership_sha256=model.membership_sha256,
        identity_key=model.identity_key,
        status=model.status,  # type: ignore[arg-type]
        video_count=model.video_count,
        artifact_count=model.artifact_count,
        work_item_id=model.work_item_id,
        work_attempt_id=model.work_attempt_id,
        legacy_index_publication_id=model.legacy_index_publication_id,
        error_code=model.error_code,
        error_message=model.error_message,
        created_at=model.created_at,
    )


def _publication_delivery_record(
    model: ArchivePublicationDeliveryModel,
) -> PublicationDeliveryRecord:
    return PublicationDeliveryRecord(
        id=model.id,
        publication_id=model.publication_id,
        object_binding_id=model.object_binding_id,
        destination_id=model.destination_id,
        required=model.required,
        status=model.status,  # type: ignore[arg-type]
        index_staging_key=model.index_staging_key,
        index_object_key=model.index_object_key,
        index_public_url=model.index_public_url,
        index_sha256=model.index_sha256,
        index_byte_size=model.index_byte_size,
        index_succeeded_at=model.index_succeeded_at,
        pointer_staging_key=model.pointer_staging_key,
        pointer_object_key=model.pointer_object_key,
        pointer_public_url=model.pointer_public_url,
        pointer_sha256=model.pointer_sha256,
        pointer_byte_size=model.pointer_byte_size,
        pointer_succeeded_at=model.pointer_succeeded_at,
        attempt_count=model.attempt_count,
        work_item_id=model.last_work_item_id,
        work_attempt_id=model.last_work_attempt_id,
        error_code=model.error_code,
        error_message=model.error_message,
        updated_at=model.updated_at,
    )


async def _acquire_pg_pointer_lock(
    connection: AsyncConnection,
    *,
    route_id: int,
    schema_version: int,
) -> None:
    await connection.execute(
        text("SELECT pg_advisory_lock(:route_id, :schema_version)"),
        {"route_id": route_id, "schema_version": schema_version},
    )


async def _release_pg_pointer_lock(
    connection: AsyncConnection,
    *,
    route_id: int,
    schema_version: int,
) -> None:
    await connection.execute(
        text("SELECT pg_advisory_unlock(:route_id, :schema_version)"),
        {"route_id": route_id, "schema_version": schema_version},
    )
