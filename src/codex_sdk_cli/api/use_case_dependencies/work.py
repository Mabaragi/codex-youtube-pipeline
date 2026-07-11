from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from codex_sdk_cli.api.dependencies import SettingsDep, get_database_session_factory
from codex_sdk_cli.application.channels.commands import ResolveChannelUseCase
from codex_sdk_cli.application.processing.commands import (
    ComposeTimelinesUseCase,
    ExtractMicroEventsUseCase,
)
from codex_sdk_cli.application.transcripts.commands import (
    CollectTranscriptsUseCase,
    GenerateTranscriptCuesUseCase,
)
from codex_sdk_cli.application.videos.commands import CollectVideosUseCase
from codex_sdk_cli.application.work.commands import (
    CancelWorkItemUseCase,
    RetryWorkItemUseCase,
)
from codex_sdk_cli.application.work.queries import (
    GetWorkBatchUseCase,
    GetWorkflowRunUseCase,
    GetWorkItemUseCase,
    ListWorkItemsUseCase,
)
from codex_sdk_cli.application.workflows.commands import StartProcessToPublishUseCase
from codex_sdk_cli.application.workflows.publish import PublishArchivesUseCase
from codex_sdk_cli.bootstrap.operations import (
    cancel_work_item_use_case,
    collect_transcripts_use_case,
    collect_videos_use_case,
    compose_timelines_use_case,
    extract_micro_events_use_case,
    generate_transcript_cues_use_case,
    get_work_batch_use_case,
    get_work_item_use_case,
    get_workflow_run_use_case,
    list_work_items_use_case,
    resolve_channel_use_case,
    retry_work_item_use_case,
)
from codex_sdk_cli.bootstrap.workflows import (
    publish_archives_use_case,
    start_process_to_publish_use_case,
)

DatabaseSessionFactoryDep = Annotated[
    async_sessionmaker[AsyncSession],
    Depends(get_database_session_factory),
]


def get_collect_transcripts_use_case(
    session_factory: DatabaseSessionFactoryDep,
) -> CollectTranscriptsUseCase:
    return collect_transcripts_use_case(session_factory)


def get_collect_videos_use_case(
    session_factory: DatabaseSessionFactoryDep,
    settings: SettingsDep,
) -> CollectVideosUseCase:
    return collect_videos_use_case(session_factory, settings)


def get_resolve_channel_use_case(
    session_factory: DatabaseSessionFactoryDep,
    settings: SettingsDep,
) -> ResolveChannelUseCase:
    return resolve_channel_use_case(session_factory, settings)


def get_generate_transcript_cues_use_case(
    session_factory: DatabaseSessionFactoryDep,
) -> GenerateTranscriptCuesUseCase:
    return generate_transcript_cues_use_case(session_factory)


def get_extract_micro_events_use_case(
    session_factory: DatabaseSessionFactoryDep,
) -> ExtractMicroEventsUseCase:
    return extract_micro_events_use_case(session_factory)


def get_compose_timelines_use_case(
    session_factory: DatabaseSessionFactoryDep,
) -> ComposeTimelinesUseCase:
    return compose_timelines_use_case(session_factory)


def get_list_work_items_use_case(
    session_factory: DatabaseSessionFactoryDep,
) -> ListWorkItemsUseCase:
    return list_work_items_use_case(session_factory)


def get_get_work_item_use_case(
    session_factory: DatabaseSessionFactoryDep,
) -> GetWorkItemUseCase:
    return get_work_item_use_case(session_factory)


def get_get_work_batch_use_case(
    session_factory: DatabaseSessionFactoryDep,
) -> GetWorkBatchUseCase:
    return get_work_batch_use_case(session_factory)


def get_get_workflow_run_use_case(
    session_factory: DatabaseSessionFactoryDep,
) -> GetWorkflowRunUseCase:
    return get_workflow_run_use_case(session_factory)


def get_retry_work_item_use_case(
    session_factory: DatabaseSessionFactoryDep,
) -> RetryWorkItemUseCase:
    return retry_work_item_use_case(session_factory)


def get_cancel_work_item_use_case(
    session_factory: DatabaseSessionFactoryDep,
) -> CancelWorkItemUseCase:
    return cancel_work_item_use_case(session_factory)


def get_start_process_to_publish_use_case(
    session_factory: DatabaseSessionFactoryDep,
) -> StartProcessToPublishUseCase:
    return start_process_to_publish_use_case(session_factory)


def get_publish_archives_use_case(
    session_factory: DatabaseSessionFactoryDep,
    settings: SettingsDep,
) -> PublishArchivesUseCase:
    return publish_archives_use_case(session_factory, settings)


CollectTranscriptsUseCaseDep = Annotated[
    CollectTranscriptsUseCase,
    Depends(get_collect_transcripts_use_case),
]
CollectVideosUseCaseDep = Annotated[
    CollectVideosUseCase,
    Depends(get_collect_videos_use_case),
]
ResolveChannelUseCaseDep = Annotated[
    ResolveChannelUseCase,
    Depends(get_resolve_channel_use_case),
]
GenerateTranscriptCuesUseCaseDep = Annotated[
    GenerateTranscriptCuesUseCase,
    Depends(get_generate_transcript_cues_use_case),
]
ExtractMicroEventsUseCaseDep = Annotated[
    ExtractMicroEventsUseCase,
    Depends(get_extract_micro_events_use_case),
]
ComposeTimelinesUseCaseDep = Annotated[
    ComposeTimelinesUseCase,
    Depends(get_compose_timelines_use_case),
]
ListWorkItemsUseCaseDep = Annotated[
    ListWorkItemsUseCase,
    Depends(get_list_work_items_use_case),
]
GetWorkItemUseCaseDep = Annotated[
    GetWorkItemUseCase,
    Depends(get_get_work_item_use_case),
]
GetWorkBatchUseCaseDep = Annotated[
    GetWorkBatchUseCase,
    Depends(get_get_work_batch_use_case),
]
GetWorkflowRunUseCaseDep = Annotated[
    GetWorkflowRunUseCase,
    Depends(get_get_workflow_run_use_case),
]
RetryWorkItemUseCaseDep = Annotated[
    RetryWorkItemUseCase,
    Depends(get_retry_work_item_use_case),
]
CancelWorkItemUseCaseDep = Annotated[
    CancelWorkItemUseCase,
    Depends(get_cancel_work_item_use_case),
]
StartProcessToPublishUseCaseDep = Annotated[
    StartProcessToPublishUseCase,
    Depends(get_start_process_to_publish_use_case),
]
PublishArchivesUseCaseDep = Annotated[
    PublishArchivesUseCase,
    Depends(get_publish_archives_use_case),
]
