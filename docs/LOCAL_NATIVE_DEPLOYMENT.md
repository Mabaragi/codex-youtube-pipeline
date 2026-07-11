# Local Native Home PC Deployment

This is the current Home PC runtime path.

The app no longer depends on ngrok, Nginx, GHCR image pulls, or GitHub Actions
deployment. Docker is kept only for MinIO. The API, workers, and optional Ops UI
run as Windows processes from this checkout.

## Runtime Topology

```text
Windows process: codex-api / uvicorn on 127.0.0.1:8000
Windows process: codex-pipeline-scheduler
Windows process: codex-transcript-worker
Windows process: codex-transcript-cue-worker
Windows process: codex-micro-event-worker
Windows process: codex-timeline-compose-worker
Windows process: codex-workflow-coordinator
Windows process: Next.js ops-ui on 127.0.0.1:3000
Docker container: MinIO on 127.0.0.1:9000 and console on 127.0.0.1:9001
SQLite file: ./data/app.db
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

Keep `.home-deploy/local.env` private. It may contain API keys and local MinIO
credentials.

`codex-pipeline-scheduler` starts by default and needs
`CODEX_CLI_YOUTUBE_DATA_API_KEY` to collect channel/video metadata. Set the key
in `.home-deploy/local.env`, or set `CODEX_CLI_PIPELINE_SCHEDULER_ENABLED=false`
when this machine should not run automatic collection. Without either choice,
the scheduler process stays alive but logs a failed tick every poll interval.

### Optional ASR Prerequisites

`codex-demo asr transcribe` also needs `yt-dlp`, `ffmpeg`, and `ffprobe`. Put
the executables on `PATH` or set `CODEX_CLI_YTDLP_BIN`, `CODEX_CLI_FFMPEG_BIN`,
and `CODEX_CLI_FFPROBE_BIN` in the private local env. These tools are not
needed for the API, scheduler, or ordinary transcript collection.

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
- MinIO start through `compose.local-infra.yaml`
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

`start.ps1` starts native app processes and leaves MinIO running. The native app
processes are API, pipeline scheduler, transcript worker, cue worker,
micro-event worker, timeline worker, workflow coordinator, and optionally Ops
UI.

Check status:

```powershell
.\scripts\local-home\status.ps1
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-WebRequest http://127.0.0.1:3000/ops -UseBasicParsing
```

Stop app processes:

```powershell
.\scripts\local-home\stop.ps1
```

`stop.ps1` removes both PID-file managed processes and stale local runtime
children such as Next standalone `node` processes. This keeps a later
`deploy.ps1` from failing with Windows `EBUSY` errors while rebuilding
`ops-ui/.next`.

Stop app processes and MinIO:

```powershell
.\scripts\local-home\stop.ps1 -StopInfra
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

The task runs `start.ps1 -NoBuild` at logon and then repeats every 5 minutes.
Because `start.ps1` is idempotent, it starts only missing processes.

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

## Work Model Database Cutover

The work-model transition must use an offline candidate DB rather than a direct
in-place migration:

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
