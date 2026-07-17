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
    _register_database_models()
    ensure_sqlite_parent(database_url)
    url = make_url(database_url)
    options: dict[str, object] = {"echo": echo}
    if url.drivername.startswith("postgresql"):
        options.update(
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
            pool_timeout=30,
        )
    return create_async_engine(database_url, **options)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def ensure_sqlite_parent(database_url: str) -> None:
    url = make_url(database_url)
    if not url.drivername.startswith("sqlite"):
        return
    if url.database in {None, "", ":memory:"}:
        return

    Path(url.database).parent.mkdir(parents=True, exist_ok=True)


def _register_database_models() -> None:
    # SQLAlchemy resolves string-based foreign keys from the shared metadata at flush time.
    from codex_sdk_cli.infra.database import models

    if not models.__all__:
        raise RuntimeError("Database model registry is empty.")
