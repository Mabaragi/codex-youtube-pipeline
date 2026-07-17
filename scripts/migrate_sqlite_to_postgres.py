from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Boolean, DateTime
from sqlalchemy.engine import make_url

import codex_sdk_cli.infra.database.models  # noqa: F401
from codex_sdk_cli.infra.database.base import Base

Batch = list[tuple[object, ...]]
Converter = Callable[[object], object]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Copy a contracted SQLite database into an Alembic-initialized PostgreSQL DB."
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target-url", required=True)
    parser.add_argument("--batch-size", type=int, default=5_000)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--allow-foreign-key-debt", action="store_true")
    args = parser.parse_args()
    if args.batch_size < 1:
        parser.error("--batch-size must be at least 1")
    asyncio.run(
        migrate(
            source=args.source.resolve(),
            target_url=args.target_url,
            batch_size=args.batch_size,
            replace=args.replace,
            allow_foreign_key_debt=args.allow_foreign_key_debt,
        )
    )


async def migrate(
    *,
    source: Path,
    target_url: str,
    batch_size: int,
    replace: bool,
    allow_foreign_key_debt: bool = False,
) -> None:
    _require_source(source)
    dsn = _postgres_dsn(target_url)
    sqlite_connection = sqlite3.connect(source)
    sqlite_connection.row_factory = sqlite3.Row
    postgres_connection: asyncpg.Connection | None = None
    try:
        metadata_tables = {table.name: table for table in Base.metadata.sorted_tables}
        source_tables, source_fk_violations = _validate_source(
            sqlite_connection,
            metadata_tables,
            allow_foreign_key_debt=allow_foreign_key_debt,
        )

        postgres_connection = await asyncpg.connect(dsn)
        revision = await postgres_connection.fetchval("SELECT version_num FROM alembic_version")
        expected_revision = _expected_alembic_head()
        if revision != expected_revision:
            raise RuntimeError(f"PostgreSQL is not at the expected Alembic head: {revision}")
        target_tables = {
            row["tablename"]
            for row in await postgres_connection.fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            )
        }
        copy_names = sorted(
            source_tables.intersection(target_tables).difference({"alembic_version"})
        )
        if not copy_names:
            raise RuntimeError("No application tables were found to copy.")

        existing_rows = 0
        for name in copy_names:
            existing_rows += _required_int(
                await postgres_connection.fetchval(
                    f"SELECT COUNT(*) FROM {_quote(name)}"
                )
            )
        if existing_rows and not replace:
            raise RuntimeError(
                "PostgreSQL already contains application rows; pass --replace to rebuild it."
            )

        copied_counts: dict[str, int] = {}
        async with postgres_connection.transaction():
            await postgres_connection.execute("SET LOCAL session_replication_role = replica")
            if replace:
                targets = ", ".join(
                    _quote(name)
                    for name in sorted(target_tables.difference({"alembic_version"}))
                )
                await postgres_connection.execute(f"TRUNCATE TABLE {targets} CASCADE")

            for name in copy_names:
                table = metadata_tables[name]
                columns = [column.name for column in table.columns]
                converters = [_converter(column.type) for column in table.columns]
                copied = await _copy_table(
                    sqlite_connection=sqlite_connection,
                    postgres_connection=postgres_connection,
                    table_name=name,
                    columns=columns,
                    converters=converters,
                    batch_size=batch_size,
                )
                copied_counts[name] = copied
                print(f"copied {name}: {copied}", flush=True)

            await _reset_sequences(postgres_connection, copy_names, metadata_tables)
            await _verify_counts(sqlite_connection, postgres_connection, copied_counts)

        print(
            json.dumps(
                {
                    "source": str(source),
                    "tableCount": len(copied_counts),
                    "rowCount": sum(copied_counts.values()),
                    "sourceForeignKeyViolationCount": source_fk_violations,
                    "alembicRevision": revision,
                },
                ensure_ascii=True,
            ),
            flush=True,
        )
    finally:
        sqlite_connection.close()
        if postgres_connection is not None:
            await postgres_connection.close()


async def _copy_table(
    *,
    sqlite_connection: sqlite3.Connection,
    postgres_connection: asyncpg.Connection,
    table_name: str,
    columns: list[str],
    converters: list[Converter],
    batch_size: int,
) -> int:
    selected_columns = ", ".join(_quote(column) for column in columns)
    cursor = sqlite_connection.execute(
        f"SELECT {selected_columns} FROM {_quote(table_name)}"
    )
    copied = 0
    while rows := cursor.fetchmany(batch_size):
        batch: Batch = [
            tuple(converter(row[index]) for index, converter in enumerate(converters))
            for row in rows
        ]
        await postgres_connection.copy_records_to_table(
            table_name,
            records=batch,
            columns=columns,
        )
        copied += len(batch)
    return copied


