from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from codex_sdk_cli.application.transcripts.commands import (
    CollectTranscriptsUseCase,
    GenerateTranscriptCuesUseCase,
)
from codex_sdk_cli.application.work.commands import (
    CancelWorkItemUseCase,
    RetryWorkItemUseCase,
)
from codex_sdk_cli.application.work.execution import WorkUnitOfWorkFactory
from codex_sdk_cli.application.work.queries import (
    GetWorkItemUseCase,
    ListWorkItemsUseCase,
)
from codex_sdk_cli.infra.work.transcript_execution import YouTubeTranscriptMetadataReader
from codex_sdk_cli.infra.work.unit_of_work import SqlAlchemyWorkUnitOfWork
from codex_sdk_cli.infra.work.video_selection import SqlAlchemyVideoSelection


def work_unit_of_work_factory(
    session_factory: async_sessionmaker[AsyncSession],
) -> WorkUnitOfWorkFactory:
    def create() -> SqlAlchemyWorkUnitOfWork:
        return SqlAlchemyWorkUnitOfWork(session_factory)

    return create


def collect_transcripts_use_case(
    session_factory: async_sessionmaker[AsyncSession],
) -> CollectTranscriptsUseCase:
    return CollectTranscriptsUseCase(
        videos=SqlAlchemyVideoSelection(session_factory),
        unit_of_work_factory=work_unit_of_work_factory(session_factory),
    )


def generate_transcript_cues_use_case(
    session_factory: async_sessionmaker[AsyncSession],
) -> GenerateTranscriptCuesUseCase:
    return GenerateTranscriptCuesUseCase(
        videos=SqlAlchemyVideoSelection(session_factory),
        transcripts=YouTubeTranscriptMetadataReader(session_factory),
        unit_of_work_factory=work_unit_of_work_factory(session_factory),
    )


def list_work_items_use_case(
    session_factory: async_sessionmaker[AsyncSession],
) -> ListWorkItemsUseCase:
    return ListWorkItemsUseCase(work_unit_of_work_factory(session_factory))


def get_work_item_use_case(
    session_factory: async_sessionmaker[AsyncSession],
) -> GetWorkItemUseCase:
    return GetWorkItemUseCase(work_unit_of_work_factory(session_factory))


def retry_work_item_use_case(
    session_factory: async_sessionmaker[AsyncSession],
) -> RetryWorkItemUseCase:
    return RetryWorkItemUseCase(work_unit_of_work_factory(session_factory))


def cancel_work_item_use_case(
    session_factory: async_sessionmaker[AsyncSession],
) -> CancelWorkItemUseCase:
    return CancelWorkItemUseCase(work_unit_of_work_factory(session_factory))
