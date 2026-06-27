from __future__ import annotations

from .exceptions import DomainKnowledgeNotFound
from .ports import (
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
    DomainKnowledgeRepositoryPort,
)
from .schemas import (
    DeleteResponse,
    DomainEntryAliasCreateRequest,
    DomainEntryAliasResponse,
    DomainEntryAliasUpdateRequest,
    DomainEntryCreateRequest,
    DomainEntryListResponse,
    DomainEntryResponse,
    DomainEntryStreamerLinkRequest,
    DomainEntryStreamerResponse,
    DomainEntryTypeCreateRequest,
    DomainEntryTypeResponse,
    DomainEntryUpdateRequest,
)


class ListDomainEntryTypesUseCase:
    def __init__(self, repository: DomainKnowledgeRepositoryPort) -> None:
        self._repository = repository

    async def execute(self) -> list[DomainEntryTypeResponse]:
        return [_type_response(record) for record in await self._repository.list_types()]


class CreateDomainEntryTypeUseCase:
    def __init__(self, repository: DomainKnowledgeRepositoryPort) -> None:
        self._repository = repository

    async def execute(
        self,
        request: DomainEntryTypeCreateRequest,
    ) -> DomainEntryTypeResponse:
        record = await self._repository.create_type(_type_create(request))
        return _type_response(record)


class ListDomainEntriesUseCase:
    def __init__(self, repository: DomainKnowledgeRepositoryPort) -> None:
        self._repository = repository

    async def execute(
        self,
        *,
        streamer_id: int | None,
        type_id: int | None,
        q: str | None,
        active: bool | None,
        limit: int,
    ) -> DomainEntryListResponse:
        records = await self._repository.list_entries(
            DomainEntryListQuery(
                streamer_id=streamer_id,
                type_id=type_id,
                q=q,
                active=active,
                limit=limit,
            )
        )
        return DomainEntryListResponse(items=[_entry_response(record) for record in records])


class GetDomainEntryUseCase:
    def __init__(self, repository: DomainKnowledgeRepositoryPort) -> None:
        self._repository = repository

    async def execute(self, entry_id: int) -> DomainEntryResponse:
        record = await self._repository.get_entry(entry_id)
        if record is None:
            raise DomainKnowledgeNotFound("Domain entry not found.")
        return _entry_response(record)


class CreateDomainEntryUseCase:
    def __init__(self, repository: DomainKnowledgeRepositoryPort) -> None:
        self._repository = repository

    async def execute(self, request: DomainEntryCreateRequest) -> DomainEntryResponse:
        type_id = await self._resolve_type(request)
        record = await self._repository.create_entry(
            DomainEntryCreate(
                type_id=type_id,
                canonical_name=request.canonical_name,
                display_name=request.display_name,
                disambiguation=request.disambiguation,
                detail=request.detail,
                prompt_policy=request.prompt_policy,
                priority=request.priority,
                is_active=request.is_active,
                source_note=request.source_note,
                streamer_links=[
                    DomainEntryStreamerLinkCreate(streamer_id=streamer_id)
                    for streamer_id in sorted(set(request.streamer_ids))
                ],
                aliases=[_alias_create(alias) for alias in request.aliases],
            )
        )
        return _entry_response(record)

    async def _resolve_type(self, request: DomainEntryCreateRequest) -> int:
        if request.type_id is not None:
            record = await self._repository.get_type(request.type_id)
            if record is None:
                raise DomainKnowledgeNotFound("Domain entry type not found.")
            return record.id
        label = request.type_label or request.type_key
        assert label is not None
        record = await self._repository.get_or_create_type(
            DomainEntryTypeCreate(
                key=request.type_key,
                label=label,
            )
        )
        return record.id


class UpdateDomainEntryUseCase:
    def __init__(self, repository: DomainKnowledgeRepositoryPort) -> None:
        self._repository = repository

    async def execute(
        self,
        entry_id: int,
        request: DomainEntryUpdateRequest,
    ) -> DomainEntryResponse:
        type_id = await self._resolve_type(request)
        record = await self._repository.update_entry(
            entry_id,
            DomainEntryUpdate(
                type_id=type_id,
                canonical_name=request.canonical_name,
                display_name=request.display_name,
                display_name_set="display_name" in request.model_fields_set,
                disambiguation=request.disambiguation,
                disambiguation_set="disambiguation" in request.model_fields_set,
                detail=request.detail,
                detail_set="detail" in request.model_fields_set,
                prompt_policy=request.prompt_policy,
                priority=request.priority,
                is_active=request.is_active,
                source_note=request.source_note,
                source_note_set="source_note" in request.model_fields_set,
            ),
        )
        if record is None:
            raise DomainKnowledgeNotFound("Domain entry not found.")
        return _entry_response(record)

    async def _resolve_type(self, request: DomainEntryUpdateRequest) -> int | None:
        if request.type_id is not None:
            record = await self._repository.get_type(request.type_id)
            if record is None:
                raise DomainKnowledgeNotFound("Domain entry type not found.")
            return record.id
        if request.type_label is None and request.type_key is None:
            return None
        label = request.type_label or request.type_key
        assert label is not None
        record = await self._repository.get_or_create_type(
            DomainEntryTypeCreate(key=request.type_key, label=label)
        )
        return record.id


class ArchiveDomainEntryUseCase:
    def __init__(self, repository: DomainKnowledgeRepositoryPort) -> None:
        self._repository = repository

    async def execute(self, entry_id: int) -> DomainEntryResponse:
        record = await self._repository.archive_entry(entry_id)
        if record is None:
            raise DomainKnowledgeNotFound("Domain entry not found.")
        return _entry_response(record)


