from __future__ import annotations

from datetime import UTC, datetime
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

from codex_sdk_cli.domains.prompts.constants import PromptKey, PromptStatus
from codex_sdk_cli.domains.prompts.exceptions import (
    PromptConflict,
    PromptPersistenceError,
)
from codex_sdk_cli.domains.prompts.ports import (
    PromptRepositoryPort,
    PromptVersionCreate,
    PromptVersionRecord,
    PromptVersionUpdate,
)
from codex_sdk_cli.infra.database.base import Base


class PromptVersionModel(Base):
    __tablename__ = "prompt_versions"
    __table_args__ = (
        UniqueConstraint(
            "prompt_key",
            "version_label",
            name="uq_prompt_versions_key_label",
        ),
        CheckConstraint(
            "status IN ('DRAFT', 'PUBLISHED', 'ARCHIVED')",
            name="prompt_versions_status_allowed",
        ),
        Index("ix_prompt_versions_key_status", "prompt_key", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    prompt_key: Mapped[str] = mapped_column(String(128), nullable=False)
    version_label: Mapped[str] = mapped_column(String(128), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    body_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    source_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class PromptActiveVersionModel(Base):
    __tablename__ = "prompt_active_versions"

    prompt_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    version_id: Mapped[int] = mapped_column(
        ForeignKey("prompt_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SqlAlchemyPromptRepository(PromptRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def list_versions(self, prompt_key: PromptKey) -> list[PromptVersionRecord]:
        result = await self._session.scalars(
            select(PromptVersionModel)
            .where(PromptVersionModel.prompt_key == prompt_key)
            .order_by(PromptVersionModel.id.desc())
        )
        return [_record(model) for model in result.all()]

    @override
    async def get_version(
        self,
        prompt_key: PromptKey,
        version_id: int,
    ) -> PromptVersionRecord | None:
        model = await self._get_model(prompt_key, version_id)
        return _record(model) if model is not None else None

    @override
    async def get_active_version(
        self,
        prompt_key: PromptKey,
    ) -> PromptVersionRecord | None:
        result = await self._session.execute(
            select(PromptVersionModel)
            .join(
                PromptActiveVersionModel,
                PromptActiveVersionModel.version_id == PromptVersionModel.id,
            )
            .where(PromptActiveVersionModel.prompt_key == prompt_key)
        )
        model = result.scalar_one_or_none()
        return _record(model) if model is not None else None

    @override
    async def create_version(
        self,
        create: PromptVersionCreate,
    ) -> PromptVersionRecord:
        model = PromptVersionModel(
            prompt_key=create.prompt_key,
            version_label=create.version_label,
            body=create.body,
            body_sha256=create.body_sha256,
            status="DRAFT",
            source_note=create.source_note,
        )
        self._session.add(model)
        try:
            await self._session.flush()
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise PromptConflict("Prompt version already exists.") from exc
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise PromptPersistenceError("Prompt persistence failed.") from exc
        record = await self.get_version(create.prompt_key, model.id)
        assert record is not None
        return record

    @override
    async def update_draft(
        self,
        prompt_key: PromptKey,
        version_id: int,
        update: PromptVersionUpdate,
    ) -> PromptVersionRecord | None:
        model = await self._get_model(prompt_key, version_id)
        if model is None:
            return None
        if model.status != "DRAFT":
            raise PromptConflict("Only draft prompt versions can be updated.")
        if update.body_set:
            if update.body is None or update.body_sha256 is None:
                raise PromptConflict("Prompt body update is incomplete.")
            model.body = update.body
            model.body_sha256 = update.body_sha256
        if update.source_note_set:
            model.source_note = update.source_note
        try:
            await self._session.commit()
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise PromptPersistenceError("Prompt persistence failed.") from exc
        return await self.get_version(prompt_key, version_id)

    @override
    async def publish_version(
        self,
        prompt_key: PromptKey,
        version_id: int,
    ) -> PromptVersionRecord | None:
        model = await self._get_model(prompt_key, version_id)
        if model is None:
            return None
        if model.status == "ARCHIVED":
            raise PromptConflict("Archived prompt versions cannot be published.")
        now = datetime.now(UTC)
        if model.status == "DRAFT":
            model.status = "PUBLISHED"
            model.published_at = now
        active = await self._session.get(PromptActiveVersionModel, prompt_key)
        if active is None:
            self._session.add(
                PromptActiveVersionModel(prompt_key=prompt_key, version_id=model.id)
            )
        else:
            active.version_id = model.id
            active.updated_at = now
        try:
            await self._session.commit()
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise PromptPersistenceError("Prompt persistence failed.") from exc
        return await self.get_version(prompt_key, version_id)

    @override
    async def archive_version(
        self,
        prompt_key: PromptKey,
        version_id: int,
    ) -> PromptVersionRecord | None:
        model = await self._get_model(prompt_key, version_id)
        if model is None:
            return None
        active = await self._session.get(PromptActiveVersionModel, prompt_key)
        if active is not None and active.version_id == model.id:
            raise PromptConflict("Active prompt version cannot be archived.")
        if model.status != "ARCHIVED":
            model.status = "ARCHIVED"
            model.archived_at = datetime.now(UTC)
        try:
            await self._session.commit()
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise PromptPersistenceError("Prompt persistence failed.") from exc
        return await self.get_version(prompt_key, version_id)

    async def _get_model(
        self,
        prompt_key: PromptKey,
        version_id: int,
    ) -> PromptVersionModel | None:
        return await self._session.scalar(
            select(PromptVersionModel).where(
                PromptVersionModel.id == version_id,
                PromptVersionModel.prompt_key == prompt_key,
            )
        )


def _record(model: PromptVersionModel) -> PromptVersionRecord:
    return PromptVersionRecord(
        id=model.id,
        prompt_key=cast(PromptKey, model.prompt_key),
        version_label=model.version_label,
        body=model.body,
        body_sha256=model.body_sha256,
        status=cast(PromptStatus, model.status),
        source_note=model.source_note,
        created_at=model.created_at,
        updated_at=model.updated_at,
        published_at=model.published_at,
        archived_at=model.archived_at,
    )
