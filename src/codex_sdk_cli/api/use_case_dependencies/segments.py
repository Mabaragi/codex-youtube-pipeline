from typing import Annotated

from fastapi import Depends

from codex_sdk_cli.api.use_case_dependencies.work import DatabaseSessionFactoryDep
from codex_sdk_cli.application.segments.backfill import BackfillSegmentsUseCase
from codex_sdk_cli.application.segments.commands import ClassifySegmentsUseCase
from codex_sdk_cli.bootstrap.segments import backfill_segments_use_case, classify_segments_use_case


def get_classify_segments_use_case(sessions: DatabaseSessionFactoryDep) -> ClassifySegmentsUseCase:
    return classify_segments_use_case(sessions)


ClassifySegmentsUseCaseDep = Annotated[
    ClassifySegmentsUseCase, Depends(get_classify_segments_use_case)
]


def get_backfill_segments_use_case(sessions: DatabaseSessionFactoryDep) -> BackfillSegmentsUseCase:
    return backfill_segments_use_case(sessions)


BackfillSegmentsUseCaseDep = Annotated[
    BackfillSegmentsUseCase, Depends(get_backfill_segments_use_case)
]
