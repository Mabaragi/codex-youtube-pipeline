# Codex SDK CLI Demo

A small Python CLI and FastAPI app that use the OpenAI Codex SDK to start or
resume Codex threads, run prompts, manage local Codex authentication, and test
YouTube transcript/data workflows.

## Install

```powershell
uv sync --dev
corepack enable
pnpm install
```

## Login

```powershell
uv run codex-demo login browser
uv run codex-demo login device
uv run codex-demo login api-key
```

`login api-key` reads `--api-key` when provided, then `CODEX_CLI_API_KEY`, then
falls back to a hidden prompt.

## Run Codex

Start a new ephemeral thread:

```powershell
uv run codex-demo run "Describe this repository in one sentence."
```

Persist a new thread when you want to resume it later:

```powershell
uv run codex-demo run --persist "Describe this repository in one sentence."
```

Resume a previous thread:

```powershell
uv run codex-demo run --thread-id <thread-id> "Continue from the previous answer."
```

By default, newly created threads are ephemeral and should not be materialized on
disk by the Codex SDK. Use `--persist` only for threads that need a durable
thread id for later `--thread-id` resume. `--persist` has no effect when
resuming an existing thread.

Useful options:

```powershell
uv run codex-demo run --sandbox read-only --approval deny-all "Review the project."
uv run codex-demo run --cwd C:\path\to\repo --model gpt-5.4 "Explain this codebase."
uv run codex-demo run --empty-base-instructions "Answer with no SDK base instructions."
uv run codex-demo run --empty-developer-instructions "Answer with no SDK developer instructions."
```

`--empty-base-instructions` and `--empty-developer-instructions` send blank
instruction overrides to the Codex SDK. The SDK server rejects an actual empty
string during turn execution, so the CLI uses whitespace overrides to compare
behavior or token usage without the SDK's default instructions.

## Account

```powershell
uv run codex-demo account
uv run codex-demo logout
```

## Domain Knowledge CLI

Domain knowledge entries are stored in the app database and are shared by the
Ops UI, API, CLI, and micro-event extraction prompts. Set
`CODEX_CLI_DATABASE_URL` when you want the CLI to write to a specific database;
otherwise it uses the local default database.

List known entry types:

```powershell
uv run codex-demo domain type list
```

List entries. By default archived entries are hidden:

```powershell
uv run codex-demo domain entry list
uv run codex-demo domain entry list --streamer-id 1
uv run codex-demo domain entry list --type person --q "nickname"
uv run codex-demo domain entry list --include-inactive
```

Add one entry. `--type` accepts an existing type key/label or a new label; when
the type does not exist, the server-side use case creates it before saving the
entry. Repeat `--streamer-id` and `--alias` to attach multiple values.

```powershell
uv run codex-demo domain entry add `
  --type "사람 이름" `
  --name "홍길동" `
  --detail "스트리머가 자주 언급하는 예시 인물이다." `
  --streamer-id 1 `
  --alias "길동"