class AddDomainEntryStreamerUseCase:
    def __init__(self, repository: DomainKnowledgeRepositoryPort) -> None:
        self._repository = repository

    async def execute(
        self,
        entry_id: int,
        request: DomainEntryStreamerLinkRequest,
    ) -> DomainEntryResponse:
        record = await self._repository.add_streamer_link(
            entry_id,
            DomainEntryStreamerLinkCreate(
                streamer_id=request.streamer_id,
                relevance=request.relevance,
                note=request.note,
            ),
        )
        if record is None:
            raise DomainKnowledgeNotFound("Domain entry not found.")
        return _entry_response(record)


class RemoveDomainEntryStreamerUseCase:
    def __init__(self, repository: DomainKnowledgeRepositoryPort) -> None:
        self._repository = repository

    async def execute(self, entry_id: int, streamer_id: int) -> DeleteResponse:
        deleted = await self._repository.remove_streamer_link(entry_id, streamer_id)
        if not deleted:
            raise DomainKnowledgeNotFound("Domain entry streamer link not found.")
        return DeleteResponse(success=True)


class AddDomainEntryAliasUseCase:
    def __init__(self, repository: DomainKnowledgeRepositoryPort) -> None:
        self._repository = repository

    async def execute(
        self,
        entry_id: int,
        request: DomainEntryAliasCreateRequest,
    ) -> DomainEntryResponse:
        record = await self._repository.add_alias(entry_id, _alias_create(request))
        if record is None:
            raise DomainKnowledgeNotFound("Domain entry not found.")
        return _entry_response(record)


class UpdateDomainEntryAliasUseCase:
    def __init__(self, repository: DomainKnowledgeRepositoryPort) -> None:
        self._repository = repository

    async def execute(
        self,
        alias_id: int,
        request: DomainEntryAliasUpdateRequest,
    ) -> DomainEntryAliasResponse:
        record = await self._repository.update_alias(
            alias_id,
            DomainEntryAliasUpdate(
                surface_form=request.surface_form,
                alias_kind=request.alias_kind,
                certainty=request.certainty,
                apply_scope=request.apply_scope,
                language_code=request.language_code,
                language_code_set="language_code" in request.model_fields_set,
                note=request.note,
                note_set="note" in request.model_fields_set,
            ),
        )
        if record is None:
            raise DomainKnowledgeNotFound("Domain entry alias not found.")
        return _alias_response(record)


class DeleteDomainEntryAliasUseCase:
    def __init__(self, repository: DomainKnowledgeRepositoryPort) -> None:
        self._repository = repository

    async def execute(self, alias_id: int) -> DeleteResponse:
        deleted = await self._repository.delete_alias(alias_id)
        if not deleted:
            raise DomainKnowledgeNotFound("Domain entry alias not found.")
        return DeleteResponse(success=True)


def _type_create(request: DomainEntryTypeCreateRequest) -> DomainEntryTypeCreate:
    return DomainEntryTypeCreate(
        key=request.key,
        label=request.label,
        description=request.description,
        sort_order=request.sort_order,
        is_system=request.is_system,
    )


def _alias_create(request: DomainEntryAliasCreateRequest) -> DomainEntryAliasCreate:
    return DomainEntryAliasCreate(
        surface_form=request.surface_form,
        alias_kind=request.alias_kind,
        certainty=request.certainty,
        apply_scope=request.apply_scope,
        language_code=request.language_code,
        note=request.note,
    )


def _type_response(record: DomainEntryTypeRecord) -> DomainEntryTypeResponse:
    return DomainEntryTypeResponse(
        typeId=record.id,
        key=record.key,
        label=record.label,
        description=record.description,
        sortOrder=record.sort_order,
        isSystem=record.is_system,
        createdAt=record.created_at,
        updatedAt=record.updated_at,
    )


def _streamer_response(record: DomainEntryStreamerRecord) -> DomainEntryStreamerResponse:
    return DomainEntryStreamerResponse(
        streamerId=record.streamer_id,
        streamerName=record.streamer_name,
        relevance=record.relevance,
        note=record.note,
        createdAt=record.created_at,
    )


def _alias_response(record: DomainEntryAliasRecord) -> DomainEntryAliasResponse:
    return DomainEntryAliasResponse(
        aliasId=record.id,
        entryId=record.entry_id,
        surfaceForm=record.surface_form,
        aliasKind=record.alias_kind,
        certainty=record.certainty,
        applyScope=record.apply_scope,
        languageCode=record.language_code,
        note=record.note,
        createdAt=record.created_at,
        updatedAt=record.updated_at,
    )


def _entry_response(record: DomainEntryRecord) -> DomainEntryResponse:
    return DomainEntryResponse(
        entryId=record.id,
        typeId=record.type_id,
        typeKey=record.type_key,
        typeLabel=record.type_label,
        canonicalName=record.canonical_name,
        displayName=record.display_name,
        disambiguation=record.disambiguation,
        detail=record.detail,
        promptPolicy=record.prompt_policy,
        priority=record.priority,
        isActive=record.is_active,
        sourceNote=record.source_note,
        streamers=[_streamer_response(streamer) for streamer in record.streamers],
        aliases=[_alias_response(alias) for alias in record.aliases],
        createdAt=record.created_at,
        updatedAt=record.updated_at,
    )