async def _verify_counts(
    sqlite_connection: sqlite3.Connection,
    postgres_connection: asyncpg.Connection,
    copied_counts: dict[str, int],
) -> None:
    mismatches: list[str] = []
    for table_name, copied in copied_counts.items():
        source_count = int(
            sqlite_connection.execute(
                f"SELECT COUNT(*) FROM {_quote(table_name)}"
            ).fetchone()[0]
        )
        target_count = _required_int(
            await postgres_connection.fetchval(
                f"SELECT COUNT(*) FROM {_quote(table_name)}"
            )
        )
        if source_count != copied or target_count != copied:
            mismatches.append(
                f"{table_name}: source={source_count}, copied={copied}, target={target_count}"
            )
    if mismatches:
        raise RuntimeError("Row-count verification failed: " + "; ".join(mismatches))


async def _reset_sequences(
    connection: asyncpg.Connection,
    table_names: Sequence[str],
    metadata_tables: dict[str, Any],
) -> None:
    for table_name in table_names:
        table = metadata_tables[table_name]
        for column in table.primary_key.columns:
            if not column.autoincrement:
                continue
            sequence_name = await connection.fetchval(
                "SELECT pg_get_serial_sequence($1, $2)", table_name, column.name
            )
            if sequence_name is None:
                continue
            maximum = await connection.fetchval(
                f"SELECT MAX({_quote(column.name)}) FROM {_quote(table_name)}"
            )
            if maximum is None:
                await connection.execute("SELECT setval($1::regclass, 1, false)", sequence_name)
            else:
                await connection.execute(
                    "SELECT setval($1::regclass, $2, true)", sequence_name, maximum
                )


def _source_tables(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }


def _require_source(source: Path) -> None:
    if not source.is_file():
        raise SystemExit(f"SQLite source does not exist: {source}")


def _validate_source(
    connection: sqlite3.Connection,
    metadata_tables: dict[str, Any],
    *,
    allow_foreign_key_debt: bool = False,
) -> tuple[set[str], int]:
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        raise RuntimeError(f"SQLite integrity check failed: {integrity}")
    foreign_key_violations = len(connection.execute("PRAGMA foreign_key_check").fetchall())
    if foreign_key_violations and not allow_foreign_key_debt:
        raise RuntimeError(
            "SQLite foreign-key validation failed: "
            f"{foreign_key_violations} violation(s). "
            "Use --allow-foreign-key-debt only for an explicit forensic migration."
        )
    tables = _source_tables(connection)
    unknown_tables = tables.difference(metadata_tables).difference({"alembic_version"})
    if unknown_tables:
        raise RuntimeError(
            f"SQLite has tables missing from SQLAlchemy metadata: {sorted(unknown_tables)}"
        )
    return tables, foreign_key_violations


def _converter(column_type: object) -> Converter:
    if isinstance(column_type, Boolean):
        return _boolean
    if isinstance(column_type, DateTime):
        return lambda value: _datetime(value, timezone=column_type.timezone)
    return _identity


def _boolean(value: object) -> object:
    return None if value is None else bool(value)


def _datetime(value: object, *, timezone: bool) -> object:
    if value is None or isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise TypeError(f"Unsupported datetime value: {value!r}")
    if parsed is None:
        return None
    if timezone and parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    if not timezone and parsed.tzinfo is not None:
        return parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def _identity(value: object) -> object:
    return value


def _required_int(value: object | None) -> int:
    if not isinstance(value, int):
        raise RuntimeError("Expected an integer database result.")
    return value


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _postgres_dsn(database_url: str) -> str:
    url = make_url(database_url)
    if not url.drivername.startswith("postgresql"):
        raise ValueError("Target URL must use PostgreSQL.")
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


def _expected_alembic_head() -> str:
    repository_root = Path(__file__).resolve().parents[1]
    config = Config(str(repository_root / "alembic.ini"))
    config.set_main_option("script_location", str(repository_root / "alembic"))
    revision = ScriptDirectory.from_config(config).get_current_head()
    if revision is None:
        raise RuntimeError("Alembic does not define a current head revision.")
    return revision


if __name__ == "__main__":
    main()