```

Useful add options:

- `--prompt-policy AUTO_ON_MATCH`: inject only when the name or alias appears.
- `--prompt-policy ALWAYS_FOR_SCOPED_STREAMER`: inject for linked streamers even
  without a text match, subject to extraction caps.
- `--prompt-policy DISABLED`: keep the entry stored but do not inject it.
- `--priority <number>`: lower numbers are considered earlier when prompt
  annotations are capped.
- `--source-note "..."`: record where the knowledge came from.

Import entries from JSONL. Each line is the same camelCase payload used by the
API `POST /domain-entries` request. This format is intended for agents and bulk
manual curation because it can set advanced alias metadata.

```powershell
uv run codex-demo domain entry import .\domain-entries.jsonl
```

Example JSONL line:

```json
{"typeLabel":"게임 용어","canonicalName":"텔레포터","detail":"게임 진행 중 이동 장치나 선택지로 언급된다.","streamerIds":[1],"aliases":[{"surfaceForm":"텔포","aliasKind":"ALIAS","certainty":"HIGH","applyScope":"SEARCH_AND_SUMMARY"}],"promptPolicy":"AUTO_ON_MATCH","priority":40}
```

## Configuration

Environment variables use the `CODEX_CLI_` prefix:

- `CODEX_CLI_MODEL`
- `CODEX_CLI_SANDBOX` (`read-only`, `workspace-write`, `full-access`)
- `CODEX_CLI_APPROVAL` (`auto-review`, `deny-all`)
- `CODEX_CLI_CODEX_BIN`
- `CODEX_CLI_API_KEY`
- `CODEX_CLI_YOUTUBE_HTTP_PROXY`
- `CODEX_CLI_YOUTUBE_HTTPS_PROXY`
- `CODEX_CLI_YOUTUBE_DATA_API_KEY`
- `CODEX_CLI_YOUTUBE_DATA_TIMEOUT_SECONDS` (default: `10`)
- `CODEX_CLI_TRANSCRIPT_MINIO_ENDPOINT`
- `CODEX_CLI_TRANSCRIPT_MINIO_ACCESS_KEY`
- `CODEX_CLI_TRANSCRIPT_MINIO_SECRET_KEY`
- `CODEX_CLI_TRANSCRIPT_MINIO_BUCKET`
- `CODEX_CLI_TRANSCRIPT_MINIO_PREFIX` (default: `youtube/transcripts`)
- `CODEX_CLI_TRANSCRIPT_MINIO_SECURE` (default: `false`)
- `CODEX_CLI_TRANSCRIPT_COLLECT_DELAY_SECONDS` (default: `300`)
- `CODEX_CLI_TRANSCRIPT_COLLECT_TIMEOUT_SECONDS`
- `CODEX_CLI_TRANSCRIPT_COLLECT_CONCURRENCY_LIMIT`
- `CODEX_CLI_TRANSCRIPT_CUE_GENERATE_TIMEOUT_SECONDS`
- `CODEX_CLI_TRANSCRIPT_CUE_GENERATE_CONCURRENCY_LIMIT`
- `CODEX_CLI_MICRO_EVENT_EXTRACT_TIMEOUT_SECONDS`
- `CODEX_CLI_MICRO_EVENT_EXTRACT_CONCURRENCY_LIMIT`
- `CODEX_CLI_MICRO_EVENT_WORKER_POLL_INTERVAL_SECONDS`
- `CODEX_CLI_MICRO_EVENT_WORKER_ID`
- `CODEX_CLI_TIMELINE_COMPOSE_TIMEOUT_SECONDS`
- `CODEX_CLI_TIMELINE_COMPOSE_WORKER_POLL_INTERVAL_SECONDS`
- `CODEX_CLI_TIMELINE_COMPOSE_WORKER_ID`
- `CODEX_CLI_EXTERNAL_API_CALL_MINIO_PREFIX` (default: `external-api-calls`)
- `CODEX_CLI_DATABASE_URL` (app default:
  `sqlite+aiosqlite:///./data/app.db`; Docker Compose default:
  `sqlite+aiosqlite:////data/db/app.db`)
- `CODEX_CLI_DATABASE_ECHO` (default: `false`)

## Database

The project uses async SQLAlchemy with Alembic migrations. Non-Docker runs use
`./data/app.db` by default; Docker Compose runs use `/data/db/app.db` on the
`db-data` named volume so redeploy checkout cleanup does not remove metadata.
Local database files and SQLite journal/WAL files are ignored by git. Current
application tables are `youtube_transcripts`, `streamers`, `channels`,
`external_api_calls`, `pipeline_jobs`, `pipeline_job_attempts`, `videos`,
`video_tasks`, transcript cues, operation events, Codex usage, domain knowledge,
micro-event extraction, and timeline composition tables. See
`docs/PROJECT_OVERVIEW.md` for the current table inventory. Transcript and
external API raw response JSON stays in MinIO while SQLite stores metadata plus
the MinIO bucket, object name, URI, response hash, validation status, and
pipeline state. Operators can update only the nullable `notes` field through the
transcript metadata API.

