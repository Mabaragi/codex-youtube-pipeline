# Codex SDK Local Pipeline

OpenAI Codex SDK를 실험하는 Python CLI/FastAPI 프로젝트다. 현재는 단순 SDK 데모를 넘어, 로컬 Home PC에서 YouTube 영상 메타데이터 수집, transcript/cue 생성, micro-event 추출, timeline 생성, R2 archive publish까지 운영하는 파이프라인을 포함한다.

정상 운영 경로는 로컬 네이티브 런타임이다. API, worker, Ops UI는 Windows 프로세스로 실행하고, MinIO만 Docker로 실행한다. 공개 서버나 GitHub Actions 배포는 현재 운영 경로가 아니다.

## Current Runtime

```text
API:              127.0.0.1:8000
Ops UI:           127.0.0.1:3000
MinIO:            127.0.0.1:9000 / 127.0.0.1:9001
SQLite DB:        ./data/app.db
Runtime state:    ./.home-deploy/
Workers:
  codex-micro-event-worker
  codex-timeline-compose-worker
```

로컬 운영 에이전트는 `http://127.0.0.1:8000` API를 호출한다. 코드 탐색 없이 운영만 할 때는 [docs/AGENT_API_OPERATIONS.md](docs/AGENT_API_OPERATIONS.md)를 먼저 읽는다.

## Main Capabilities

- Codex SDK CLI: thread 실행, 재개, 로그인, account 확인.
- FastAPI: Codex 실행 API, YouTube pipeline API, 운영 read model API.
- YouTube Data pipeline:
  - channel resolve
  - latest video metadata collect
  - transcript collect
  - transcript cue generation
  - micro-event extraction
  - timeline composition
  - archive publish to Cloudflare R2
- Ops workflow:
  - `/ops/videos`, `/ops/video-tasks`, `/ops/events`
  - `/ops/candidates/micro-event-ready`
  - `/ops/candidates/timeline-ready`
  - `/ops/codex-usage*`
  - `codex-demo ops detect-stuck`
- Timeline maintenance:
  - block split patch
  - display copy patch
  - topic cluster copy patch
  - source micro-event copy patch
  - patch 후 selected video republish
- LLM observability:
  - DB task/job/attempt state
  - operation events
  - Codex usage rows
  - file trace under `.home-deploy/logs/llm-traces/YYYY-MM-DD/`

## Quick Start

Install dependencies:

```powershell
uv sync --dev
corepack enable
pnpm install
```

Create local runtime env:

```powershell
New-Item -ItemType Directory -Force .home-deploy | Out-Null
Copy-Item scripts/local-home/local.env.example .home-deploy/local.env
notepad .home-deploy/local.env
```

Required for the full YouTube/R2 pipeline:

- `CODEX_CLI_API_KEY` or browser/device login
- `CODEX_CLI_YOUTUBE_DATA_API_KEY`
- MinIO settings from `scripts/local-home/local.env.example`
- R2 archive publish settings when publishing public artifacts

Deploy local runtime:

```powershell
.\scripts\local-home\deploy.ps1
```

Start/status/stop:

```powershell
.\scripts\local-home\start.ps1
.\scripts\local-home\status.ps1
.\scripts\local-home\stop.ps1
```

Register reboot recovery:

```powershell
.\scripts\local-home\register-task.ps1
```

See [docs/LOCAL_NATIVE_DEPLOYMENT.md](docs/LOCAL_NATIVE_DEPLOYMENT.md) for the full local runtime procedure.

## Codex CLI

Login:

```powershell
uv run codex-demo login browser
uv run codex-demo login device
uv run codex-demo login api-key
```

Run a prompt:

```powershell
uv run codex-demo run "Describe this repository in one sentence."
```

Persist and resume a thread:

```powershell
uv run codex-demo run --persist "Create a short project summary."
uv run codex-demo run --thread-id <thread-id> "Continue from the previous answer."
```

Account and logout:

```powershell
uv run codex-demo account
uv run codex-demo logout
```

Operational CLI examples:

```powershell
uv run codex-demo ops detect-stuck --task micro_event_extract --minutes 15
uv run codex-demo ops detect-stuck --task timeline_compose --minutes 15
```

## Common API Workflows

Base URL:

```powershell
$base = "http://127.0.0.1:8000"
```

Health and status:

```powershell
Invoke-RestMethod "$base/health"
Invoke-RestMethod "$base/ops/summary"
```

Collect latest videos for one channel:

```powershell
Invoke-RestMethod -Method Post "$base/channels/1/videos/collect"
```

Collect transcripts and generate cues:

```powershell
$body = @{
  limit = 5
  languages = @("ko", "en")
  preserveFormatting = $false
  retryFailed = $false
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri "$base/channels/1/video-tasks/transcript-collect" `
  -ContentType "application/json" `
  -Body $body
```

Process selected videos through micro-event, timeline, and publish:

```powershell
$body = @{
  videoIds = @(114)
  microReasoning = "medium"
  timelineReasoning = "high"
  retryFailed = $false
  waitTimeoutMinutes = 30
  pollIntervalSeconds = 10
  environment = "prod"
  variant = "control"
  schemaVersion = 1
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri "$base/video-tasks/process-to-publish" `
  -ContentType "application/json" `
  -Body $body
```

