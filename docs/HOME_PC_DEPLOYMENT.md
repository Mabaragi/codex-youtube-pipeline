# Home PC Deployment Guide

This guide runs the FastAPI API from a Windows PC so YouTube transcript requests
use the PC's residential network instead of a cloud provider IP.

For the full GitHub Actions CI/CD topology, including Mermaid diagrams and
failure handling, see `docs/CICD.md`. For the concrete before/after deployment
flow change from Home PC local builds to GHCR pulls, see
`docs/HOME_DEPLOYMENT_FLOW.md`.

## Architecture

```text
GitHub main push or workflow_dispatch
  -> GitHub-hosted quality checks and GHCR image publish
  -> Windows self-hosted runner on the home PC
  -> Pull immutable API and ops-ui images from GHCR
  -> Alembic migration against the API SQLite database
  -> Docker Compose home stack
  -> Next.js ops-ui
  -> MinIO raw JSON storage
  -> ngrok dev domain tunnel
  -> nginx Basic Auth
  -> codex-api and /ops
```

The home stack is defined in `compose.home.yaml`. It is image-based for normal
deployment. Use `compose.home.build.yaml` only when manually rebuilding images
on the home PC.

- `api`: runs `codex-api` from `CODEX_API_IMAGE` and exposes port `8000`
  only inside Docker.
- `micro-event-worker`: runs `codex-micro-event-worker` from the same
  `CODEX_API_IMAGE`, polls pending `micro_event_extract` video tasks from the
  SQLite database, and executes them outside the API process.
- `ops-ui`: runs the Next.js operational console from `CODEX_OPS_UI_IMAGE` and
  exposes port `3000` only inside Docker. Browser-visible backend calls go
  through `/ops/api/backend/*`.
- `minio`: stores YouTube transcript and external API raw response JSON in the
  `raw` bucket by default and is reachable only inside the Docker network.
- SQLite: stores metadata in `youtube_transcripts`, `external_api_calls`,
  `pipeline_jobs`, `pipeline_job_attempts`, `streamers`, `channels`, `videos`,
  and `video_tasks`; raw JSON remains in MinIO.
- `nginx`: reverse proxies `/ops` to `ops-ui:3000` and API routes to
  `api:8000`, requires Basic Auth, and binds
  `127.0.0.1:${HOME_NGINX_PORT:-18080}` for local checks.
- `ngrok`: starts a fixed dev domain tunnel to `nginx:80`.
- `codex`: utility service for one-time `codex-demo login device`.

## One-Time Windows PC Setup

Install these tools on the PC that will host the API:

```powershell
winget install --id Docker.DockerDesktop --exact
winget install --id GitHub.cli --exact
```

Install a repository-level GitHub Actions self-hosted runner:

1. Open GitHub repository settings.
2. Go to `Settings > Actions > Runners > New self-hosted runner`.
3. Choose `Windows`.
4. Follow GitHub's download and `config.cmd` instructions.
5. Add the custom label `codex-home` during configuration.
6. Configure the runner as a Windows service.

The runner must appear online with labels:

```text
self-hosted
Windows
X64
codex-home
```

The workflow uses a GitHub-hosted preflight job to verify required secrets. If
the runner is offline, the home deployment job will wait until the runner comes
back online.

## ngrok Tunnel Setup

The home stack uses an ngrok dev domain tunnel. The `ngrok` container forwards
`https://mutation-runny-smelting.ngrok-free.dev` to Docker Nginx at `nginx:80`.
The deploy job writes this URL to both the GitHub Actions summary and
`.home-deploy/latest-tunnel-url.txt` on the runner.

Store Basic Auth and ngrok credentials as GitHub repository secrets:

```powershell
gh secret set HOME_BASIC_AUTH_USER -R Mabaragi/codex-sdk
gh secret set HOME_BASIC_AUTH_PASSWORD -R Mabaragi/codex-sdk
gh secret set NGROK_AUTHTOKEN -R Mabaragi/codex-sdk
```

Optional repository variables:

```powershell
gh variable set HOME_NGINX_PORT --body 18080 -R Mabaragi/codex-sdk
gh variable set NGROK_DOMAIN --body mutation-runny-smelting.ngrok-free.dev -R Mabaragi/codex-sdk
gh variable set CODEX_CLI_SANDBOX --body workspace-write -R Mabaragi/codex-sdk
gh variable set CODEX_CLI_APPROVAL --body auto-review -R Mabaragi/codex-sdk
gh secret set CODEX_CLI_YOUTUBE_DATA_API_KEY -R Mabaragi/codex-sdk
gh variable set CODEX_CLI_TRANSCRIPT_MINIO_BUCKET --body raw -R Mabaragi/codex-sdk
```

The home compose defaults use `minio:9000`, access key `codex`, bucket `raw`,
transcript prefix `youtube/transcripts`, external API call prefix
`external-api-calls`, and SQLite URL
`sqlite+aiosqlite:////data/db/app.db`. The SQLite file lives on the
`db-data` Docker named volume at `/data/db/app.db`, not in the runner checkout.
Override
`CODEX_CLI_TRANSCRIPT_MINIO_ACCESS_KEY` and
`CODEX_CLI_TRANSCRIPT_MINIO_SECRET_KEY` with repository secrets for a less
guessable local MinIO credential.

