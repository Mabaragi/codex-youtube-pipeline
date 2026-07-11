from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from codex_sdk_cli.api.dependencies import get_database_session_factory
from codex_sdk_cli.application.transcripts.commands import (
    CollectTranscriptsUseCase,
    GenerateTranscriptCuesUseCase,
)
from codex_sdk_cli.application.work.commands import (
    CancelWorkItemUseCase,
    RetryWorkItemUseCase,
)
from codex_sdk_cli.application.work.queries import (
    GetWorkItemUseCase,
    ListWorkItemsUseCase,
)
from codex_sdk_cli.bootstrap.operations import (
    cancel_work_item_use_case,
    collect_transcripts_use_case,
    generate_transcript_cues_use_case,
    get_work_item_use_case,
    list_work_items_use_case,
    retry_work_item_use_case,
)

DatabaseSessionFactoryDep = Annotated[
    async_sessionmaker[AsyncSession],
    Depends(get_database_session_factory),
]


def get_collect_transcripts_use_case(
    session_factory: DatabaseSessionFactoryDep,
) -> CollectTranscriptsUseCase:
    return collect_transcripts_use_case(session_factory)


def get_generate_transcript_cues_use_case(
    session_factory: DatabaseSessionFactoryDep,
) -> GenerateTranscriptCuesUseCase:
    return generate_transcript_cues_use_case(session_factory)


def get_list_work_items_use_case(
    session_factory: DatabaseSessionFactoryDep,
) -> ListWorkItemsUseCase:
    return list_work_items_use_case(session_factory)


def get_get_work_item_use_case(
    session_factory: DatabaseSessionFactoryDep,
) -> GetWorkItemUseCase:
    return get_work_item_use_case(session_factory)


def get_retry_work_item_use_case(
    session_factory: DatabaseSessionFactoryDep,
) -> RetryWorkItemUseCase:
    return retry_work_item_use_case(session_factory)


def get_cancel_work_item_use_case(
    session_factory: DatabaseSessionFactoryDep,
) -> CancelWorkItemUseCase:
    return cancel_work_item_use_case(session_factory)


CollectTranscriptsUseCaseDep = Annotated[
    CollectTranscriptsUseCase,
    Depends(get_collect_transcripts_use_case),
]
GenerateTranscriptCuesUseCaseDep = Annotated[
    GenerateTranscriptCuesUseCase,
    Depends(get_generate_transcript_cues_use_case),
]
ListWorkItemsUseCaseDep = Annotated[
    ListWorkItemsUseCase,
    Depends(get_list_work_items_use_case),
]
GetWorkItemUseCaseDep = Annotated[
    GetWorkItemUseCase,
    Depends(get_get_work_item_use_case),
]
RetryWorkItemUseCaseDep = Annotated[
    RetryWorkItemUseCase,
    Depends(get_retry_work_item_use_case),
]
CancelWorkItemUseCaseDep = Annotated[
    CancelWorkItemUseCase,
    Depends(get_cancel_work_item_use_case),
]
