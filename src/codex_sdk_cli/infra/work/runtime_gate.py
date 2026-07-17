from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import TextClause

from codex_sdk_cli.application.work.errors import WorkPersistenceError


async def runtime_accepting_work(session: AsyncSession) -> bool:
    statement = _runtime_state_statement(session.get_bind().dialect.name)
    try:
        runtime_state = (await session.execute(statement)).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise WorkPersistenceError() from exc
    return runtime_state in {None, "active"}


def _runtime_state_statement(dialect_name: str) -> TextClause:
    statement = "SELECT runtime_state FROM pipeline_automation_state WHERE id = 1"
    if dialect_name == "postgresql":
        statement += " FOR SHARE"
    return text(statement)
