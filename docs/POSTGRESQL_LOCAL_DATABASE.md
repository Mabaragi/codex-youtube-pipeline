# PostgreSQL Local Database

The Home PC runtime uses Docker PostgreSQL for application state. FastAPI,
workers, scheduler, coordinator, and Ops UI remain native Windows processes.
MinIO remains a separate Docker service.

## Why PostgreSQL

SQLite serializes writers at the database-file level. Six micro-event slots plus
transcript, cue, timeline, scheduler, and coordinator writers can collide during
claim, heartbeat, attempt creation, and completion. Staggered startup reduces
the chance but cannot guarantee correctness.

PostgreSQL provides concurrent row-level writes. `work_items` claims use
`SELECT ... FOR UPDATE SKIP LOCKED` inside the Unit of Work transaction, so each
slot skips rows already being claimed by another transaction.

## Runtime Configuration

Private `.home-deploy/local.env` values:

```text
POSTGRES_DB=codex
POSTGRES_USER=codex
POSTGRES_PASSWORD=<random local secret>
POSTGRES_PORT=5432
CODEX_CLI_DATABASE_URL=postgresql+asyncpg://codex:<secret>@127.0.0.1:5432/codex
```

Do not commit this file. `status.ps1` masks the URL password.

The Compose service uses `postgres:17-alpine`, publishes only localhost port
5432, has a readiness health check, and persists data in
`codex-sdk-home_postgres-data`. `docker compose down` preserves the volume;
only an explicit volume deletion destroys it.

## SQLite Migration

After setting PostgreSQL credentials, run once:

```powershell
.\scripts\local-home\migrate-sqlite-to-postgres.ps1
```

The migration is offline with respect to application writers. It:

1. stops native API and worker processes;
2. checkpoints SQLite and creates `data/app.pre-postgres.<timestamp>.db`;
3. starts healthy PostgreSQL and runs `alembic upgrade head`;
4. truncates only the target PostgreSQL application tables;
5. copies all SQLite physical tables in one PostgreSQL transaction;
6. verifies source/copied/target row counts and resets identity sequences;
7. restarts the local runtime.

Compatibility views are created by Alembic and are not copied as tables.
The migration stops before connecting to PostgreSQL when
`PRAGMA foreign_key_check` reports any source violation. For an explicit
forensic copy only, pass `--allow-foreign-key-debt` to the Python migration
tool; the final summary then includes `sourceForeignKeyViolationCount`.
The source database and backup are never deleted.

## Operations

```powershell
.\scripts\local-home\start.ps1
.\scripts\local-home\status.ps1
.\scripts\local-home\stop.ps1
.\scripts\local-home\stop.ps1 -StopInfra
```

`deploy.ps1` starts PostgreSQL before Alembic. Unit tests continue to use
isolated SQLite databases for speed; PostgreSQL-specific claim SQL has a static
test and is smoke-tested against the local container during migration.

## Recovery

If PostgreSQL cannot start, inspect:

```powershell
docker compose --project-name codex-sdk-home -f compose.local-infra.yaml ps postgres
docker compose --project-name codex-sdk-home -f compose.local-infra.yaml logs postgres
```

Keep the named volume and `.home-deploy/local.env` together because the volume
was initialized with that database user/password. To return temporarily to the
preserved SQLite source, stop all native processes, use the matching pre-change
checkout, and point `CODEX_CLI_DATABASE_URL` at the retained SQLite file.