Schema changes must go through Alembic migrations. Do not call
`metadata.create_all()` or `metadata.drop_all()` from app code, tests, or startup
hooks.

```powershell
uv run alembic check
uv run alembic revision --autogenerate -m "create <name>"
uv run alembic upgrade head
```

Review autogenerated migrations before applying or committing them. Alembic is
configured with SQLite batch rendering for future alter-table compatibility.

## Checks

```powershell
uv run pytest
uv run ruff check .
uv run pyrefly check --min-severity warn
uv run python scripts/export_openapi.py --check
pnpm --filter codex-sdk-ops-ui api:check
pnpm --filter codex-sdk-ops-ui lint
pnpm --filter codex-sdk-ops-ui typecheck
pnpm --filter codex-sdk-ops-ui test
pnpm --filter codex-sdk-ops-ui build
```

## AWS Deployment

The AWS EC2/Terraform deployment path is legacy. Its files are archived under
`legacy/` with their original root-relative layout preserved, and are not part
of the normal Home PC runtime.

For reference, the old entrypoint is `legacy/scripts/deploy_aws.ps1`. Treat it
as archival material: restore the legacy tree to the old root layout or adjust
its internal paths before using it again.

See `legacy/docs/AWS_DEPLOYMENT.md` for SSM login, Codex authentication, and optional
S3 Mountpoint usage.

## Docker

Docker deployment artifacts are legacy. The current Home PC runtime keeps MinIO
in Docker and runs the API, workers, and Ops UI as local Windows processes. See
`docs/LOCAL_NATIVE_DEPLOYMENT.md`.

Archived Docker files live under `legacy/` with their original root-relative
paths preserved:

- `legacy/Dockerfile`
- `legacy/compose.yaml`
- `legacy/compose.home.yaml`
- `legacy/compose.home.build.yaml`
- `legacy/ops-ui/Dockerfile`
- `legacy/deploy/nginx/home.conf`

The old CLI image workflow can still be reconstructed from `legacy/` if needed,
but it is no longer the documented operating path.

## REST API

Start the local Home PC runtime:

```powershell
.\scripts\local-home\start.ps1
```

Open `http://localhost:8000/docs`, or call the API directly:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://localhost:8000/codex/runs `
  -ContentType "application/json" `
  -Body '{"prompt":"Describe /work in one sentence.","baseInstructions":"You are concise.","developerInstructions":"Answer in Korean."}'
```

Fetch YouTube captions by URL or video ID:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://localhost:8000/youtube-transcripts `
  -ContentType "application/json" `
  -Body '{"video":"https://www.youtube.com/watch?v=dQw4w9WgXcQ","languages":["ko","en"],"preserveFormatting":false}'
```

The YouTube transcript endpoint returns the selected transcript metadata,
newline-joined plain text, the original timed caption segments, and the MinIO
object location. It stores the same response JSON in MinIO, then records
metadata and the storage path in `youtube_transcripts` before returning success:

```json
{
  "videoId": "dQw4w9WgXcQ",
  "storage": {
    "bucket": "raw",
    "objectName": "youtube/transcripts/2026/06/15/dQw4w9WgXcQ-<hash>.json",
    "uri": "s3://raw/youtube/transcripts/2026/06/15/dQw4w9WgXcQ-<hash>.json"
  }
}
```

List, inspect, annotate, and delete stored metadata rows:

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/youtube-transcripts?videoId=dQw4w9WgXcQ"
Invoke-RestMethod -Uri http://localhost:8000/youtube-transcripts/1
Invoke-RestMethod `
  -Method Patch `
  -Uri http://localhost:8000/youtube-transcripts/1 `
  -ContentType "application/json" `
  -Body '{"notes":"reviewed"}'
Invoke-RestMethod -Method Delete -Uri http://localhost:8000/youtube-transcripts/1
```

