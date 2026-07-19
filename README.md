# Codex YouTube Pipeline

Local Python/FastAPI and React operations project for collecting YouTube video
metadata and transcripts, generating cue-based micro-events and timelines, and
publishing playback-ready projections through streamer-scoped profiles to local
and remote object/catalog destinations.

The repository contains public-safe code and sample prompt fallbacks. Local DB,
runtime logs, raw media/transcripts, production prompt packs, and secrets are
ignored.

## Runtime

- FastAPI API on `127.0.0.1:8000`.
- Next.js Ops UI on `127.0.0.1:3000/ops`.
- DB-polling transcript, cue, micro-event, and timeline workers.
- Workflow coordinator for transcript -> cue -> micro-event -> timeline ->
  archive.
- Periodic channel/video/transcript scheduler.
- Docker PostgreSQL for the `codex` control DB and `codex_public_catalog`, plus
  MinIO for raw data, private canonical artifacts, and local publication objects.
- Vendor-neutral publication connections configured outside the control DB.

## Quick Start

```powershell
uv sync --dev --locked
corepack enable
pnpm install --frozen-lockfile
Copy-Item scripts/local-home/local.env.example .home-deploy/local.env
Copy-Item scripts/local-home/publish-connections.example.json `
  .home-deploy/publish-connections.json
.\scripts\local-home\deploy.ps1
```

Replace every `CHANGE_ME` value in the two ignored `.home-deploy` files before
deploying.

Check the runtime:

```powershell
.\scripts\local-home\status.ps1
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-WebRequest http://127.0.0.1:3000/ops -UseBasicParsing
```

OpenAPI is available at `http://127.0.0.1:8000/docs`.

## API Example

```powershell
$body = @{
  selection = @{ type = "selected"; videoIds = @(1, 2) }
  retryFailed = $true
  microModel = "gpt-5.6-sol"
  microReasoningEffort = "high"
  timelineModel = "gpt-5.6-luna"
  timelineReasoningEffort = "xhigh"
  publishMode = "prod"
  environment = "prod"
  variant = "control"
} | ConvertTo-Json -Depth 5

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/ops/workflows/process-to-publish" `
  -ContentType "application/json" `
  -Body $body
```

All pipeline commands live under `/ops/operations/*`. Durable execution state
is read and controlled through `/ops/work-items`, `/ops/work-batches`, and
`/ops/workflows`.

## Architecture

```text
src/codex_sdk_cli/
|-- domains/       framework-free policy and models
|-- application/   commands, queries, workflows, ports
|-- infra/         SQLAlchemy and external adapters
|-- bootstrap/     composition root and lazy executor wiring
|-- api/           FastAPI DTOs and routes
|-- workers/       thin process entrypoints
|-- cli.py         Click entrypoint
`-- settings.py    CODEX_CLI_ environment settings
```

Read [Clean Architecture](docs/CLEAN_ARCHITECTURE.md) and
[Agent API Operations](docs/AGENT_API_OPERATIONS.md) before changing boundaries
or operating the pipeline. Publication behavior and offline legacy data handling
are documented in [Archive Publish](docs/ARCHIVE_PUBLISH.md) and
[Publication Data Migration](docs/PUBLICATION_MIGRATION.md).

## Verification

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

Documentation is indexed at [docs/INDEX.md](docs/INDEX.md). Ops UI-specific
guidance is at [ops-ui/docs/INDEX.md](ops-ui/docs/INDEX.md).
