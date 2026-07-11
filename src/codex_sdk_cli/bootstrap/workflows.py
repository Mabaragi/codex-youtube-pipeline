from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from codex_sdk_cli.application.work.execution import WorkExecutionEngine, WorkExecutorRegistry
from codex_sdk_cli.application.workflows.archive import ArchivePublishExecutor
from codex_sdk_cli.application.workflows.commands import StartProcessToPublishUseCase
from codex_sdk_cli.application.workflows.publish import PublishArchivesUseCase
from codex_sdk_cli.infra.work.archive_execution import (
    InlineWorkExecutionRunner,
    WorkArchivePublisher,
)
from codex_sdk_cli.infra.work.execution_repositories import (
    WorkPipelineJobRepository,
    WorkVideoTaskRepository,
)
from codex_sdk_cli.infra.work.video_selection import SqlAlchemyVideoSelection
from codex_sdk_cli.settings import CliSettings

from .archive import archive_publish_use_case
from .operations import work_unit_of_work_factory


def start_process_to_publish_use_case(
    session_factory: async_sessionmaker[AsyncSession],
) -> StartProcessToPublishUseCase:
    return StartProcessToPublishUseCase(
        videos=SqlAlchemyVideoSelection(session_factory),
        unit_of_work_factory=work_unit_of_work_factory(session_factory),
    )


def publish_archives_use_case(
    session_factory: async_sessionmaker[AsyncSession],
    settings: CliSettings,
) -> PublishArchivesUseCase:
    unit_of_work = work_unit_of_work_factory(session_factory)
    engine = WorkExecutionEngine(
        unit_of_work_factory=unit_of_work,
        registry=WorkExecutorRegistry(
            {
                "archive_publish": lambda: ArchivePublishExecutor(
                    WorkArchivePublisher(
                        session_factory=session_factory,
                        use_case_factory=lambda session, work_item_id, work_attempt_id: (
                            archive_publish_use_case(
                                session,
                                settings,
                                video_tasks=WorkVideoTaskRepository(session),
                                pipeline_jobs=WorkPipelineJobRepository(
                                    session,
                                    current_work_item_id=work_item_id,
                                    current_work_attempt_id=work_attempt_id,
                                ),
                            )
                        ),
                    )
                )
            }
        ),
        task_types=("archive_publish",),
        worker_id="archive-publish:manual-api",
    )
    return PublishArchivesUseCase(
        videos=SqlAlchemyVideoSelection(session_factory),
        unit_of_work_factory=unit_of_work,
        inline_runner=InlineWorkExecutionRunner(engine),
    )