Metadata deletion removes only the SQLite row. The raw transcript JSON remains
in MinIO at the recorded `storage.uri`.

If MinIO is not configured, the object write fails, or the database metadata
write fails, the endpoint returns an error instead of silently dropping the
transcript. If YouTube blocks cloud provider traffic, configure
`CODEX_CLI_YOUTUBE_HTTP_PROXY` and/or
`CODEX_CLI_YOUTUBE_HTTPS_PROXY` before starting the API.

Create local streamer metadata and manually create a channel when you already
know all fields:

```powershell
$streamer = Invoke-RestMethod `
  -Method Post `
  -Uri http://localhost:8000/streamers `
  -ContentType "application/json" `
  -Body '{"name":"Chzzk Archive"}'

Invoke-RestMethod `
  -Method Post `
  -Uri "http://localhost:8000/streamers/$($streamer.id)/channels" `
  -ContentType "application/json" `
  -Body (@{
    handle = "@GoogleDevelopers"
    name = "Google Developers"
  } | ConvertTo-Json)
```

Or resolve a YouTube handle for a registered streamer and create one complete
local `channels` row:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://localhost:8000/streamers/$($streamer.id)/channels/resolve" `
  -ContentType "application/json" `
  -Body (@{
    handle = "@GoogleDevelopers"
  } | ConvertTo-Json)
```

This endpoint requires `CODEX_CLI_YOUTUBE_DATA_API_KEY`. It uses the official
YouTube Data API `channels.list` method with `forHandle` and
`part=id,snippet,contentDetails`, validates the response shape, and creates a
channel row whose local identifier is returned as `channelId`. The YouTube
external identifier is returned as `youtubeChannelId`; the cached uploads
playlist identifier is returned as `uploadsPlaylistId`. The raw YouTube Data API
response body is saved to MinIO, `external_api_calls` stores its metadata, and
the created channel returns the metadata row as `sourceApiCallId`. The endpoint
also creates a `channel_resolve` pipeline job/attempt and returns `jobId` and
`jobAttemptId`.

Failed `channel_resolve` jobs can be retried synchronously by the API server.
Retry creates a new attempt under the same job:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://localhost:8000/pipeline/jobs/<jobId>/retry
```

Pipeline jobs can also be inspected for operational debugging:

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/pipeline/jobs?status=failed&limit=20"
Invoke-RestMethod -Uri "http://localhost:8000/pipeline/jobs/<jobId>"
```

Operational read APIs for the UI are exposed under `/ops/*`, including
`/ops/summary`, `/ops/channels`, `/ops/videos`, `/ops/video-tasks`, and
`/ops/schema-graph`. The deployed UI renders the schema graph interactively at
`/ops/erd`; static ERD SVG artifacts are no longer generated.

The normal Home PC runtime has no public URL. Remote operation should be done by
an agent running on this PC and calling `http://127.0.0.1:8000`; see
`docs/AGENT_API_OPERATIONS.md`.

The REST API keeps route handlers thin: HTTP DTOs live in the Codex domain,
application workflows live in use cases, and the actual Codex SDK adapter lives
under the infrastructure layer.

## GitHub CI/CD

GitHub Actions are not part of the normal deployment loop. The active workflow
set is manual verification only; legacy GHCR publishing is archived under
`legacy/.github/workflows/`.

`main` pushes do not deploy the Home PC. GitHub Actions are manual checks only;
see `docs/CICD.md`. Home PC operations use the local native flow in
`docs/HOME_PC_DEPLOYMENT.md`.

The older Terraform EC2 deployment remains documented in
`legacy/docs/AWS_DEPLOYMENT.md` for manual AWS reference, but `main` pushes no
longer deploy to EC2.
