from __future__ import annotations

from pathlib import Path

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_database_engine(database_url: str, *, echo: bool = False) -> AsyncEngine:
    ensure_sqlite_parent(database_url)
    return create_async_engine(database_url, echo=echo)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def ensure_sqlite_parent(database_url: str) -> None:
    url = make_url(database_url)
    if not url.drivername.startswith("sqlite"):
        return
    if url.database in {None, "", ":memory:"}:
        return

    Path(url.database).parent.mkdir(parents=True, exist_ok=True)
