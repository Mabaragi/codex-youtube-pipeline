# Local Native Home PC Deployment

This is the current Home PC runtime path.

The app no longer depends on ngrok, Nginx, GHCR image pulls, or GitHub Actions
deployment. Docker is kept for PostgreSQL and MinIO. The API, workers, and
optional Ops UI run as Windows processes from this checkout.

## Runtime Topology

```text
Windows process: codex-api / uvicorn on 127.0.0.1:8000
Windows process: codex-pipeline-scheduler
Windows process: codex-transcript-worker
Windows process: codex-transcript-cue-worker
Windows process: codex-asr-worker
Windows process: codex-micro-event-worker
Windows process: codex-timeline-compose-worker
Windows process: codex-workflow-coordinator
Windows process: codex-pipeline-supervisor
Windows process: Next.js ops-ui on 127.0.0.1:3000
Docker container: MinIO on 127.0.0.1:9000 and console on 127.0.0.1:9001
Docker container: PostgreSQL on 127.0.0.1:5432
Database volume: codex-sdk-home_postgres-data
Runtime state: ./.home-deploy/
```

There is no public URL. Remote operation should be done by an agent running on
this PC and calling `http://127.0.0.1:8000`.

## One-Time Setup

Install Docker, Git, and Node LTS:

```powershell
winget install --id Docker.DockerDesktop --exact
winget install --id Git.Git --exact
winget install --id OpenJS.NodeJS.LTS --exact
```

Install Python 3.11 or later and `uv` before deployment. `deploy.ps1` starts
with `uv sync --dev --locked` and then runs Alembic, so it cannot bootstrap a
machine that has only Docker and Node. Confirm the tools are available before
continuing:

```powershell
uv --version
uv run python --version
```

Create local env:

```powershell
New-Item -ItemType Directory -Force .home-deploy | Out-Null
Copy-Item scripts/local-home/local.env.example .home-deploy/local.env
notepad .home-deploy/local.env
```

Keep `.home-deploy/local.env` private. It contains the PostgreSQL password and
may contain API keys and local MinIO credentials. Replace every `CHANGE_ME`
value before the first start.

`codex-pipeline-scheduler` starts by default and needs
`CODEX_CLI_YOUTUBE_DATA_API_KEY` to collect channel/video metadata. Set the key
in `.home-deploy/local.env`, or set `CODEX_CLI_PIPELINE_SCHEDULER_ENABLED=false`
when this machine should not run automatic collection. Without either choice,
the scheduler process stays alive but logs a failed tick every poll interval.

### Optional ASR Prerequisites

ASR workflows and `codex-demo asr transcribe` need `yt-dlp`, `ffmpeg`, and
`ffprobe`. Put
the executables on `PATH` or set `CODEX_CLI_YTDLP_BIN`, `CODEX_CLI_FFMPEG_BIN`,
and `CODEX_CLI_FFPROBE_BIN` in the private local env. The automated runtime
starts `asr-worker` with GPU concurrency one and `pipeline-supervisor` with a
60-second incident scan interval. These tools are not needed when automatic
ASR fallback is disabled.

If the previous Docker home stack has the metadata DB, copy it once:

```powershell
.\scripts\local-home\migrate-db-from-docker-volume.ps1
```

The script copies `codex-sdk-home_db-data:/app.db` into `.\data\app.db` only
when a local DB is not already present. Use `-Force` only after checking the
backup it creates in `.\data`.

## Deploy

Run the local deploy from the repo root:

```powershell
.\scripts\local-home\deploy.ps1
```

This performs:

- `uv sync --dev --locked`
- `pnpm install --frozen-lockfile`
- local API, scheduler, worker, and Ops UI process cleanup, including stale child processes
  that may keep `.next/standalone` locked
- PostgreSQL and MinIO start through `compose.local-infra.yaml`
- Docker-volume DB migration if needed
- `uv run alembic upgrade head`
- `pnpm -C ops-ui build`
- local API, worker, and Ops UI process start

For a faster backend-only deploy:

```powershell
.\scripts\local-home\deploy.ps1 -NoUi -SkipUiBuild
```

## Start, Stop, Status

After the first deploy, use idempotent start:

```powershell
.\scripts\local-home\start.ps1
```

`start.ps1` starts PostgreSQL and MinIO, then native app processes. The native app
processes are API, pipeline scheduler, transcript worker, cue worker,
ASR worker, micro-event worker, timeline worker, workflow coordinator,
pipeline supervisor, and optionally Ops UI.

Check status:

```powershell
.\scripts\local-home\status.ps1
.\scripts\local-home\runtime.ps1 status -Json
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-WebRequest http://127.0.0.1:3000/ops -UseBasicParsing
```

Drain without stopping processes:

```powershell
.\scripts\local-home\runtime.ps1 drain
.\scripts\local-home\runtime.ps1 resume
```

Stop app processes safely:

```powershell
.\scripts\local-home\stop.ps1
```

`stop.ps1` delegates to `runtime.ps1 stop`: it blocks new scheduler, workflow,
worker, and inline claims, waits up to 30 minutes for running work, persists the
`stopped` state, then removes PID-managed processes and stale local runtime
children. A timeout leaves processes running in `draining`; it never escalates
to a forced stop automatically. Use `runtime.ps1 stop -Force` only when lease
and checkpoint recovery is acceptable. A forced stop remains draining on the
next start until an explicit `runtime.ps1 resume`.

See [Drain-based local runtime orchestration](learnings/topics/drain-based-local-runtime-orchestration.md)
for the design rationale and failure semantics behind these rules.

Stop app processes and Docker infrastructure:

```powershell
.\scripts\local-home\stop.ps1 -StopInfra
.\scripts\local-home\runtime.ps1 restart
```

