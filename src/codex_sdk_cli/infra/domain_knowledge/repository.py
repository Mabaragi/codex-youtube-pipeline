from __future__ import annotations

import re
from datetime import datetime
from typing import cast

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    exists,
    func,
    or_,
    select,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from typing_extensions import override

from codex_sdk_cli.domains.domain_knowledge.exceptions import (
    DomainKnowledgeConflict,
    DomainKnowledgePersistenceError,
)
from codex_sdk_cli.domains.domain_knowledge.ports import (
    AliasKind,
    ApplyScope,
    Certainty,
    DomainEntryAliasCreate,
    DomainEntryAliasRecord,
    DomainEntryAliasUpdate,
    DomainEntryCreate,
    DomainEntryListQuery,
    DomainEntryRecord,
    DomainEntryStreamerLinkCreate,
    DomainEntryStreamerRecord,
    DomainEntryTypeCreate,
    DomainEntryTypeRecord,
    DomainEntryUpdate,
    DomainKnowledgePromptAliasRecord,
    DomainKnowledgePromptEntryRecord,
    DomainKnowledgeRepositoryPort,
    PromptPolicy,
)
from codex_sdk_cli.infra.database.base import Base
from codex_sdk_cli.infra.streamers.repository import StreamerModel


class DomainEntryTypeModel(Base):
    __tablename__ = "domain_entry_types"
    __table_args__ = (
        UniqueConstraint("key", name="uq_domain_entry_types_key"),
        UniqueConstraint(
            "label_normalized",
            name="uq_domain_entry_types_label_normalized",
        ),
        CheckConstraint("sort_order >= 0", name="domain_entry_types_sort_order_min"),
        Index("ix_domain_entry_types_sort", "sort_order", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    label_normalized: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
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


class DomainEntryModel(Base):
    __tablename__ = "domain_entries"
    __table_args__ = (
        CheckConstraint(
            "prompt_policy IN ('AUTO_ON_MATCH', 'ALWAYS_FOR_SCOPED_STREAMER', 'DISABLED')",
            name="domain_entries_prompt_policy_allowed",
        ),
        CheckConstraint("priority >= 0", name="domain_entries_priority_min"),
        Index("ix_domain_entries_type_active", "type_id", "is_active"),
        Index("ix_domain_entries_active_priority", "is_active", "priority"),
        Index("ix_domain_entries_canonical", "canonical_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type_id: Mapped[int] = mapped_column(
        ForeignKey("domain_entry_types.id", ondelete="RESTRICT"),
        nullable=False,
    )
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    disambiguation: Mapped[str | None] = mapped_column(String(500), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_policy: Mapped[str] = mapped_column(String(64), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
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


class DomainEntryStreamerModel(Base):
    __tablename__ = "domain_entry_streamers"
    __table_args__ = (
        UniqueConstraint(
            "entry_id",
            "streamer_id",
            name="uq_domain_entry_streamers_entry_streamer",
        ),
        Index("ix_domain_entry_streamers_streamer", "streamer_id", "entry_id"),
    )

    entry_id: Mapped[int] = mapped_column(
        ForeignKey("domain_entries.id", ondelete="CASCADE"),
        primary_key=True,
    )
    streamer_id: Mapped[int] = mapped_column(
        ForeignKey("streamers.id", ondelete="CASCADE"),
        primary_key=True,
    )
    relevance: Mapped[str | None] = mapped_column(String(255), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class DomainEntryAliasModel(Base):
    __tablename__ = "domain_entry_aliases"
    __table_args__ = (
        UniqueConstraint(
            "entry_id",
            "surface_form",
            "alias_kind",
            name="uq_domain_entry_aliases_entry_surface_kind",
        ),
        CheckConstraint(
            "alias_kind IN ('ALIAS', 'ASR_ERROR', 'SEARCH_ALIAS', "
            "'NICKNAME', 'WORDPLAY', 'MISSPELLING')",
            name="domain_entry_aliases_kind_allowed",
        ),
        CheckConstraint(
            "certainty IN ('LOW', 'MEDIUM', 'HIGH')",
            name="domain_entry_aliases_certainty_allowed",
        ),
        CheckConstraint(
            "apply_scope IN ('NONE', 'SEARCH_ONLY', 'SEARCH_AND_SUMMARY', "
            "'DISPLAY_ALLOWED')",
            name="domain_entry_aliases_apply_scope_allowed",
        ),
        Index("ix_domain_entry_aliases_entry", "entry_id"),
        Index("ix_domain_entry_aliases_surface", "surface_form"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entry_id: Mapped[int] = mapped_column(
        ForeignKey("domain_entries.id", ondelete="CASCADE"),
        nullable=False,
    )
    surface_form: Mapped[str] = mapped_column(String(255), nullable=False)
    alias_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    certainty: Mapped[str] = mapped_column(String(16), nullable=False)
    apply_scope: Mapped[str] = mapped_column(String(32), nullable=False)
    language_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
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


class SqlAlchemyDomainKnowledgeRepository(DomainKnowledgeRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def list_types(self) -> list[DomainEntryTypeRecord]:
        try:
            rows = await self._session.scalars(
                select(DomainEntryTypeModel).order_by(
                    DomainEntryTypeModel.sort_order,
                    DomainEntryTypeModel.id,
                )
            )
            return [_type_record(row) for row in rows]
        except SQLAlchemyError as exc:
            raise DomainKnowledgePersistenceError(
                "Domain knowledge persistence failed."
            ) from exc

    @override
    async def create_type(self, create: DomainEntryTypeCreate) -> DomainEntryTypeRecord:
        try:
            model = _type_model(create)
            self._session.add(model)
            await self._session.commit()
            await self._session.refresh(model)
            return _type_record(model)
        except IntegrityError as exc:
            await self._session.rollback()
            raise DomainKnowledgeConflict("Domain entry type already exists.") from exc
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise DomainKnowledgePersistenceError(
                "Domain knowledge persistence failed."
            ) from exc

    @override
    async def get_or_create_type(
        self,
        create: DomainEntryTypeCreate,
    ) -> DomainEntryTypeRecord:
        key = _normalized_key(create.key or create.label)
        label_normalized = _normalized_label(create.label)
        try:
            existing = await self._session.scalar(
                select(DomainEntryTypeModel).where(
                    or_(
                        DomainEntryTypeModel.key == key,
                        DomainEntryTypeModel.label_normalized == label_normalized,
                    )
                )
            )
            if existing is not None:
                return _type_record(existing)
            model = _type_model(create)
            self._session.add(model)
            await self._session.commit()
            await self._session.refresh(model)
            return _type_record(model)
        except IntegrityError as exc:
            await self._session.rollback()
            existing = await self._session.scalar(
                select(DomainEntryTypeModel).where(
                    or_(
                        DomainEntryTypeModel.key == key,
                        DomainEntryTypeModel.label_normalized == label_normalized,
                    )
                )
            )
            if existing is not None:
                return _type_record(existing)
            raise DomainKnowledgeConflict("Domain entry type already exists.") from exc
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise DomainKnowledgePersistenceError(
                "Domain knowledge persistence failed."
            ) from exc

    @override
    async def get_type(self, type_id: int) -> DomainEntryTypeRecord | None:
        try:
            model = await self._session.get(DomainEntryTypeModel, type_id)
            return _type_record(model) if model is not None else None
        except SQLAlchemyError as exc:
            raise DomainKnowledgePersistenceError(
                "Domain knowledge persistence failed."
            ) from exc

    @override
    async def list_entries(
        self,
        query: DomainEntryListQuery,
    ) -> list[DomainEntryRecord]:
        try:
            statement = select(DomainEntryModel)
            if query.active is not None:
                statement = statement.where(DomainEntryModel.is_active == query.active)
            if query.type_id is not None:
                statement = statement.where(DomainEntryModel.type_id == query.type_id)
            if query.streamer_id is not None:
                statement = statement.where(
                    or_(
                        exists().where(
                            DomainEntryStreamerModel.entry_id == DomainEntryModel.id,
                            DomainEntryStreamerModel.streamer_id == query.streamer_id,
                        ),
                        ~exists().where(
                            DomainEntryStreamerModel.entry_id == DomainEntryModel.id
                        ),
                    )
                )
            if query.q:
                pattern = f"%{query.q.strip()}%"
                statement = statement.where(
                    or_(
                        DomainEntryModel.canonical_name.ilike(pattern),
                        DomainEntryModel.display_name.ilike(pattern),
                        DomainEntryModel.detail.ilike(pattern),
                        exists().where(
                            DomainEntryAliasModel.entry_id == DomainEntryModel.id,
                            DomainEntryAliasModel.surface_form.ilike(pattern),
                        ),
                    )
                )
            rows = list(
                (
                    await self._session.scalars(
                        statement.order_by(
                            DomainEntryModel.is_active.desc(),
                            DomainEntryModel.priority.desc(),
                            DomainEntryModel.id.desc(),
                        ).limit(query.limit)
                    )
                ).all()
            )
            return [await self._entry_record(row) for row in rows]
        except SQLAlchemyError as exc:
            raise DomainKnowledgePersistenceError(
                "Domain knowledge persistence failed."
            ) from exc

    @override
    async def get_entry(self, entry_id: int) -> DomainEntryRecord | None:
        try:
            model = await self._session.get(DomainEntryModel, entry_id)
            if model is None:
                return None
            return await self._entry_record(model)
        except SQLAlchemyError as exc:
            raise DomainKnowledgePersistenceError(
                "Domain knowledge persistence failed."
            ) from exc

    @override
    async def create_entry(self, create: DomainEntryCreate) -> DomainEntryRecord:
        try:
            await self._ensure_streamers([link.streamer_id for link in create.streamer_links])
            model = DomainEntryModel(
                type_id=create.type_id,
                canonical_name=create.canonical_name,
                display_name=create.display_name,
                disambiguation=create.disambiguation,
                detail=create.detail,
                prompt_policy=create.prompt_policy,
                priority=create.priority,
                is_active=create.is_active,
                source_note=create.source_note,
            )
            self._session.add(model)
            await self._session.flush()
            for link in create.streamer_links:
                self._session.add(_streamer_model(model.id, link))
            for alias in create.aliases:
                self._session.add(_alias_model(model.id, alias))
            await self._session.commit()
            record = await self.get_entry(model.id)
            assert record is not None
            return record
        except IntegrityError as exc:
            await self._session.rollback()
            raise DomainKnowledgeConflict("Domain entry conflicts with existing data.") from exc
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise DomainKnowledgePersistenceError(
                "Domain knowledge persistence failed."
            ) from exc

    @override
    async def update_entry(
        self,
        entry_id: int,
        update: DomainEntryUpdate,
    ) -> DomainEntryRecord | None:
        try:
            model = await self._session.get(DomainEntryModel, entry_id)
            if model is None:
                return None
            if update.type_id is not None:
                model.type_id = update.type_id
            if update.canonical_name is not None:
                model.canonical_name = update.canonical_name
            if update.display_name_set:
                model.display_name = update.display_name
            if update.disambiguation_set:
                model.disambiguation = update.disambiguation
            if update.detail_set:
                model.detail = update.detail
            if update.prompt_policy is not None:
                model.prompt_policy = update.prompt_policy
            if update.priority is not None:
                model.priority = update.priority
            if update.is_active is not None:
                model.is_active = update.is_active
            if update.source_note_set:
                model.source_note = update.source_note
            await self._session.commit()
            await self._session.refresh(model)
            record = await self.get_entry(entry_id)
            assert record is not None
            return record
        except IntegrityError as exc:
            await self._session.rollback()
            raise DomainKnowledgeConflict("Domain entry conflicts with existing data.") from exc
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise DomainKnowledgePersistenceError(
                "Domain knowledge persistence failed."
            ) from exc

    @override
    async def archive_entry(self, entry_id: int) -> DomainEntryRecord | None:
        return await self.update_entry(
            entry_id,
            DomainEntryUpdate(is_active=False),
        )

    @override
    async def add_streamer_link(
        self,
        entry_id: int,
        link: DomainEntryStreamerLinkCreate,
    ) -> DomainEntryRecord | None:
        try:
            model = await self._session.get(DomainEntryModel, entry_id)
            if model is None:
                return None
            await self._ensure_streamers([link.streamer_id])
            existing = await self._session.get(
                DomainEntryStreamerModel,
                {"entry_id": entry_id, "streamer_id": link.streamer_id},
            )
            if existing is None:
                self._session.add(_streamer_model(entry_id, link))
            else:
                existing.relevance = link.relevance
                existing.note = link.note
            await self._session.commit()
            record = await self.get_entry(entry_id)
            assert record is not None
            return record
        except IntegrityError as exc:
            await self._session.rollback()
            raise DomainKnowledgeConflict("Domain entry streamer link conflicts.") from exc
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise DomainKnowledgePersistenceError(
                "Domain knowledge persistence failed."
            ) from exc

    @override
    async def remove_streamer_link(self, entry_id: int, streamer_id: int) -> bool:
        try:
            model = await self._session.get(
                DomainEntryStreamerModel,
                {"entry_id": entry_id, "streamer_id": streamer_id},
            )
            if model is None:
                return False
            await self._session.delete(model)
            await self._session.commit()
            return True
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise DomainKnowledgePersistenceError(
                "Domain knowledge persistence failed."
            ) from exc

    @override
    async def add_alias(
        self,
        entry_id: int,
        alias: DomainEntryAliasCreate,
    ) -> DomainEntryRecord | None:
        try:
            model = await self._session.get(DomainEntryModel, entry_id)
            if model is None:
                return None
            self._session.add(_alias_model(entry_id, alias))
            await self._session.commit()
            record = await self.get_entry(entry_id)
            assert record is not None
            return record
        except IntegrityError as exc:
            await self._session.rollback()
            raise DomainKnowledgeConflict("Domain entry alias already exists.") from exc
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise DomainKnowledgePersistenceError(
                "Domain knowledge persistence failed."
            ) from exc

    @override
    async def update_alias(
        self,
        alias_id: int,
        update: DomainEntryAliasUpdate,
    ) -> DomainEntryAliasRecord | None:
        try:
            model = await self._session.get(DomainEntryAliasModel, alias_id)
            if model is None:
                return None
            if update.surface_form is not None:
                model.surface_form = update.surface_form
            if update.alias_kind is not None:
                model.alias_kind = update.alias_kind
            if update.certainty is not None:
                model.certainty = update.certainty
            if update.apply_scope is not None:
                model.apply_scope = update.apply_scope
            if update.language_code_set:
                model.language_code = update.language_code
            if update.note_set:
                model.note = update.note
            await self._session.commit()
            await self._session.refresh(model)
            return _alias_record(model)
        except IntegrityError as exc:
            await self._session.rollback()
            raise DomainKnowledgeConflict("Domain entry alias already exists.") from exc
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise DomainKnowledgePersistenceError(
                "Domain knowledge persistence failed."
            ) from exc

    @override
    async def delete_alias(self, alias_id: int) -> bool:
        try:
            model = await self._session.get(DomainEntryAliasModel, alias_id)
            if model is None:
                return False
            await self._session.delete(model)
            await self._session.commit()
            return True
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise DomainKnowledgePersistenceError(
                "Domain knowledge persistence failed."
            ) from exc

    @override
    async def list_prompt_entries_for_streamer(
        self,
        streamer_id: int | None,
    ) -> list[DomainKnowledgePromptEntryRecord]:
        query = DomainEntryListQuery(streamer_id=streamer_id, active=True, limit=500)
        entries = await self.list_entries(query)
        return [
            DomainKnowledgePromptEntryRecord(
                entry_id=entry.id,
                type_key=entry.type_key,
                type_label=entry.type_label,
                canonical_name=entry.canonical_name,
                display_name=entry.display_name,
                disambiguation=entry.disambiguation,
                detail=entry.detail,
                prompt_policy=entry.prompt_policy,
                priority=entry.priority,
                aliases=[
                    DomainKnowledgePromptAliasRecord(
                        surface_form=alias.surface_form,
                        alias_kind=alias.alias_kind,
                        certainty=alias.certainty,
                        apply_scope=alias.apply_scope,
                        language_code=alias.language_code,
                        note=alias.note,
                    )
                    for alias in entry.aliases
                ],
            )
            for entry in entries
            if entry.prompt_policy != "DISABLED"
        ]

    async def _entry_record(self, model: DomainEntryModel) -> DomainEntryRecord:
        type_model = await self._session.get(DomainEntryTypeModel, model.type_id)
        assert type_model is not None
        streamer_rows = (
            await self._session.execute(
                select(DomainEntryStreamerModel, StreamerModel)
                .join(StreamerModel, StreamerModel.id == DomainEntryStreamerModel.streamer_id)
                .where(DomainEntryStreamerModel.entry_id == model.id)
                .order_by(StreamerModel.name, StreamerModel.id)
            )
        ).all()
        aliases = list(
            (
                await self._session.scalars(
                    select(DomainEntryAliasModel)
                    .where(DomainEntryAliasModel.entry_id == model.id)
                    .order_by(DomainEntryAliasModel.id)
                )
            ).all()
        )
        return DomainEntryRecord(
            id=model.id,
            type_id=model.type_id,
            type_key=type_model.key,
            type_label=type_model.label,
            canonical_name=model.canonical_name,
            display_name=model.display_name,
            disambiguation=model.disambiguation,
            detail=model.detail,
            prompt_policy=cast(PromptPolicy, model.prompt_policy),
            priority=model.priority,
            is_active=model.is_active,
            source_note=model.source_note,
            created_at=model.created_at,
            updated_at=model.updated_at,
            streamers=[
                DomainEntryStreamerRecord(
                    streamer_id=link.streamer_id,
                    streamer_name=streamer.name,
                    relevance=link.relevance,
                    note=link.note,
                    created_at=link.created_at,
                )
                for link, streamer in streamer_rows
            ],
            aliases=[_alias_record(alias) for alias in aliases],
        )

    async def _ensure_streamers(self, streamer_ids: list[int]) -> None:
        unique_ids = sorted(set(streamer_ids))
        if not unique_ids:
            return
        rows = await self._session.scalars(
            select(StreamerModel.id).where(StreamerModel.id.in_(unique_ids))
        )
        found = set(rows.all())
        if found != set(unique_ids):
            raise DomainKnowledgeConflict("One or more streamers do not exist.")


def _type_model(create: DomainEntryTypeCreate) -> DomainEntryTypeModel:
    key = _normalized_key(create.key or create.label)
    return DomainEntryTypeModel(
        key=key,
        label=create.label,
        label_normalized=_normalized_label(create.label),
        description=create.description,
        sort_order=create.sort_order,
        is_system=create.is_system,
    )


def _streamer_model(
    entry_id: int,
    link: DomainEntryStreamerLinkCreate,
) -> DomainEntryStreamerModel:
    return DomainEntryStreamerModel(
        entry_id=entry_id,
        streamer_id=link.streamer_id,
        relevance=link.relevance,
        note=link.note,
    )


def _alias_model(entry_id: int, alias: DomainEntryAliasCreate) -> DomainEntryAliasModel:
    return DomainEntryAliasModel(
        entry_id=entry_id,
        surface_form=alias.surface_form,
        alias_kind=alias.alias_kind,
        certainty=alias.certainty,
        apply_scope=alias.apply_scope,
        language_code=alias.language_code,
        note=alias.note,
    )


def _type_record(model: DomainEntryTypeModel) -> DomainEntryTypeRecord:
    return DomainEntryTypeRecord(
        id=model.id,
        key=model.key,
        label=model.label,
        description=model.description,
        sort_order=model.sort_order,
        is_system=model.is_system,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _alias_record(model: DomainEntryAliasModel) -> DomainEntryAliasRecord:
    return DomainEntryAliasRecord(
        id=model.id,
        entry_id=model.entry_id,
        surface_form=model.surface_form,
        alias_kind=cast(AliasKind, model.alias_kind),
        certainty=cast(Certainty, model.certainty),
        apply_scope=cast(ApplyScope, model.apply_scope),
        language_code=model.language_code,
        note=model.note,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _normalized_key(value: str) -> str:
    lowered = value.strip().lower()
    key = re.sub(r"[^\w-]+", "-", lowered, flags=re.UNICODE)
    key = re.sub(r"_+", "-", key).strip("-")
    return key or "type"


def _normalized_label(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())
