from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from codex_sdk_cli.infra.database.session import ensure_sqlite_parent


def create_evaluation_engine(database_url: str, *, echo: bool = False) -> AsyncEngine:
    ensure_sqlite_parent(database_url)
    options: dict[str, object] = {"echo": echo}
    if database_url.startswith("postgresql"):
        options.update(pool_pre_ping=True, pool_size=3, max_overflow=2, pool_timeout=30)
    return create_async_engine(database_url, **options)


def create_evaluation_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
