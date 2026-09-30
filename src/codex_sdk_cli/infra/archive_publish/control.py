from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from codex_sdk_cli.domains.archive_publish.ports import ArchivePublishingControlPort
from codex_sdk_cli.infra.work.runtime_gate import publishing_enabled


class SqlAlchemyArchivePublishingControl(ArchivePublishingControlPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enabled(self) -> bool:
        return await publishing_enabled(self._session)
