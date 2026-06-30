# Codex YouTube Pipeline

Python `codex-demo` CLI와 `codex-api` FastAPI 앱으로 구성된 로컬 YouTube 데이터 파이프라인 예제 프로젝트다. Codex SDK 실행, YouTube 메타데이터/자막 수집, transcript cue 생성, micro-event 추출, timeline 구성, archive publish 흐름을 한 저장소에서 실험할 수 있다.

이 공개 저장소에는 코드와 public-safe 샘플 프롬프트만 포함한다. 실제 운영 데이터, 내부 runbook, raw LLM trace, production prompt pack, API key, 로컬 DB는 포함하지 않는다.

## 주요 기능

- Codex SDK CLI: prompt 실행, thread 재개, 로그인, account 확인.
- FastAPI backend: Codex 실행 API, YouTube pipeline API, 운영 조회 API.
- YouTube pipeline:
  - streamer/channel metadata 관리
  - 최신 video metadata 수집
  - transcript 수집과 cue 생성
  - cue 기반 micro-event 후보 추출
  - micro-event 기반 timeline 구성
  - Cloudflare R2 compatible archive publish
- Ops UI: Next.js 기반 로컬 운영 콘솔.
- 관측성:
  - `video_tasks`, `pipeline_jobs`, `pipeline_job_attempts`
  - `operation_events`
  - LLM usage row
  - optional file trace under `.home-deploy/logs/llm-traces`

## 공개 저장소 정책

다음 항목은 commit하지 않는다.

- `.home-deploy/`, `data/`, SQLite DB, local env, PID/log files.
- raw transcript, cue, micro-event, timeline export JSON.
- production prompt pack과 내부 prompt tuning 기록.
- 내부 운영 runbook, worklog, incident note.
- R2 bucket URL, API key, OAuth token, access token, private key.

기본 prompt resource 파일은 앱이 로컬에서 동작하도록 둔 샘플 fallback이다. 운영 품질의 프롬프트는 DB의 `prompt_versions` 또는 private prompt pack으로 주입하는 것을 권장한다.

## 빠른 시작

의존성을 설치한다.

```powershell
uv sync --dev
corepack enable
pnpm install
```

로컬 환경 파일을 만든다.

```powershell
New-Item -ItemType Directory -Force .home-deploy | Out-Null
Copy-Item scripts/local-home/local.env.example .home-deploy/local.env
notepad .home-deploy/local.env
```

MinIO를 시작하고 DB migration을 적용한다.

```powershell
docker compose -f compose.local-infra.yaml up -d
uv run alembic upgrade head
```

API를 실행한다.

```powershell
uv run uvicorn codex_sdk_cli.api.main:app --host 127.0.0.1 --port 8000
```

Ops UI를 실행한다.

```powershell
pnpm --filter codex-sdk-ops-ui dev
```

## CLI 예시

```powershell
uv run codex-demo --help
uv run codex-demo login browser
uv run codex-demo run "이 저장소를 한 문장으로 설명해줘."
uv run codex-demo run --persist "이 thread를 저장해줘."
uv run codex-demo run --thread-id <thread-id> "앞선 답변을 이어서 정리해줘."
uv run codex-demo account
```

운영 보조 CLI:

```powershell
uv run codex-demo ops detect-stuck --task micro_event_extract --minutes 15
uv run codex-demo ops detect-stuck --task timeline_compose --minutes 15
```

## API 진입점

로컬 API 주소:

```text
http://127.0.0.1:8000
```

주요 endpoint group:

- `/codex/*`
- `/streamers`, `/channels`, `/channels/{id}/videos`
- `/youtube-transcripts/*`
- `/video-tasks/*`
- `/videos/{id}/micro-event-extractions/*`
- `/videos/{id}/timelines/*`
- `/pipeline/jobs/*`
- `/ops/*`

OpenAPI 문서:

```text
http://127.0.0.1:8000/docs
http://127.0.0.1:8000/openapi.json
```

선택한 video를 micro-event, timeline, publish까지 처리하는 API 예시:

```powershell
$body = @{
  videoIds = @(1, 2, 3)
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
  -Uri "http://127.0.0.1:8000/video-tasks/process-to-publish" `
  -ContentType "application/json" `
  -Body $body
```

## 아키텍처

```text
src/codex_sdk_cli/
├── api/                  # FastAPI app, routes, dependency composition
├── domains/              # use cases, DTOs, ports
├── infra/                # SQLAlchemy, external clients, Codex adapters
├── workers/              # DB polling workers
├── cli.py                # Click command entrypoint
├── runner.py             # Codex SDK helper
└── settings.py           # CODEX_CLI_ settings
```

Route handler는 얇게 유지하고, 업무 흐름은 domain use case에 둔다. Infrastructure adapter는 Protocol port를 구현한다. DB schema 변경은 Alembic migration으로만 수행한다.

## 설정

환경변수 prefix는 `CODEX_CLI_`다. 로컬 기본값은 [scripts/local-home/local.env.example](scripts/local-home/local.env.example)에 있다.

자주 쓰는 설정:

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

`.home-deploy/local.env`는 secret을 포함할 수 있으므로 commit하지 않는다.

## 검증

백엔드:

```powershell
uv run pytest
uv run ruff check src tests
uv run pyrefly check --min-severity warn
uv run python scripts/export_openapi.py --check
```

프론트엔드:

```powershell
pnpm --filter codex-sdk-ops-ui api:check
pnpm --filter codex-sdk-ops-ui lint
pnpm --filter codex-sdk-ops-ui typecheck
pnpm --filter codex-sdk-ops-ui test
pnpm --filter codex-sdk-ops-ui build
```

## 문서

- [docs/PROJECT_OVERVIEW.md](docs/PROJECT_OVERVIEW.md): 프로젝트 구조와 API 목록.
- [docs/YOUTUBE_DATA_PIPELINE.md](docs/YOUTUBE_DATA_PIPELINE.md): 파이프라인 상태와 데이터 수명주기.
- [docs/LOCAL_NATIVE_DEPLOYMENT.md](docs/LOCAL_NATIVE_DEPLOYMENT.md): 로컬 네이티브 런타임.
- [docs/ARCHIVE_PUBLISH.md](docs/ARCHIVE_PUBLISH.md): archive object layout과 publish API.
- [docs/ARCHITECTURE_LINTING.md](docs/ARCHITECTURE_LINTING.md): import boundary 검증.
- [ops-ui/docs/FRONTEND_ARCHITECTURE.md](ops-ui/docs/FRONTEND_ARCHITECTURE.md): Ops UI 구조.