Read logs:

```powershell
.\scripts\local-home\logs.ps1
.\scripts\local-home\logs.ps1 api -Tail 200
.\scripts\local-home\logs.ps1 pipeline-scheduler -Tail 200
.\scripts\local-home\logs.ps1 transcript-worker -Tail 200
.\scripts\local-home\logs.ps1 workflow-coordinator -Tail 200
.\scripts\local-home\logs.ps1 timeline-compose-worker -Wait
```

Logs and PID files live under `.home-deploy/logs` and `.home-deploy/pids`.

## Reboot Recovery

Register the local runtime with Windows Task Scheduler:

```powershell
.\scripts\local-home\register-task.ps1
```

The task runs the idempotent runtime start at logon and then repeats every 5
minutes. It starts only missing processes and never changes a persisted
`draining` or `stopped` state back to `active`.

To register without Ops UI:

```powershell
.\scripts\local-home\register-task.ps1 -NoUi
```

## MinIO

The local MinIO compose file publishes:

- API: `http://127.0.0.1:9000`
- Console: `http://127.0.0.1:9001`

The compose project name remains `codex-sdk-home`, so the existing
`codex-sdk-home_minio-data` volume is reused.

The app defaults are:

```text
CODEX_CLI_TRANSCRIPT_MINIO_ENDPOINT=127.0.0.1:9000
CODEX_CLI_TRANSCRIPT_MINIO_BUCKET=raw
CODEX_CLI_TRANSCRIPT_MINIO_PREFIX=youtube/transcripts
CODEX_CLI_EXTERNAL_API_CALL_MINIO_PREFIX=external-api-calls
```

## PostgreSQL

PostgreSQL uses `postgres:17-alpine`, binds only to `127.0.0.1:5432`, and stores
data in the `codex-sdk-home_postgres-data` named volume. All API, scheduler,
worker, and coordinator processes share the asyncpg URL from
`CODEX_CLI_DATABASE_URL`.

Workers claim rows with PostgreSQL `FOR UPDATE SKIP LOCKED`, so concurrent slots
claim different pending work without SQLite's database-wide writer lock.

To migrate an existing contracted SQLite database once:

```powershell
.\scripts\local-home\migrate-sqlite-to-postgres.ps1
```

The command stops writers, checkpoints and backs up `data/app.db`, creates the
PostgreSQL schema with Alembic, copies all physical tables in one transaction,
verifies every table's row count, resets sequences, and restarts the runtime.
The SQLite source and timestamped `data/app.pre-postgres.*.db` backup remain
untouched. See `docs/POSTGRESQL_LOCAL_DATABASE.md` for recovery details.

## R2 Archive Publish

Timeline archive publishing is optional and uses Cloudflare R2 instead of local
MinIO. Configure these only when `/ops/archive` should publish public artifacts:

```text
CODEX_CLI_ARCHIVE_PUBLISH_R2_ENDPOINT=https://<ACCOUNT_ID>.r2.cloudflarestorage.com
CODEX_CLI_ARCHIVE_PUBLISH_R2_ACCESS_KEY=...
CODEX_CLI_ARCHIVE_PUBLISH_R2_SECRET_KEY=...
CODEX_CLI_ARCHIVE_PUBLISH_R2_BUCKET=...
CODEX_CLI_ARCHIVE_PUBLISH_R2_SECURE=true
CODEX_CLI_ARCHIVE_PUBLISH_PUBLIC_BASE_URL=https://<public-bucket-or-domain>
CODEX_CLI_ARCHIVE_PUBLISH_PREFIX=archive
CODEX_CLI_ARCHIVE_PUBLISH_ENVIRONMENT=prod

# Optional dev review bucket. Endpoint/key/secret fall back to the prod values
# above when these optional dev-specific connection values are omitted.
CODEX_CLI_ARCHIVE_PUBLISH_DEV_R2_BUCKET=...
CODEX_CLI_ARCHIVE_PUBLISH_DEV_PUBLIC_BASE_URL=https://<dev-public-bucket-or-domain>
CODEX_CLI_ARCHIVE_PUBLISH_DEV_PREFIX=archive-dev
CODEX_CLI_ARCHIVE_PUBLISH_DEV_ENVIRONMENT=dev
```

Archive publish runs synchronously in `POST /ops/operations/archive-publish`; there
is no local archive publish worker process. See `docs/ARCHIVE_PUBLISH.md` for
object keys and API usage.

## Historical Work Model Database Cutover

These commands apply only to a restored legacy SQLite database. The active
PostgreSQL runtime is already on the contracted work model:

```powershell
.\scripts\local-home\cutover-work-model.ps1 -Rehearsal -NoRestart
.\scripts\local-home\cutover-work-model.ps1
```

The command stops all writers, checkpoints WAL, creates backup/candidate copies,
migrates and validates the candidate, then atomically replaces the DB. Read
`docs/WORK_MODEL_CUTOVER.md` before running it.

## GitHub Actions

GitHub Actions no longer deploys this PC. The only tracked workflow is the
manual `Manual Checks` workflow in `.github/workflows/ci.yml`; this repository
does not include a Docker Publish workflow. Normal operation is local:

```powershell
uv run pytest
uv run ruff check .
uv run pyrefly check --min-severity warn
uv run lint-imports --no-cache
uv run python scripts/check_architecture.py
uv run python scripts/export_openapi.py --check
pnpm --filter codex-sdk-ops-ui api:check
pnpm --filter codex-sdk-ops-ui lint
pnpm --filter codex-sdk-ops-ui typecheck
pnpm --filter codex-sdk-ops-ui test
pnpm --filter codex-sdk-ops-ui build
```
