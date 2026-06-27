from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from codex_sdk_cli.api.dependencies import DomainKnowledgeRepositoryDep
from codex_sdk_cli.domains.domain_knowledge.use_cases import (
    AddDomainEntryAliasUseCase,
    AddDomainEntryStreamerUseCase,
    ArchiveDomainEntryUseCase,
    CreateDomainEntryTypeUseCase,
    CreateDomainEntryUseCase,
    DeleteDomainEntryAliasUseCase,
    GetDomainEntryUseCase,
    ListDomainEntriesUseCase,
    ListDomainEntryTypesUseCase,
    RemoveDomainEntryStreamerUseCase,
    UpdateDomainEntryAliasUseCase,
    UpdateDomainEntryUseCase,
)


def get_list_domain_entry_types_use_case(
    repository: DomainKnowledgeRepositoryDep,
) -> ListDomainEntryTypesUseCase:
    return ListDomainEntryTypesUseCase(repository)


def get_create_domain_entry_type_use_case(
    repository: DomainKnowledgeRepositoryDep,
) -> CreateDomainEntryTypeUseCase:
    return CreateDomainEntryTypeUseCase(repository)


def get_list_domain_entries_use_case(
    repository: DomainKnowledgeRepositoryDep,
) -> ListDomainEntriesUseCase:
    return ListDomainEntriesUseCase(repository)


def get_get_domain_entry_use_case(
    repository: DomainKnowledgeRepositoryDep,
) -> GetDomainEntryUseCase:
    return GetDomainEntryUseCase(repository)


def get_create_domain_entry_use_case(
    repository: DomainKnowledgeRepositoryDep,
) -> CreateDomainEntryUseCase:
    return CreateDomainEntryUseCase(repository)


def get_update_domain_entry_use_case(
    repository: DomainKnowledgeRepositoryDep,
) -> UpdateDomainEntryUseCase:
    return UpdateDomainEntryUseCase(repository)


def get_archive_domain_entry_use_case(
    repository: DomainKnowledgeRepositoryDep,
) -> ArchiveDomainEntryUseCase:
    return ArchiveDomainEntryUseCase(repository)


def get_add_domain_entry_streamer_use_case(
    repository: DomainKnowledgeRepositoryDep,
) -> AddDomainEntryStreamerUseCase:
    return AddDomainEntryStreamerUseCase(repository)


def get_remove_domain_entry_streamer_use_case(
    repository: DomainKnowledgeRepositoryDep,
) -> RemoveDomainEntryStreamerUseCase:
    return RemoveDomainEntryStreamerUseCase(repository)


def get_add_domain_entry_alias_use_case(
    repository: DomainKnowledgeRepositoryDep,
) -> AddDomainEntryAliasUseCase:
    return AddDomainEntryAliasUseCase(repository)


def get_update_domain_entry_alias_use_case(
    repository: DomainKnowledgeRepositoryDep,
) -> UpdateDomainEntryAliasUseCase:
    return UpdateDomainEntryAliasUseCase(repository)


def get_delete_domain_entry_alias_use_case(
    repository: DomainKnowledgeRepositoryDep,
) -> DeleteDomainEntryAliasUseCase:
    return DeleteDomainEntryAliasUseCase(repository)


ListDomainEntryTypesUseCaseDep = Annotated[
    ListDomainEntryTypesUseCase,
    Depends(get_list_domain_entry_types_use_case),
]
CreateDomainEntryTypeUseCaseDep = Annotated[
    CreateDomainEntryTypeUseCase,
    Depends(get_create_domain_entry_type_use_case),
]
ListDomainEntriesUseCaseDep = Annotated[
    ListDomainEntriesUseCase,
    Depends(get_list_domain_entries_use_case),
]
GetDomainEntryUseCaseDep = Annotated[
    GetDomainEntryUseCase,
    Depends(get_get_domain_entry_use_case),
]
CreateDomainEntryUseCaseDep = Annotated[
    CreateDomainEntryUseCase,
    Depends(get_create_domain_entry_use_case),
]
UpdateDomainEntryUseCaseDep = Annotated[
    UpdateDomainEntryUseCase,
    Depends(get_update_domain_entry_use_case),
]
ArchiveDomainEntryUseCaseDep = Annotated[
    ArchiveDomainEntryUseCase,
    Depends(get_archive_domain_entry_use_case),
]
AddDomainEntryStreamerUseCaseDep = Annotated[
    AddDomainEntryStreamerUseCase,
    Depends(get_add_domain_entry_streamer_use_case),
]
RemoveDomainEntryStreamerUseCaseDep = Annotated[
    RemoveDomainEntryStreamerUseCase,
    Depends(get_remove_domain_entry_streamer_use_case),
]
AddDomainEntryAliasUseCaseDep = Annotated[
    AddDomainEntryAliasUseCase,
    Depends(get_add_domain_entry_alias_use_case),
]
UpdateDomainEntryAliasUseCaseDep = Annotated[
    UpdateDomainEntryAliasUseCase,
    Depends(get_update_domain_entry_alias_use_case),
]
DeleteDomainEntryAliasUseCaseDep = Annotated[
    DeleteDomainEntryAliasUseCase,
    Depends(get_delete_domain_entry_alias_use_case),
]
