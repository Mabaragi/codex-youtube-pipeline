from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from codex_sdk_cli.application.workflows.commands import StartProcessToPublishUseCase
from codex_sdk_cli.infra.work.video_selection import SqlAlchemyVideoSelection

from .operations import work_unit_of_work_factory


def start_process_to_publish_use_case(
    session_factory: async_sessionmaker[AsyncSession],
) -> StartProcessToPublishUseCase:
    return StartProcessToPublishUseCase(
        videos=SqlAlchemyVideoSelection(session_factory),
        unit_of_work_factory=work_unit_of_work_factory(session_factory),
    )
