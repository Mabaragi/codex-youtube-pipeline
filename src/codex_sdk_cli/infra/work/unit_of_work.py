from __future__ import annotations

from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from typing_extensions import override

from codex_sdk_cli.application.work.ports import WorkUnitOfWorkPort

from .batch_repository import SqlAlchemyWorkBatchRepository
from .item_repository import (
    SqlAlchemyWorkAttemptRepository,
    SqlAlchemyWorkItemRepository,
)
from .workflow_repository import SqlAlchemyWorkflowRepository


class SqlAlchemyWorkUnitOfWork(WorkUnitOfWorkPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None

    @override
    async def __aenter__(self) -> Self:
        if self._session is not None:
            raise RuntimeError("Unit of work is already active.")
        self._session = self._session_factory()
        self.work_items = SqlAlchemyWorkItemRepository(self._session)
        self.work_attempts = SqlAlchemyWorkAttemptRepository(self._session)
        self.work_batches = SqlAlchemyWorkBatchRepository(self._session)
        self.workflows = SqlAlchemyWorkflowRepository(self._session)
        return self

    @override
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        session = self._required_session()
        try:
            if exc_type is not None:
                await session.rollback()
        finally:
            await session.close()
            self._session = None

    @override
    async def commit(self) -> None:
        await self._required_session().commit()

    @override
    async def rollback(self) -> None:
        await self._required_session().rollback()

    def _required_session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("Unit of work has not been entered.")
        return self._session
