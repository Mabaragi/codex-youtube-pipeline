from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from codex_sdk_cli.infra.database.session import ensure_sqlite_parent

_CATALOG_DATABASE_NAME = "codex_public_catalog"


def create_catalog_engine(database_url: str, *, echo: bool = False) -> AsyncEngine:
    ensure_sqlite_parent(database_url)
    url = make_url(database_url)
    options: dict[str, object] = {"echo": echo}
    if url.drivername.startswith("postgresql"):
        options.update(pool_pre_ping=True, pool_size=5, max_overflow=10, pool_timeout=30)
    return create_async_engine(database_url, **options)


def create_catalog_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def ensure_catalog_database(
    database_url: str,
    *,
    expected_database_name: str = _CATALOG_DATABASE_NAME,
) -> bool:
    """Create the dedicated PostgreSQL database when absent.

    Returns True only when this call created the database. SQLite needs no
    provisioning and returns False. Schema creation remains Alembic-owned.
    """
    target_url = make_url(database_url)
    if not target_url.drivername.startswith("postgresql"):
        return False
    if target_url.database != expected_database_name:
        raise ValueError(f"Catalog database URL must target '{expected_database_name}'.")
    admin_url = _admin_database_url(target_url)
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            exists = await connection.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :database_name"),
                {"database_name": expected_database_name},
            )
            if exists:
                return False
            quoted_name = connection.dialect.identifier_preparer.quote(expected_database_name)
            await connection.execute(text(f"CREATE DATABASE {quoted_name}"))
            return True
    finally:
        await engine.dispose()


def _admin_database_url(target_url: URL) -> URL:
    return target_url.set(database="postgres")
