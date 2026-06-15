# Home PC Deployment Guide

This guide runs the FastAPI API from a Windows PC so YouTube transcript requests
use the PC's residential network instead of a cloud provider IP.

For the full GitHub Actions CI/CD topology, including Mermaid diagrams and
failure handling, see `docs/CICD.md`.

## Architecture

```text
GitHub main push or workflow_dispatch
  -> GitHub-hosted quality and Docker checks
  -> Windows self-hosted runner on the home PC
  -> Alembic migration against the API SQLite database
  -> Docker Compose home stack
  -> MinIO transcript JSON storage
  -> cloudflared quick tunnel
  -> nginx Basic Auth
  -> codex-api
```

The home stack is defined in `compose.home.yaml`.

- `api`: runs `codex-api` and exposes port `8000` only inside Docker.
- `minio`: stores YouTube transcript response JSON in the `raw` bucket by
  default and is reachable only inside the Docker network.
- SQLite: stores transcript metadata in `youtube_transcripts`; raw transcript
  response JSON remains in MinIO.
- `nginx`: reverse proxies to `api:8000`, requires Basic Auth, and binds
  `127.0.0.1:${HOME_NGINX_PORT:-18080}` for local checks.
- `cloudflared`: starts an ephemeral `trycloudflare.com` quick tunnel to
  `nginx:80`.
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

## Cloudflare Quick Tunnel Setup

The home stack uses Cloudflare's quick tunnel mode. It does not require a
Cloudflare account, domain, DNS record, or tunnel token. Each `cloudflared`
restart can produce a new `https://*.trycloudflare.com` URL, so the deploy job
extracts the latest URL from container logs and writes it to both the GitHub
Actions summary and `.home-deploy/latest-tunnel-url.txt` on the runner.

Store only the Basic Auth credentials as GitHub repository secrets:

```powershell
gh secret set HOME_BASIC_AUTH_USER -R Mabaragi/codex-sdk
gh secret set HOME_BASIC_AUTH_PASSWORD -R Mabaragi/codex-sdk
```

Optional repository variables:

```powershell
gh variable set HOME_NGINX_PORT --body 18080 -R Mabaragi/codex-sdk
gh variable set CODEX_CLI_SANDBOX --body workspace-write -R Mabaragi/codex-sdk
gh variable set CODEX_CLI_APPROVAL --body auto-review -R Mabaragi/codex-sdk
gh variable set CODEX_CLI_TRANSCRIPT_MINIO_BUCKET --body raw -R Mabaragi/codex-sdk
```

The home compose defaults use `minio:9000`, access key `codex`, bucket `raw`,
prefix `youtube/transcripts`, and SQLite URL
`sqlite+aiosqlite:///./data/app.db`. Override
`CODEX_CLI_TRANSCRIPT_MINIO_ACCESS_KEY` and
`CODEX_CLI_TRANSCRIPT_MINIO_SECRET_KEY` with repository secrets for a less
guessable local MinIO credential.

## Deploy And Verify

Home deployment runs on `main` pushes and can also be started from the GitHub
Actions `CI` workflow with `Run workflow`.

The deploy workflow builds the API image, runs `alembic upgrade head` with the
same `CODEX_CLI_DATABASE_URL` used by the API container, then recreates the home
stack. If you redeploy manually from the runner checkout, run the same migration
step before starting the API:

```powershell
docker compose --project-name codex-sdk-home -f compose.home.yaml build api
docker compose --project-name codex-sdk-home -f compose.home.yaml run --rm --no-deps --entrypoint alembic api upgrade head
docker compose --project-name codex-sdk-home -f compose.home.yaml up -d --build --force-recreate api nginx cloudflared minio
```

On the home PC, inspect the stack:

```powershell
docker compose --project-name codex-sdk-home -f compose.home.yaml ps
docker compose --project-name codex-sdk-home -f compose.home.yaml logs --tail 100 api nginx cloudflared minio
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

Read the latest quick tunnel URL on the home PC:

```powershell
Get-Content .home-deploy/latest-tunnel-url.txt
```

Test the public quick tunnel URL:

```powershell
$url = Get-Content .home-deploy/latest-tunnel-url.txt
Invoke-RestMethod `
  -Uri "$url/health" `
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

## Operations

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
