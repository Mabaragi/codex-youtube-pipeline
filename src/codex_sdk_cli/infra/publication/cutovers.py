from __future__ import annotations

import json
from datetime import datetime
from typing import cast

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    select,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from typing_extensions import override

from codex_sdk_cli.application.publication.cutover_ports import (
    PublicationCutoverAdvance,
    PublicationCutoverCreate,
    PublicationCutoverRecord,
    PublicationCutoverRepositoryPort,
    PublicationCutoverStatus,
    PublicationCutoverStep,
)
from codex_sdk_cli.infra.database.base import Base


class PublishProfileCutoverModel(Base):
    __tablename__ = "publish_profile_cutovers"
    __table_args__ = (
        CheckConstraint(
            "status IN ('preparing','prepared','target_pointer_published',"
            "'streamer_assigned','source_ready','completed','failed')",
            name="publish_profile_cutovers_status_allowed",
        ),
        CheckConstraint(
            "publish_mode IN ('prod','dev')",
            name="publish_profile_cutovers_mode_allowed",
        ),
        UniqueConstraint("request_key", name="uq_publish_profile_cutovers_request_key"),
        UniqueConstraint("open_key", name="uq_publish_profile_cutovers_open_key"),
        Index(
            "ix_publish_profile_cutovers_streamer_status",
            "streamer_id",
            "status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_key: Mapped[str] = mapped_column(String(64), nullable=False)
    open_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    streamer_id: Mapped[int] = mapped_column(
        ForeignKey("streamers.id", ondelete="RESTRICT"), nullable=False
    )
    source_profile_id: Mapped[int] = mapped_column(
        ForeignKey("publish_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    target_profile_id: Mapped[int] = mapped_column(
        ForeignKey("publish_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    source_profile_revision_id: Mapped[int] = mapped_column(
        ForeignKey("publish_profile_revisions.id", ondelete="RESTRICT"), nullable=False
    )
    target_profile_revision_id: Mapped[int] = mapped_column(
        ForeignKey("publish_profile_revisions.id", ondelete="RESTRICT"), nullable=False
    )
    source_route_id: Mapped[int] = mapped_column(
        ForeignKey("publish_profile_routes.id", ondelete="RESTRICT"), nullable=False
    )
    target_route_id: Mapped[int] = mapped_column(
        ForeignKey("publish_profile_routes.id", ondelete="RESTRICT"), nullable=False
    )
    publish_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    environment: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    artifact_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    operator_reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="preparing")
    last_completed_step: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_publication_id: Mapped[int | None] = mapped_column(
        ForeignKey("archive_publications.id", ondelete="RESTRICT"), nullable=True
    )
    source_publication_id: Mapped[int | None] = mapped_column(
        ForeignKey("archive_publications.id", ondelete="RESTRICT"), nullable=True
    )
    target_pointer_published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    streamer_assigned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_pointer_published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error_step: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class SqlAlchemyPublicationCutoverRepository(PublicationCutoverRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def create_or_get(
        self,
        create: PublicationCutoverCreate,
    ) -> PublicationCutoverRecord:
        existing = await self._by_request_key(create.request_key)
        if existing is not None:
            return _record(existing)
        model = PublishProfileCutoverModel(
            request_key=create.request_key,
            open_key=_open_key(
                streamer_id=create.streamer_id,
                publish_mode=create.publish_mode,
                environment=create.environment,
            ),
            streamer_id=create.streamer_id,
            source_profile_id=create.source_profile_id,
            target_profile_id=create.target_profile_id,
            source_profile_revision_id=create.source_profile_revision_id,
            target_profile_revision_id=create.target_profile_revision_id,
            source_route_id=create.source_route_id,
            target_route_id=create.target_route_id,
            publish_mode=create.publish_mode,
            environment=create.environment,
            schema_version=create.schema_version,
            artifact_ids_json=json.dumps(create.artifact_ids, separators=(",", ":")),
            operator_reason=create.operator_reason,
            status="preparing",
        )
        self._session.add(model)
        try:
            await self._session.commit()
            await self._session.refresh(model)
            return _record(model)
        except IntegrityError:
            await self._session.rollback()
            concurrent = await self._by_request_key(create.request_key)
            if concurrent is not None:
                return _record(concurrent)
            open_model = await self._open_model(
                streamer_id=create.streamer_id,
                publish_mode=create.publish_mode,
                environment=create.environment,
            )
            if open_model is not None:
                return _record(open_model)
            raise

    @override
    async def get(self, cutover_id: int) -> PublicationCutoverRecord | None:
        try:
            model = await self._session.get(PublishProfileCutoverModel, cutover_id)
            return _record(model) if model is not None else None
        except SQLAlchemyError as exc:
            raise RuntimeError("Publication cutover persistence failed.") from exc

    @override
    async def list(self, *, limit: int = 100) -> list[PublicationCutoverRecord]:
        try:
            models = await self._session.scalars(
                select(PublishProfileCutoverModel)
                .order_by(PublishProfileCutoverModel.id.desc())
                .limit(limit)
            )
            return [_record(model) for model in models]
        except SQLAlchemyError as exc:
            raise RuntimeError("Publication cutover persistence failed.") from exc

    @override
    async def find_open(
        self,
        *,
        streamer_id: int,
        publish_mode: str,
        environment: str,
    ) -> PublicationCutoverRecord | None:
        try:
            model = await self._open_model(
                streamer_id=streamer_id,
                publish_mode=publish_mode,
                environment=environment,
            )
            return _record(model) if model is not None else None
        except SQLAlchemyError as exc:
            raise RuntimeError("Publication cutover persistence failed.") from exc

    @override
    async def advance(
        self,
        cutover_id: int,
        advance: PublicationCutoverAdvance,
    ) -> PublicationCutoverRecord:
        model = await self._required(cutover_id)
        model.status = advance.status
        if advance.status == "completed":
            model.open_key = None
        if advance.last_completed_step is not None:
            model.last_completed_step = advance.last_completed_step
        if advance.target_publication_id is not None:
            model.target_publication_id = advance.target_publication_id
        if advance.source_publication_id is not None:
            model.source_publication_id = advance.source_publication_id
        if advance.target_pointer_published_at is not None:
            model.target_pointer_published_at = advance.target_pointer_published_at
        if advance.streamer_assigned_at is not None:
            model.streamer_assigned_at = advance.streamer_assigned_at
        if advance.source_pointer_published_at is not None:
            model.source_pointer_published_at = advance.source_pointer_published_at
        if advance.clear_error:
            model.last_error_step = None
            model.last_error_code = None
            model.last_error_message = None
        return await self._commit(model)

    @override
    async def mark_failed(
        self,
        cutover_id: int,
        *,
        step: PublicationCutoverStep,
        error_code: str,
        error_message: str,
    ) -> PublicationCutoverRecord:
        model = await self._required(cutover_id)
        model.status = "failed"
        model.last_error_step = step
        model.last_error_code = error_code[:128]
        model.last_error_message = error_message[:4000]
        return await self._commit(model)

    async def _by_request_key(self, request_key: str) -> PublishProfileCutoverModel | None:
        return await self._session.scalar(
            select(PublishProfileCutoverModel).where(
                PublishProfileCutoverModel.request_key == request_key
            )
        )

    async def _open_model(
        self,
        *,
        streamer_id: int,
        publish_mode: str,
        environment: str,
    ) -> PublishProfileCutoverModel | None:
        return await self._session.scalar(
            select(PublishProfileCutoverModel)
            .where(
                PublishProfileCutoverModel.open_key
                == _open_key(
                    streamer_id=streamer_id,
                    publish_mode=publish_mode,
                    environment=environment,
                )
            )
            .limit(1)
        )

    async def _required(self, cutover_id: int) -> PublishProfileCutoverModel:
        model = await self._session.get(PublishProfileCutoverModel, cutover_id)
        if model is None:
            raise LookupError(f"Publication cutover not found: {cutover_id}")
        return model

    async def _commit(
        self,
        model: PublishProfileCutoverModel,
    ) -> PublicationCutoverRecord:
        try:
            await self._session.commit()
            await self._session.refresh(model)
            return _record(model)
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise RuntimeError("Publication cutover persistence failed.") from exc


def _record(model: PublishProfileCutoverModel) -> PublicationCutoverRecord:
    artifact_ids = tuple(int(value) for value in json.loads(model.artifact_ids_json))
    return PublicationCutoverRecord(
        request_key=model.request_key,
        streamer_id=model.streamer_id,
        source_profile_id=model.source_profile_id,
        target_profile_id=model.target_profile_id,
        source_profile_revision_id=model.source_profile_revision_id,
        target_profile_revision_id=model.target_profile_revision_id,
        source_route_id=model.source_route_id,
        target_route_id=model.target_route_id,
        publish_mode=model.publish_mode,
        environment=model.environment,
        schema_version=model.schema_version,
        artifact_ids=artifact_ids,
        operator_reason=model.operator_reason,
        id=model.id,
        status=cast(PublicationCutoverStatus, model.status),
        last_completed_step=cast(PublicationCutoverStep | None, model.last_completed_step),
        target_publication_id=model.target_publication_id,
        source_publication_id=model.source_publication_id,
        target_pointer_published_at=model.target_pointer_published_at,
        streamer_assigned_at=model.streamer_assigned_at,
        source_pointer_published_at=model.source_pointer_published_at,
        last_error_step=cast(PublicationCutoverStep | None, model.last_error_step),
        last_error_code=model.last_error_code,
        last_error_message=model.last_error_message,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _open_key(*, streamer_id: int, publish_mode: str, environment: str) -> str:
    return f"{streamer_id}:{publish_mode}:{environment}"
