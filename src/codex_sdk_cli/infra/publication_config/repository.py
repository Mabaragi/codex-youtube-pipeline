from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    select,
    text,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import Select
from typing_extensions import override

from codex_sdk_cli.application.publication_config.ports import (
    CreateCatalogDestination,
    CreateObjectDestination,
    CreatePublishProfile,
    CreatePublishProfileRevision,
    CreatePublishProfileRoute,
    CreateRouteCatalogBinding,
    CreateRouteObjectBinding,
    PublishConfigurationRepositoryPort,
    ResolvedCatalogBinding,
    ResolvedObjectBinding,
    ResolvedPublishRoute,
)
from codex_sdk_cli.domains.publication_config.exceptions import (
    PublishConfigurationConflict,
    PublishConfigurationPersistenceError,
)
from codex_sdk_cli.domains.publication_config.models import (
    PublishCatalogDestination,
    PublishMode,
    PublishObjectDestination,
    PublishProfile,
    PublishProfileDetail,
    PublishProfileRevision,
    PublishProfileRevisionState,
    PublishProfileRoute,
    PublishRouteCatalogBinding,
    PublishRouteObjectBinding,
)
from codex_sdk_cli.infra.database.base import Base


class PublishProfileModel(Base):
    __tablename__ = "publish_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    active_revision_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "publish_profile_revisions.id",
            name="fk_publish_profiles_active_revision",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class PublishProfileRevisionModel(Base):
    __tablename__ = "publish_profile_revisions"
    __table_args__ = (
        UniqueConstraint(
            "profile_id",
            "revision_number",
            name="uq_publish_profile_revisions_profile_number",
        ),
        CheckConstraint(
            "state IN ('draft', 'active', 'retired')",
            name="publish_profile_revisions_state_allowed",
        ),
        Index("ix_publish_profile_revisions_profile_state", "profile_id", "state"),
        Index(
            "uq_publish_profile_revisions_single_active",
            "profile_id",
            unique=True,
            postgresql_where=text("state = 'active'"),
            sqlite_where=text("state = 'active'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("publish_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PublishProfileRouteModel(Base):
    __tablename__ = "publish_profile_routes"
    __table_args__ = (
        UniqueConstraint(
            "profile_revision_id",
            "publish_mode",
            "environment",
            name="uq_publish_profile_routes_revision_mode_environment",
        ),
        UniqueConstraint(
            "id",
            "profile_revision_id",
            name="uq_publish_profile_routes_id_revision",
        ),
        CheckConstraint(
            "publish_mode IN ('prod', 'dev')",
            name="publish_profile_routes_mode_allowed",
        ),
        Index(
            "ix_publish_profile_routes_revision_lookup",
            "profile_revision_id",
            "publish_mode",
            "environment",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_revision_id: Mapped[int] = mapped_column(
        ForeignKey("publish_profile_revisions.id", ondelete="CASCADE"),
        nullable=False,
    )
    publish_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    environment: Mapped[str] = mapped_column(String(64), nullable=False)


class PublishObjectDestinationModel(Base):
    __tablename__ = "publish_object_destinations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    connection_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class PublishCatalogDestinationModel(Base):
    __tablename__ = "publish_catalog_destinations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    connection_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class PublishRouteObjectBindingModel(Base):
    __tablename__ = "publish_route_object_bindings"
    __table_args__ = (
        UniqueConstraint(
            "route_id",
            "destination_id",
            name="uq_publish_route_object_bindings_route_destination",
        ),
        UniqueConstraint(
            "id",
            "route_id",
            name="uq_publish_route_object_bindings_id_route",
        ),
        UniqueConstraint(
            "id",
            "route_id",
            "destination_id",
            "required",
            name="uq_publish_route_object_bindings_delivery_scope",
        ),
        Index("ix_publish_route_object_bindings_route", "route_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    route_id: Mapped[int] = mapped_column(
        ForeignKey("publish_profile_routes.id", ondelete="CASCADE"),
        nullable=False,
    )
    destination_id: Mapped[int] = mapped_column(
        ForeignKey("publish_object_destinations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    key_prefix: Mapped[str] = mapped_column(String(512), nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class PublishRouteCatalogBindingModel(Base):
    __tablename__ = "publish_route_catalog_bindings"
    __table_args__ = (
        UniqueConstraint(
            "route_id",
            "destination_id",
            name="uq_publish_route_catalog_bindings_route_destination",
        ),
        ForeignKeyConstraint(
            ["source_object_binding_id", "route_id"],
            [
                "publish_route_object_bindings.id",
                "publish_route_object_bindings.route_id",
            ],
            name="fk_publish_route_catalog_binding_source_same_route",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "id",
            "route_id",
            "destination_id",
            "source_object_binding_id",
            "required",
            name="uq_publish_route_catalog_bindings_delivery_scope",
        ),
        Index("ix_publish_route_catalog_bindings_route", "route_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    route_id: Mapped[int] = mapped_column(
        ForeignKey("publish_profile_routes.id", ondelete="CASCADE"),
        nullable=False,
    )
    destination_id: Mapped[int] = mapped_column(
        ForeignKey("publish_catalog_destinations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_object_binding_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


def _profile_for_activation_statement(
    profile_id: int,
) -> Select[PublishProfileModel]:
    return select(PublishProfileModel).where(PublishProfileModel.id == profile_id).with_for_update()


class SqlAlchemyPublishConfigurationRepository(PublishConfigurationRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def create_object_destination(
        self,
        create: CreateObjectDestination,
    ) -> PublishObjectDestination:
        model = PublishObjectDestinationModel(
            key=create.key,
            name=create.name,
            connection_ref=create.connection_ref,
        )
        self._session.add(model)
        await self._commit_create("Object destination already exists.")
        await self._session.refresh(model)
        return _object_destination(model)

    @override
    async def list_object_destinations(self) -> list[PublishObjectDestination]:
        try:
            models = await self._session.scalars(
                select(PublishObjectDestinationModel).order_by(PublishObjectDestinationModel.id)
            )
            return [_object_destination(model) for model in models]
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc

    @override
    async def create_catalog_destination(
        self,
        create: CreateCatalogDestination,
    ) -> PublishCatalogDestination:
        model = PublishCatalogDestinationModel(
            key=create.key,
            name=create.name,
            connection_ref=create.connection_ref,
        )
        self._session.add(model)
        await self._commit_create("Catalog destination already exists.")
        await self._session.refresh(model)
        return _catalog_destination(model)

    @override
    async def list_catalog_destinations(self) -> list[PublishCatalogDestination]:
        try:
            models = await self._session.scalars(
                select(PublishCatalogDestinationModel).order_by(PublishCatalogDestinationModel.id)
            )
            return [_catalog_destination(model) for model in models]
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc

    @override
    async def create_profile(self, create: CreatePublishProfile) -> PublishProfile:
        model = PublishProfileModel(
            key=create.key,
            name=create.name,
            description=create.description,
        )
        self._session.add(model)
        await self._commit_create("Publish profile already exists.")
        await self._session.refresh(model)
        return _profile(model)

    @override
    async def list_profiles(self) -> list[PublishProfile]:
        try:
            models = await self._session.scalars(
                select(PublishProfileModel).order_by(PublishProfileModel.id)
            )
            return [_profile(model) for model in models]
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc

    @override
    async def get_profile(self, profile_id: int) -> PublishProfileDetail | None:
        try:
            profile = await self._session.get(PublishProfileModel, profile_id)
            if profile is None:
                return None
            revisions = await self._session.scalars(
                select(PublishProfileRevisionModel)
                .where(PublishProfileRevisionModel.profile_id == profile_id)
                .order_by(PublishProfileRevisionModel.revision_number.desc())
            )
            revision_records = [await self._revision_record(revision) for revision in revisions]
            return PublishProfileDetail(
                profile=_profile(profile),
                revisions=tuple(revision_records),
            )
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc

    @override
    async def create_revision(
        self,
        create: CreatePublishProfileRevision,
    ) -> PublishProfileRevision | None:
        profile = await self._session.get(PublishProfileModel, create.profile_id)
        if profile is None:
            return None
        try:
            revision_number = (
                await self._session.scalar(
                    select(func.max(PublishProfileRevisionModel.revision_number)).where(
                        PublishProfileRevisionModel.profile_id == create.profile_id
                    )
                )
                or 0
            ) + 1
            revision = PublishProfileRevisionModel(
                profile_id=create.profile_id,
                revision_number=revision_number,
                state="draft",
            )
            self._session.add(revision)
            await self._session.flush()
            for route_create in create.routes:
                await self._create_revision_route(revision.id, route_create)
            await self._session.commit()
            return await self._revision_record(revision)
        except PublishConfigurationConflict:
            await self._session.rollback()
            raise
        except IntegrityError as exc:
            await self._session.rollback()
            raise PublishConfigurationConflict(
                "Publish profile revision conflicts with existing configuration."
            ) from exc
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise _persistence_error() from exc

    async def _create_revision_route(
        self,
        revision_id: int,
        create: CreatePublishProfileRoute,
    ) -> None:
        route = PublishProfileRouteModel(
            profile_revision_id=revision_id,
            publish_mode=create.publish_mode,
            environment=create.environment,
        )
        self._session.add(route)
        await self._session.flush()
        object_bindings = await self._create_route_object_bindings(
            route.id,
            create.object_bindings,
        )
        await self._create_route_catalog_bindings(
            route.id,
            create.catalog_bindings,
            object_bindings,
        )

    async def _create_route_object_bindings(
        self,
        route_id: int,
        creates: tuple[CreateRouteObjectBinding, ...],
    ) -> dict[int, PublishRouteObjectBindingModel]:
        bindings: dict[int, PublishRouteObjectBindingModel] = {}
        for create in creates:
            if (
                await self._session.get(
                    PublishObjectDestinationModel,
                    create.destination_id,
                )
                is None
            ):
                raise PublishConfigurationConflict("Object destination not found.")
            binding = PublishRouteObjectBindingModel(
                route_id=route_id,
                destination_id=create.destination_id,
                key_prefix=create.key_prefix,
                required=create.required,
                is_primary=create.is_primary,
            )
            self._session.add(binding)
            await self._session.flush()
            bindings[binding.destination_id] = binding
        return bindings

    async def _create_route_catalog_bindings(
        self,
        route_id: int,
        creates: tuple[CreateRouteCatalogBinding, ...],
        object_bindings: dict[int, PublishRouteObjectBindingModel],
    ) -> None:
        for create in creates:
            if (
                await self._session.get(
                    PublishCatalogDestinationModel,
                    create.destination_id,
                )
                is None
            ):
                raise PublishConfigurationConflict("Catalog destination not found.")
            source_binding = object_bindings.get(create.source_object_destination_id)
            if source_binding is None:
                raise PublishConfigurationConflict(
                    "Catalog source object binding not found in route."
                )
            self._session.add(
                PublishRouteCatalogBindingModel(
                    route_id=route_id,
                    destination_id=create.destination_id,
                    source_object_binding_id=source_binding.id,
                    required=create.required,
                )
            )

    @override
    async def activate_revision(
        self,
        *,
        profile_id: int,
        revision_id: int,
    ) -> PublishProfileRevision | None:
        try:
            profile = await self._session.scalar(_profile_for_activation_statement(profile_id))
            revision = await self._session.get(PublishProfileRevisionModel, revision_id)
            if profile is None or revision is None or revision.profile_id != profile_id:
                return None
            if profile.active_revision_id == revision.id and revision.state == "active":
                return await self._revision_record(revision)
            if revision.state != "draft":
                raise PublishConfigurationConflict(
                    "Only draft publish profile revisions can be activated."
                )
            route_id = await self._session.scalar(
                select(PublishProfileRouteModel.id)
                .where(PublishProfileRouteModel.profile_revision_id == revision.id)
                .limit(1)
            )
            if route_id is None:
                raise PublishConfigurationConflict(
                    "A publish profile revision requires at least one route."
                )
            if profile.active_revision_id is not None:
                previous = await self._session.get(
                    PublishProfileRevisionModel,
                    profile.active_revision_id,
                )
                if previous is not None:
                    previous.state = "retired"
                    await self._session.flush()
            now = datetime.now(UTC)
            revision.state = "active"
            revision.activated_at = now
            profile.active_revision_id = revision.id
            await self._session.commit()
            return await self._revision_record(revision)
        except PublishConfigurationConflict:
            await self._session.rollback()
            raise
        except IntegrityError as exc:
            await self._session.rollback()
            raise PublishConfigurationConflict(
                "Publish profile revision activation conflicted with another activation."
            ) from exc
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise _persistence_error() from exc

    @override
    async def is_profile_active(self, profile_id: int) -> bool:
        try:
            return (
                await self._session.scalar(
                    select(PublishProfileRevisionModel.id)
                    .join(
                        PublishProfileModel,
                        PublishProfileModel.active_revision_id == PublishProfileRevisionModel.id,
                    )
                    .where(
                        PublishProfileModel.id == profile_id,
                        PublishProfileRevisionModel.state == "active",
                    )
                    .limit(1)
                )
                is not None
            )
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc

    @override
    async def resolve_active_route(
        self,
        *,
        streamer_id: int,
        publish_mode: PublishMode,
        environment: str,
    ) -> ResolvedPublishRoute | None:
        from codex_sdk_cli.infra.streamers.repository import StreamerModel

        try:
            result = await self._session.execute(
                select(
                    PublishProfileModel,
                    PublishProfileRevisionModel,
                    PublishProfileRouteModel,
                )
                .join(
                    StreamerModel,
                    StreamerModel.publish_profile_id == PublishProfileModel.id,
                )
                .join(
                    PublishProfileRevisionModel,
                    PublishProfileRevisionModel.id == PublishProfileModel.active_revision_id,
                )
                .join(
                    PublishProfileRouteModel,
                    PublishProfileRouteModel.profile_revision_id == PublishProfileRevisionModel.id,
                )
                .where(
                    StreamerModel.id == streamer_id,
                    PublishProfileRevisionModel.state == "active",
                    PublishProfileRouteModel.publish_mode == publish_mode,
                    PublishProfileRouteModel.environment == environment,
                )
            )
            row = result.one_or_none()
            if row is None:
                return None
            profile, revision, route = row
            object_bindings = await self._resolved_object_bindings(route.id)
            catalog_bindings = await self._resolved_catalog_bindings(route.id)
            return ResolvedPublishRoute(
                profile_id=profile.id,
                profile_key=profile.key,
                profile_revision_id=revision.id,
                revision_number=revision.revision_number,
                route_id=route.id,
                publish_mode=cast(PublishMode, route.publish_mode),
                environment=route.environment,
                object_bindings=object_bindings,
                catalog_bindings=catalog_bindings,
            )
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc

    @override
    async def resolve_revision_route(
        self,
        *,
        profile_revision_id: int,
        publish_mode: PublishMode,
        environment: str,
    ) -> ResolvedPublishRoute | None:
        try:
            result = await self._session.execute(
                select(
                    PublishProfileModel,
                    PublishProfileRevisionModel,
                    PublishProfileRouteModel,
                )
                .join(
                    PublishProfileRevisionModel,
                    PublishProfileRevisionModel.profile_id == PublishProfileModel.id,
                )
                .join(
                    PublishProfileRouteModel,
                    PublishProfileRouteModel.profile_revision_id == PublishProfileRevisionModel.id,
                )
                .where(
                    PublishProfileRevisionModel.id == profile_revision_id,
                    PublishProfileRouteModel.publish_mode == publish_mode,
                    PublishProfileRouteModel.environment == environment,
                )
            )
            row = result.one_or_none()
            if row is None:
                return None
            profile, revision, route = row
            return ResolvedPublishRoute(
                profile_id=profile.id,
                profile_key=profile.key,
                profile_revision_id=revision.id,
                revision_number=revision.revision_number,
                route_id=route.id,
                publish_mode=cast(PublishMode, route.publish_mode),
                environment=route.environment,
                object_bindings=await self._resolved_object_bindings(route.id),
                catalog_bindings=await self._resolved_catalog_bindings(route.id),
            )
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc

    @override
    async def get_route(self, route_id: int) -> ResolvedPublishRoute | None:
        try:
            result = await self._session.execute(
                select(
                    PublishProfileModel,
                    PublishProfileRevisionModel,
                    PublishProfileRouteModel,
                )
                .join(
                    PublishProfileRevisionModel,
                    PublishProfileRevisionModel.profile_id == PublishProfileModel.id,
                )
                .join(
                    PublishProfileRouteModel,
                    PublishProfileRouteModel.profile_revision_id == PublishProfileRevisionModel.id,
                )
                .where(PublishProfileRouteModel.id == route_id)
            )
            row = result.one_or_none()
            if row is None:
                return None
            profile, revision, route = row
            return ResolvedPublishRoute(
                profile_id=profile.id,
                profile_key=profile.key,
                profile_revision_id=revision.id,
                revision_number=revision.revision_number,
                route_id=route.id,
                publish_mode=cast(PublishMode, route.publish_mode),
                environment=route.environment,
                object_bindings=await self._resolved_object_bindings(route.id),
                catalog_bindings=await self._resolved_catalog_bindings(route.id),
            )
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc

    async def _commit_create(self, conflict_message: str) -> None:
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise PublishConfigurationConflict(conflict_message) from exc
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise _persistence_error() from exc

    async def _revision_record(
        self,
        model: PublishProfileRevisionModel,
    ) -> PublishProfileRevision:
        routes = await self._session.scalars(
            select(PublishProfileRouteModel)
            .where(PublishProfileRouteModel.profile_revision_id == model.id)
            .order_by(PublishProfileRouteModel.id)
        )
        route_records = [await self._route_record(route) for route in routes]
        return PublishProfileRevision(
            id=model.id,
            profile_id=model.profile_id,
            revision_number=model.revision_number,
            state=cast(PublishProfileRevisionState, model.state),
            created_at=model.created_at,
            activated_at=model.activated_at,
            routes=tuple(route_records),
        )

    async def _route_record(self, model: PublishProfileRouteModel) -> PublishProfileRoute:
        object_rows = await self._object_binding_rows(model.id)
        catalog_rows = await self._catalog_binding_rows(model.id)
        return PublishProfileRoute(
            id=model.id,
            publish_mode=cast(PublishMode, model.publish_mode),
            environment=model.environment,
            object_bindings=tuple(
                PublishRouteObjectBinding(
                    id=binding.id,
                    destination_id=destination.id,
                    destination_key=destination.key,
                    connection_ref=destination.connection_ref,
                    key_prefix=binding.key_prefix,
                    required=binding.required,
                    is_primary=binding.is_primary,
                )
                for binding, destination in object_rows
            ),
            catalog_bindings=tuple(
                PublishRouteCatalogBinding(
                    id=binding.id,
                    destination_id=destination.id,
                    destination_key=destination.key,
                    connection_ref=destination.connection_ref,
                    source_object_binding_id=binding.source_object_binding_id,
                    required=binding.required,
                )
                for binding, destination in catalog_rows
            ),
        )

    async def _resolved_object_bindings(
        self,
        route_id: int,
    ) -> tuple[ResolvedObjectBinding, ...]:
        return tuple(
            ResolvedObjectBinding(
                id=binding.id,
                destination_id=destination.id,
                connection_ref=destination.connection_ref,
                key_prefix=binding.key_prefix,
                required=binding.required,
                is_primary=binding.is_primary,
            )
            for binding, destination in await self._object_binding_rows(route_id)
        )

    async def _resolved_catalog_bindings(
        self,
        route_id: int,
    ) -> tuple[ResolvedCatalogBinding, ...]:
        return tuple(
            ResolvedCatalogBinding(
                id=binding.id,
                destination_id=destination.id,
                connection_ref=destination.connection_ref,
                source_object_binding_id=binding.source_object_binding_id,
                required=binding.required,
            )
            for binding, destination in await self._catalog_binding_rows(route_id)
        )

    async def _object_binding_rows(
        self,
        route_id: int,
    ) -> list[tuple[PublishRouteObjectBindingModel, PublishObjectDestinationModel]]:
        rows = await self._session.execute(
            select(PublishRouteObjectBindingModel, PublishObjectDestinationModel)
            .join(
                PublishObjectDestinationModel,
                PublishObjectDestinationModel.id == PublishRouteObjectBindingModel.destination_id,
            )
            .where(PublishRouteObjectBindingModel.route_id == route_id)
            .order_by(
                PublishRouteObjectBindingModel.is_primary.desc(),
                PublishRouteObjectBindingModel.id,
            )
        )
        return [(binding, destination) for binding, destination in rows]

    async def _catalog_binding_rows(
        self,
        route_id: int,
    ) -> list[tuple[PublishRouteCatalogBindingModel, PublishCatalogDestinationModel]]:
        rows = await self._session.execute(
            select(PublishRouteCatalogBindingModel, PublishCatalogDestinationModel)
            .join(
                PublishCatalogDestinationModel,
                PublishCatalogDestinationModel.id == PublishRouteCatalogBindingModel.destination_id,
            )
            .where(PublishRouteCatalogBindingModel.route_id == route_id)
            .order_by(PublishRouteCatalogBindingModel.id)
        )
        return [(binding, destination) for binding, destination in rows]


def _object_destination(model: PublishObjectDestinationModel) -> PublishObjectDestination:
    return PublishObjectDestination(
        id=model.id,
        key=model.key,
        name=model.name,
        connection_ref=model.connection_ref,
        created_at=model.created_at,
    )


def _catalog_destination(model: PublishCatalogDestinationModel) -> PublishCatalogDestination:
    return PublishCatalogDestination(
        id=model.id,
        key=model.key,
        name=model.name,
        connection_ref=model.connection_ref,
        created_at=model.created_at,
    )


def _profile(model: PublishProfileModel) -> PublishProfile:
    return PublishProfile(
        id=model.id,
        key=model.key,
        name=model.name,
        description=model.description,
        active_revision_id=model.active_revision_id,
        created_at=model.created_at,
    )


def _persistence_error() -> PublishConfigurationPersistenceError:
    return PublishConfigurationPersistenceError("Publication configuration persistence failed.")