## Deploy And Verify

Home deployment runs on `main` pushes and can also be started from the GitHub
Actions `CI` workflow with `Run workflow`.

The CI workflow publishes immutable SHA-tagged images to GHCR, then the home
runner pulls those images, runs `alembic upgrade head` with the same
`CODEX_CLI_DATABASE_URL` used by the API container, and updates the home stack
without rebuilding locally. On the first deploy after moving SQLite out of the
checkout, the workflow backs up a legacy `data/app.db` before checkout cleanup
and copies it into the `db-data` volume only if that volume does not already
contain `app.db`.

The detailed command-by-command flow, image naming rules, and local-build
fallback are recorded in `docs/HOME_DEPLOYMENT_FLOW.md`.

If you redeploy manually from the runner checkout using already-published GHCR
images, set `CODEX_API_IMAGE` and `CODEX_OPS_UI_IMAGE`, then run:

```powershell
docker login ghcr.io
docker compose --project-name codex-sdk-home -f compose.home.yaml pull api micro-event-worker codex ops-ui
docker compose --project-name codex-sdk-home -f compose.home.yaml run --rm --no-deps --entrypoint alembic api upgrade head
docker compose --project-name codex-sdk-home -f compose.home.yaml up -d --no-build --remove-orphans api micro-event-worker ops-ui nginx ngrok minio
```

If you intentionally need to rebuild images on the home PC, add the build
override:

```powershell
docker compose --project-name codex-sdk-home -f compose.home.yaml -f compose.home.build.yaml build api ops-ui
docker compose --project-name codex-sdk-home -f compose.home.yaml -f compose.home.build.yaml run --rm --no-deps --entrypoint alembic api upgrade head
docker compose --project-name codex-sdk-home -f compose.home.yaml -f compose.home.build.yaml up -d --no-build --remove-orphans api micro-event-worker ops-ui nginx ngrok minio
```

On the home PC, inspect the stack:

```powershell
docker compose --project-name codex-sdk-home -f compose.home.yaml ps
docker compose --project-name codex-sdk-home -f compose.home.yaml logs --tail 100 api micro-event-worker ops-ui nginx ngrok minio
```

Check the local Nginx endpoint with Basic Auth:

```powershell
$user = "<HOME_BASIC_AUTH_USER>"
$password = "<HOME_BASIC_AUTH_PASSWORD>"
$pair = "${user}:${password}"
$encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($pair))
Invoke-RestMethod `
  -Uri http://127.0.0.1:18080/health `
  -Headers @{ Authorization = "Basic $encoded" }
```

Read the current public tunnel URL on the home PC:

```powershell
Get-Content .home-deploy/latest-tunnel-url.txt
```

Test the public ngrok URL:

```powershell
$url = Get-Content .home-deploy/latest-tunnel-url.txt
Invoke-RestMethod `
  -Uri "$url/health" `
  -Headers @{ Authorization = "Basic $encoded" }
Invoke-WebRequest `
  -Uri "$url/ops" `
  -Headers @{ Authorization = "Basic $encoded" } `
  -UseBasicParsing
Invoke-RestMethod `
  -Uri "$url/ops/api/backend/ops/summary" `
  -Headers @{ Authorization = "Basic $encoded" }
```

## Codex Login

The deployment does not inject an OpenAI API key. Run device-code login once and
keep the Docker volume:

```powershell
docker compose --project-name codex-sdk-home -f compose.home.yaml run --rm codex login device
docker compose --project-name codex-sdk-home -f compose.home.yaml run --rm codex account
```

The `codex-home` Docker volume stores `/home/codex/.codex` for both `codex` and
`api`.

The `db-data` Docker volume stores the SQLite application metadata database.
Preserve it across redeploys; deleting this volume clears `streamers`,
`channels`, `youtube_transcripts`, and `external_api_calls` metadata.

## Operations

After a PC reboot, make sure both the GitHub self-hosted runner and Docker
Desktop are actually ready before redeploying. The runner can accept a job while
Docker Desktop's Linux engine is still down, which fails the deploy during
Docker-backed steps such as Basic Auth file generation.

```powershell
docker info
gh workflow run CI -R Mabaragi/codex-sdk --ref main
```

If `docker info` cannot connect to `npipe:////./pipe/dockerDesktopLinuxEngine`,
start Docker Desktop, wait until the engine is ready, then run the workflow
again.

Redeploy manually:

```powershell
gh workflow run CI -R Mabaragi/codex-sdk --ref main
```

Restart the stack on the home PC:

```powershell
docker compose --project-name codex-sdk-home -f compose.home.yaml restart
```

Stop the stack:

```powershell
docker compose --project-name codex-sdk-home -f compose.home.yaml down
```

Preserve `codex-home` unless you intentionally want to clear Codex login state.
Preserve `db-data` unless you intentionally want to clear the application
metadata database.
