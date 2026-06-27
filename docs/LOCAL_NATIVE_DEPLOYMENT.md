# Local Native Home PC Deployment

This is the current Home PC runtime path.

The app no longer depends on ngrok, Nginx, GHCR image pulls, or GitHub Actions
deployment. Docker is kept only for MinIO. The API, workers, and optional Ops UI
run as Windows processes from this checkout.

## Runtime Topology

```text
Windows process: codex-api / uvicorn on 127.0.0.1:8000
Windows process: codex-micro-event-worker
Windows process: codex-timeline-compose-worker
Windows process: Next.js ops-ui on 127.0.0.1:3000
Docker container: MinIO on 127.0.0.1:9000 and console on 127.0.0.1:9001
SQLite file: ./data/app.db
Runtime state: ./.home-deploy/
```

There is no public URL. Remote operation should be done by an agent running on
this PC and calling `http://127.0.0.1:8000`.

## One-Time Setup

Install local prerequisites:

```powershell
winget install --id Docker.DockerDesktop --exact
winget install --id Git.Git --exact
winget install --id OpenJS.NodeJS.LTS --exact
```

Create local env:

```powershell
New-Item -ItemType Directory -Force .home-deploy | Out-Null
Copy-Item scripts/local-home/local.env.example .home-deploy/local.env
notepad .home-deploy/local.env
```

Keep `.home-deploy/local.env` private. It may contain API keys and local MinIO
credentials.

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
- local API, worker, and Ops UI process cleanup, including stale child processes
  that may keep `.next/standalone` locked
- MinIO start through `compose.local-infra.yaml`
- legacy Docker app/proxy/tunnel containers stop, including `api`, workers,
  `ops-ui`, `nginx`, and `ngrok`
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

`start.ps1` also stops legacy Docker app/proxy/tunnel containers before starting
the native processes, so ngrok is not kept alive by accident. It leaves MinIO
running.

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
```

Archive publish runs synchronously in `POST /video-tasks/archive-publish`; there
is no local archive publish worker process. See `docs/ARCHIVE_PUBLISH.md` for
object keys and API usage.

## GitHub Actions

GitHub Actions no longer deploys this PC. `CI` and `Docker Publish` are manual
workflows only. Normal operation is local:

```powershell
uv run pytest
uv run ruff check src tests
uv run pyrefly check --min-severity warn
pnpm --filter codex-sdk-ops-ui lint
pnpm --filter codex-sdk-ops-ui typecheck
pnpm --filter codex-sdk-ops-ui test
pnpm --filter codex-sdk-ops-ui build
```

## Legacy Files

These files remain for reference or emergency fallback, but are no longer the
normal runtime path:

- `legacy/compose.home.yaml`
- `legacy/compose.home.build.yaml`
- `legacy/compose.yaml`
- `legacy/Dockerfile`
- `legacy/ops-ui/Dockerfile`
- `legacy/deploy/nginx/home.conf`
- `legacy/docs/HOME_DEPLOYMENT_FLOW.md`
- `legacy/docs/AWS_DEPLOYMENT.md`
- `legacy/scripts/deploy_aws.ps1`
- `legacy/infra/aws-codex-cli/`
- `docs/CICD.md`
