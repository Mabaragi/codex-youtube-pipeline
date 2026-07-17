# PostgreSQL for Concurrent Workers

## Rule

Do not operate multiple DB-polling worker processes or slots against the local
SQLite production database. SQLite's file-level writer serialization makes
claim, heartbeat, attempt creation, and completion contend even when worker
startup is staggered.

Use the Docker PostgreSQL service for the Home PC runtime. Keep SQLite only for
isolated tests and retained migration backups. Claim pending `work_items` with
`FOR UPDATE SKIP LOCKED` inside the same Unit of Work transaction that changes
the row to `running`.

## Verification

- PostgreSQL Compose health check passes before native processes start.
- Six concurrent claim transactions return six distinct work item IDs.
- SQLite-to-PostgreSQL migration verifies every copied table's row count before
  commit and resets all generated sequences.
- Runtime status never prints the database password.

The executable procedure lives in `docs/POSTGRESQL_LOCAL_DATABASE.md` and
`scripts/local-home/migrate-sqlite-to-postgres.ps1`.