Publish timeline-ready videos without recomposing:

```powershell
$body = @{
  target = "next_eligible"
  limit = 20
  environment = "prod"
  variant = "control"
  schemaVersion = 1
  retryFailed = $false
  regenerateSucceeded = $false
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri "$base/video-tasks/archive-publish" `
  -ContentType "application/json" `
  -Body $body
```

For Korean text in request bodies, use `Invoke-JsonUtf8` from `scripts/local-home/common.ps1` to avoid PowerShell encoding issues.

Detailed recipes live under `docs/agent-api-operations/`.

## Data Pipeline Model

Pipeline state is split deliberately:

- `pipeline_jobs`: logical work request.
- `pipeline_job_attempts`: one execution attempt under a job.
- `video_tasks`: durable per-video work ownership and worker claim state.
- `external_api_calls`: sanitized external API metadata; raw body goes to object storage.
- domain tables: normalized application data such as videos, transcripts, cues, micro-events, timelines.
- `operation_events`: operational timeline.
- `codex_run_usages`: token usage and model/reasoning trace.

Transcript and external API raw JSON are stored in MinIO. R2 archive publish writes public immutable timeline artifacts and updates the public pointer/index. LLM trace raw responses are file-based under `.home-deploy/logs/llm-traces`.

See [docs/YOUTUBE_DATA_PIPELINE.md](docs/YOUTUBE_DATA_PIPELINE.md) for lifecycle and identity rules.

## API And UI Surfaces

Main local surfaces:

- FastAPI docs: `http://127.0.0.1:8000/docs`
- OpenAPI: `http://127.0.0.1:8000/openapi.json`
- Ops UI: `http://127.0.0.1:3000/ops`

Important route groups:

- `/codex/*`
- `/streamers`, `/channels`, `/channels/{id}/videos`
- `/video-tasks/*`
- `/youtube-transcripts/*`
- `/videos/{id}/micro-event-extractions/*`
- `/videos/{id}/timelines/*`
- `/pipeline/jobs/*`
- `/ops/*`

Route handlers stay thin. Business workflows live in domain use cases, infrastructure adapters live under `src/codex_sdk_cli/infra/`, and SQL schema changes go through Alembic migrations.

## Configuration

Environment variables use the `CODEX_CLI_` prefix. Most local defaults are shown in [scripts/local-home/local.env.example](scripts/local-home/local.env.example).

Common settings:

- `CODEX_CLI_DATABASE_URL`
- `CODEX_CLI_MODEL`
- `CODEX_CLI_REASONING_EFFORT`
- `CODEX_CLI_API_KEY`
- `CODEX_CLI_YOUTUBE_DATA_API_KEY`
- `CODEX_CLI_TRANSCRIPT_MINIO_*`
- `CODEX_CLI_EXTERNAL_API_CALL_MINIO_PREFIX`
- `CODEX_CLI_MICRO_EVENT_EXTRACT_CONCURRENCY_LIMIT`
- `CODEX_CLI_TIMELINE_COMPOSE_CONCURRENCY_LIMIT`
- `CODEX_CLI_LLM_TRACE_*`
- `CODEX_CLI_ARCHIVE_PUBLISH_R2_*`

Ops UI uses:

- `CODEX_OPS_BACKEND_BASE_URL`
- `HOSTNAME`
- `PORT`

Keep `.home-deploy/local.env` private.

## Database

The project uses async SQLAlchemy and Alembic.

```powershell
uv run alembic check
uv run alembic revision --autogenerate -m "create <name>"
uv run alembic upgrade head
```

Do not call `metadata.create_all()` or `metadata.drop_all()` from app code, tests, or startup hooks.

## Verification

Backend:

```powershell
uv run pytest
uv run ruff check src tests
uv run pyrefly check --min-severity warn
uv run python scripts/export_openapi.py --check
```

Frontend:

```powershell
pnpm --filter codex-sdk-ops-ui api:check
pnpm --filter codex-sdk-ops-ui lint
pnpm --filter codex-sdk-ops-ui typecheck
pnpm --filter codex-sdk-ops-ui test
pnpm --filter codex-sdk-ops-ui build
```

For focused backend changes, run the smallest relevant pytest target plus `ruff check src tests`.

## Documentation Map

- [docs/PROJECT_OVERVIEW.md](docs/PROJECT_OVERVIEW.md): project structure and API inventory.
- [docs/YOUTUBE_DATA_PIPELINE.md](docs/YOUTUBE_DATA_PIPELINE.md): pipeline state and data lifecycle.
- [docs/LOCAL_NATIVE_DEPLOYMENT.md](docs/LOCAL_NATIVE_DEPLOYMENT.md): current Home PC runtime.
- [docs/AGENT_API_OPERATIONS.md](docs/AGENT_API_OPERATIONS.md): API-only operating guide.
- [docs/ARCHIVE_PUBLISH.md](docs/ARCHIVE_PUBLISH.md): R2 archive object layout and publish API.
- [docs/CICD.md](docs/CICD.md): manual GitHub Actions status.
- [ops-ui/docs/FRONTEND_ARCHITECTURE.md](ops-ui/docs/FRONTEND_ARCHITECTURE.md): Ops UI architecture.

Legacy Docker, AWS, GHCR, nginx, and ngrok material lives under `legacy/` for reference only.
