from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from codex_sdk_cli.api.dependencies import DatabaseSessionDep, SettingsDep
from codex_sdk_cli.bootstrap.archive import archive_publish_use_case
from codex_sdk_cli.domains.archive_publish.use_cases import ArchivePublishUseCase


def get_archive_publish_use_case(
    session: DatabaseSessionDep,
    settings: SettingsDep,
) -> ArchivePublishUseCase:
    return archive_publish_use_case(session, settings)


ArchivePublishUseCaseDep = Annotated[
    ArchivePublishUseCase,
    Depends(get_archive_publish_use_case),
]

__all__ = [
    "ArchivePublishUseCaseDep",
    "get_archive_publish_use_case",
]
