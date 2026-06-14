# Home PC Deployment Guide

This guide runs the FastAPI API from a Windows PC so YouTube transcript requests
use the PC's residential network instead of a cloud provider IP.

## Architecture

```text
GitHub main push or workflow_dispatch
  -> GitHub-hosted quality and Docker checks
  -> Windows self-hosted runner on the home PC
  -> Docker Compose home stack
  -> cloudflared tunnel
  -> nginx Basic Auth
  -> codex-api
```

The home stack is defined in `compose.home.yaml`.

- `api`: runs `codex-api` and exposes port `8000` only inside Docker.
- `nginx`: reverse proxies to `api:8000`, requires Basic Auth, and binds
  `127.0.0.1:${HOME_NGINX_PORT:-18080}` for local checks.
- `cloudflared`: connects a remotely managed Cloudflare Tunnel to `nginx:80`.
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

The workflow uses a GitHub-hosted preflight job. If this runner or required
secrets are missing, `main` pushes skip home deployment instead of waiting
forever for a runner.

## Cloudflare Tunnel Setup

Create the tunnel from scratch:

1. Create or log into a Cloudflare account.
2. Add the domain you want to use and point its nameservers to Cloudflare.
3. Open `Zero Trust > Networks > Tunnels`.
4. Create a tunnel and choose Docker as the connector environment.
5. Copy the tunnel token.
6. Add a public hostname such as `api.example.com`.
7. Set the service URL for that hostname to:

```text
http://nginx:80
```

Store the tunnel token and Basic Auth credentials as GitHub repository secrets:

```powershell
gh secret set CLOUDFLARED_TUNNEL_TOKEN -R Mabaragi/codex-sdk
gh secret set HOME_BASIC_AUTH_USER -R Mabaragi/codex-sdk
gh secret set HOME_BASIC_AUTH_PASSWORD -R Mabaragi/codex-sdk
```

Optional repository variables:

```powershell
gh variable set HOME_NGINX_PORT --body 18080 -R Mabaragi/codex-sdk
gh variable set CODEX_CLI_SANDBOX --body workspace-write -R Mabaragi/codex-sdk
gh variable set CODEX_CLI_APPROVAL --body auto-review -R Mabaragi/codex-sdk
```

## Deploy And Verify

Home deployment runs on `main` pushes and can also be started from the GitHub
Actions `CI` workflow with `Run workflow`.

On the home PC, inspect the stack:

```powershell
docker compose --project-name codex-sdk-home -f compose.home.yaml ps
docker compose --project-name codex-sdk-home -f compose.home.yaml logs --tail 100 api nginx cloudflared
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

After Cloudflare DNS and tunnel routing are active, test the public hostname:

```powershell
Invoke-RestMethod `
  -Uri https://api.example.com/health `
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

