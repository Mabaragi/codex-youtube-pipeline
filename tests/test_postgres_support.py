from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pytest
from sqlalchemy.dialects import postgresql

from codex_sdk_cli.infra.publication_config.repository import (
    _profile_for_activation_statement,
)
from codex_sdk_cli.infra.work.item_repository import _claim_candidate_query
from codex_sdk_cli.infra.work.runtime_gate import _runtime_state_statement
from codex_sdk_cli.infra.youtube_transcripts.repository import (
    _find_transcript_metadata_statement,
)
from scripts.migrate_sqlite_to_postgres import (
    _datetime,
    _expected_alembic_head,
    _postgres_dsn,
    _validate_source,
)


def test_postgres_claim_uses_skip_locked() -> None:
    statement = _claim_candidate_query(
        task_types=("micro_event_extract",),
        now=datetime(2026, 7, 12, tzinfo=UTC),
    ).with_for_update(skip_locked=True)

    compiled = str(statement.compile(dialect=postgresql.dialect()))

    assert "FOR UPDATE SKIP LOCKED" in compiled


def test_publish_profile_activation_locks_the_profile_row() -> None:
    compiled = str(
        _profile_for_activation_statement(7).compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "publish_profiles.id = 7" in compiled
    assert compiled.endswith("FOR UPDATE")


def test_postgres_runtime_gate_holds_state_until_claim_commits() -> None:
    compiled = str(_runtime_state_statement("postgresql"))

    assert compiled.endswith("FOR SHARE")
    assert "FOR SHARE" not in str(_runtime_state_statement("sqlite"))


def test_postgres_transcript_lookup_does_not_compare_json() -> None:
    statement = _find_transcript_metadata_statement(
        video_id="abcdefghijk",
        preserve_formatting=False,
    )

    compiled = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    where_clause = compiled.partition("\nWHERE ")[2].partition(" ORDER BY ")[0]
    assert "requested_languages" not in where_clause
    assert "video_id = 'abcdefghijk'" in where_clause
    assert "preserve_formatting = false" in where_clause


def test_postgres_migration_normalizes_dsn_and_timestamp() -> None:
    assert (
        _postgres_dsn("postgresql+asyncpg://codex:secret@127.0.0.1:5432/codex")
        == "postgresql://codex:secret@127.0.0.1:5432/codex"
    )
    assert _datetime("2026-07-12T00:00:00", timezone=True) == datetime(2026, 7, 12, tzinfo=UTC)
    assert _expected_alembic_head() == "20260718_0034"


def test_sqlite_migration_blocks_foreign_key_debt_unless_explicit() -> None:
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("CREATE TABLE parents(id INTEGER PRIMARY KEY)")
        connection.execute(
            "CREATE TABLE children("
            "id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parents(id))"
        )
        connection.execute("INSERT INTO children(id, parent_id) VALUES (1, 999)")
        metadata = {"parents": object(), "children": object()}

        with pytest.raises(RuntimeError, match="foreign-key validation failed"):
            _validate_source(connection, metadata)

        tables, violation_count = _validate_source(
            connection,
            metadata,
            allow_foreign_key_debt=True,
        )
        assert tables == {"parents", "children"}
        assert violation_count == 1
    finally:
        connection.close()
