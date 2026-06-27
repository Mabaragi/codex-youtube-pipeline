from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Query, status

from codex_sdk_cli.api.use_case_dependencies.domain_knowledge import (
    AddDomainEntryAliasUseCaseDep,
    AddDomainEntryStreamerUseCaseDep,
    ArchiveDomainEntryUseCaseDep,
    CreateDomainEntryTypeUseCaseDep,
    CreateDomainEntryUseCaseDep,
    DeleteDomainEntryAliasUseCaseDep,
    GetDomainEntryUseCaseDep,
    ListDomainEntriesUseCaseDep,
    ListDomainEntryTypesUseCaseDep,
    RemoveDomainEntryStreamerUseCaseDep,
    UpdateDomainEntryAliasUseCaseDep,
    UpdateDomainEntryUseCaseDep,
)
from codex_sdk_cli.domains.domain_knowledge.schemas import (
    DeleteResponse,
    DomainEntryAliasCreateRequest,
    DomainEntryAliasResponse,
    DomainEntryAliasUpdateRequest,
    DomainEntryCreateRequest,
    DomainEntryListResponse,
    DomainEntryResponse,
    DomainEntryStreamerLinkRequest,
    DomainEntryTypeCreateRequest,
    DomainEntryTypeResponse,
    DomainEntryUpdateRequest,
)

router = APIRouter()


@router.get("/domain-entry-types", response_model=list[DomainEntryTypeResponse])
async def list_domain_entry_types(
    use_case: ListDomainEntryTypesUseCaseDep,
) -> list[DomainEntryTypeResponse]:
    return await use_case.execute()


@router.post(
    "/domain-entry-types",
    response_model=DomainEntryTypeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_domain_entry_type(
    request: DomainEntryTypeCreateRequest,
    use_case: CreateDomainEntryTypeUseCaseDep,
) -> DomainEntryTypeResponse:
    return await use_case.execute(request)


@router.get("/domain-entries", response_model=DomainEntryListResponse)
async def list_domain_entries(
    use_case: ListDomainEntriesUseCaseDep,
    streamer_id: Annotated[int | None, Query(alias="streamerId", ge=1)] = None,
    type_id: Annotated[int | None, Query(alias="typeId", ge=1)] = None,
    q: Annotated[str | None, Query(min_length=1)] = None,
    active: Annotated[bool | None, Query()] = True,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> DomainEntryListResponse:
    return await use_case.execute(
        streamer_id=streamer_id,
        type_id=type_id,
        q=q,
        active=active,
        limit=limit,
    )


@router.post(
    "/domain-entries",
    response_model=DomainEntryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_domain_entry(
    request: DomainEntryCreateRequest,
    use_case: CreateDomainEntryUseCaseDep,
) -> DomainEntryResponse:
    return await use_case.execute(request)


@router.get("/domain-entries/{entry_id}", response_model=DomainEntryResponse)
async def get_domain_entry(
    entry_id: Annotated[int, Path(ge=1)],
    use_case: GetDomainEntryUseCaseDep,
) -> DomainEntryResponse:
    return await use_case.execute(entry_id)


@router.patch("/domain-entries/{entry_id}", response_model=DomainEntryResponse)
async def update_domain_entry(
    entry_id: Annotated[int, Path(ge=1)],
    request: DomainEntryUpdateRequest,
    use_case: UpdateDomainEntryUseCaseDep,
) -> DomainEntryResponse:
    return await use_case.execute(entry_id, request)


@router.delete("/domain-entries/{entry_id}", response_model=DomainEntryResponse)
async def archive_domain_entry(
    entry_id: Annotated[int, Path(ge=1)],
    use_case: ArchiveDomainEntryUseCaseDep,
) -> DomainEntryResponse:
    return await use_case.execute(entry_id)


@router.post(
    "/domain-entries/{entry_id}/streamers",
    response_model=DomainEntryResponse,
)
async def add_domain_entry_streamer(
    entry_id: Annotated[int, Path(ge=1)],
    request: DomainEntryStreamerLinkRequest,
    use_case: AddDomainEntryStreamerUseCaseDep,
) -> DomainEntryResponse:
    return await use_case.execute(entry_id, request)


@router.delete(
    "/domain-entries/{entry_id}/streamers/{streamer_id}",
    response_model=DeleteResponse,
)
async def remove_domain_entry_streamer(
    entry_id: Annotated[int, Path(ge=1)],
    streamer_id: Annotated[int, Path(ge=1)],
    use_case: RemoveDomainEntryStreamerUseCaseDep,
) -> DeleteResponse:
    return await use_case.execute(entry_id, streamer_id)


@router.post(
    "/domain-entries/{entry_id}/aliases",
    response_model=DomainEntryResponse,
)
async def add_domain_entry_alias(
    entry_id: Annotated[int, Path(ge=1)],
    request: DomainEntryAliasCreateRequest,
    use_case: AddDomainEntryAliasUseCaseDep,
) -> DomainEntryResponse:
    return await use_case.execute(entry_id, request)


@router.patch(
    "/domain-entry-aliases/{alias_id}",
    response_model=DomainEntryAliasResponse,
)
async def update_domain_entry_alias(
    alias_id: Annotated[int, Path(ge=1)],
    request: DomainEntryAliasUpdateRequest,
    use_case: UpdateDomainEntryAliasUseCaseDep,
) -> DomainEntryAliasResponse:
    return await use_case.execute(alias_id, request)


@router.delete("/domain-entry-aliases/{alias_id}", response_model=DeleteResponse)
async def delete_domain_entry_alias(
    alias_id: Annotated[int, Path(ge=1)],
    use_case: DeleteDomainEntryAliasUseCaseDep,
) -> DeleteResponse:
    return await use_case.execute(alias_id)
