# Codex YouTube Pipeline

OpenAI Codex SDK를 사용하는 로컬 YouTube 데이터 파이프라인 프로젝트다. 처음에는 Codex SDK CLI/FastAPI 실험으로 시작했지만, 현재는 Home PC에서 YouTube 영상 메타데이터 수집, transcript/cue 생성, micro-event 추출, timeline 생성, R2 archive publish까지 운영하는 도구로 확장되어 있다.

운영 기준은 로컬 네이티브 런타임이다. API, worker, Ops UI는 Windows 프로세스로 실행하고, MinIO만 Docker로 실행한다. 공개 서버, ngrok, GitHub Actions 배포는 현재 운영 경로가 아니다.

## 현재 런타임

```text
API:              127.0.0.1:8000
Ops UI:           127.0.0.1:3000
MinIO:            127.0.0.1:9000 / 127.0.0.1:9001
SQLite DB:        ./data/app.db
런타임 상태:      ./.home-deploy/
Worker:
  codex-micro-event-worker
  codex-timeline-compose-worker
```

로컬 운영 에이전트는 `http://127.0.0.1:8000` API를 호출한다. 코드 탐색 없이 운영만 할 때는 [docs/AGENT_API_OPERATIONS.md](docs/AGENT_API_OPERATIONS.md)를 먼저 읽는다.

## 주요 기능

- Codex SDK CLI: thread 실행, thread 재개, 로그인, account 확인.
- FastAPI: Codex 실행 API, YouTube 파이프라인 API, 운영 조회 API.
- YouTube 파이프라인:
  - 채널 resolve
  - 최신 영상 메타데이터 수집
  - transcript 수집
  - transcript cue 생성
  - micro-event 추출
  - timeline 구성
  - Cloudflare R2 archive publish
- 운영 워크플로우:
  - `/ops/videos`, `/ops/video-tasks`, `/ops/events`
  - `/ops/candidates/micro-event-ready`
  - `/ops/candidates/timeline-ready`
  - `/ops/codex-usage*`
  - `codex-demo ops detect-stuck`
- Timeline 유지보수:
  - block split patch
  - display copy patch
  - topic cluster copy patch
  - source micro-event copy patch
  - patch 후 selected video republish
- LLM 관측:
  - DB task/job/attempt 상태
  - operation event
  - Codex usage row
  - `.home-deploy/logs/llm-traces/YYYY-MM-DD/` 파일 trace

## 빠른 시작

의존성을 설치한다.

```powershell
uv sync --dev
corepack enable
pnpm install
```

로컬 런타임 환경 파일을 만든다.

```powershell
New-Item -ItemType Directory -Force .home-deploy | Out-Null
Copy-Item scripts/local-home/local.env.example .home-deploy/local.env
notepad .home-deploy/local.env
```

전체 YouTube/R2 파이프라인 운영에 필요한 값:

- `CODEX_CLI_API_KEY` 또는 browser/device login
- `CODEX_CLI_YOUTUBE_DATA_API_KEY`
- `scripts/local-home/local.env.example`의 MinIO 설정
- public artifact publish가 필요하면 R2 archive publish 설정

로컬 런타임을 배포한다.

```powershell
.\scripts\local-home\deploy.ps1
```

시작, 상태 확인, 중지:

```powershell
.\scripts\local-home\start.ps1
.\scripts\local-home\status.ps1
.\scripts\local-home\stop.ps1
```

부팅 후 자동 복구를 등록한다.

```powershell
.\scripts\local-home\register-task.ps1
```

자세한 로컬 런타임 절차는 [docs/LOCAL_NATIVE_DEPLOYMENT.md](docs/LOCAL_NATIVE_DEPLOYMENT.md)를 본다.

## Codex CLI

로그인:

```powershell
uv run codex-demo login browser
uv run codex-demo login device
uv run codex-demo login api-key
```

프롬프트 실행:

```powershell
uv run codex-demo run "이 저장소를 한 문장으로 설명해줘."
```

thread 저장 및 재개:

```powershell
uv run codex-demo run --persist "프로젝트 요약을 작성해줘."
uv run codex-demo run --thread-id <thread-id> "앞선 답변을 이어서 정리해줘."
```

account 확인과 logout:

```powershell
uv run codex-demo account
uv run codex-demo logout
```

운영 CLI 예시:

```powershell
uv run codex-demo ops detect-stuck --task micro_event_extract --minutes 15
uv run codex-demo ops detect-stuck --task timeline_compose --minutes 15
```

## 자주 쓰는 API 흐름

기본 API 주소:

```powershell
$base = "http://127.0.0.1:8000"
```

health와 운영 요약:

```powershell
Invoke-RestMethod "$base/health"
Invoke-RestMethod "$base/ops/summary"
```

채널의 최신 영상 메타데이터 수집:

```powershell
Invoke-RestMethod -Method Post "$base/channels/1/videos/collect"
```

transcript 수집과 cue 생성:

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

선택한 영상을 micro-event, timeline, publish까지 처리:

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

이미 timeline이 준비된 영상을 재구성 없이 publish:

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

한국어 문구나 public copy를 요청 body에 넣을 때는 PowerShell 인코딩 문제를 피하기 위해 `scripts/local-home/common.ps1`의 `Invoke-JsonUtf8`을 사용한다.

세부 운영 recipe는 `docs/agent-api-operations/` 아래 문서에 있다.

## 데이터 파이프라인 모델

파이프라인 상태는 다음처럼 분리한다.

- `pipeline_jobs`: 사용자가 의도한 논리 작업.
- `pipeline_job_attempts`: job 아래의 실제 실행 1회.
- `video_tasks`: video 단위 durable work item과 worker claim 상태.
- `external_api_calls`: 외부 API 요청/응답 metadata. raw body는 object storage에 저장한다.
- domain table: videos, transcripts, cues, micro-events, timelines 같은 정규화된 결과.
- `operation_events`: 작업 중심 운영 event log.
- `codex_run_usages`: token 사용량과 model/reasoning trace.

Transcript와 외부 API raw JSON은 MinIO에 저장한다. R2 archive publish는 공개 immutable timeline artifact를 쓰고 pointer/index를 갱신한다. LLM raw trace는 `.home-deploy/logs/llm-traces` 아래 파일로 남긴다.

수명주기와 id 연결 규칙은 [docs/YOUTUBE_DATA_PIPELINE.md](docs/YOUTUBE_DATA_PIPELINE.md)를 본다.

## API와 UI 진입점

로컬 진입점:

- FastAPI 문서: `http://127.0.0.1:8000/docs`
- OpenAPI: `http://127.0.0.1:8000/openapi.json`
- Ops UI: `http://127.0.0.1:3000/ops`

주요 route group:

- `/codex/*`
- `/streamers`, `/channels`, `/channels/{id}/videos`
- `/video-tasks/*`
- `/youtube-transcripts/*`
- `/videos/{id}/micro-event-extractions/*`
- `/videos/{id}/timelines/*`
- `/pipeline/jobs/*`
- `/ops/*`

Route handler는 얇게 유지한다. 업무 흐름은 domain use case에 두고, infrastructure adapter는 `src/codex_sdk_cli/infra/` 아래에 둔다. SQL schema 변경은 Alembic migration으로만 처리한다.

## 설정

환경변수는 `CODEX_CLI_` prefix를 사용한다. 대부분의 로컬 기본값은 [scripts/local-home/local.env.example](scripts/local-home/local.env.example)에 있다.

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

Ops UI 설정:

- `CODEX_OPS_BACKEND_BASE_URL`
- `HOSTNAME`
- `PORT`

`.home-deploy/local.env`는 secret을 포함할 수 있으므로 commit하지 않는다.

## 데이터베이스

이 프로젝트는 async SQLAlchemy와 Alembic을 사용한다.

```powershell
uv run alembic check
uv run alembic revision --autogenerate -m "create <name>"
uv run alembic upgrade head
```

앱 코드, 테스트, startup hook에서 `metadata.create_all()` 또는 `metadata.drop_all()`을 호출하지 않는다.

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

좁은 백엔드 변경은 관련 pytest target과 `ruff check src tests`를 우선 실행한다.

## 문서 지도

- [docs/PROJECT_OVERVIEW.md](docs/PROJECT_OVERVIEW.md): 프로젝트 구조와 API 목록.
- [docs/YOUTUBE_DATA_PIPELINE.md](docs/YOUTUBE_DATA_PIPELINE.md): 파이프라인 상태와 데이터 수명주기.
- [docs/LOCAL_NATIVE_DEPLOYMENT.md](docs/LOCAL_NATIVE_DEPLOYMENT.md): 현재 Home PC 런타임.
- [docs/AGENT_API_OPERATIONS.md](docs/AGENT_API_OPERATIONS.md): API-only 운영 가이드.
- [docs/ARCHIVE_PUBLISH.md](docs/ARCHIVE_PUBLISH.md): R2 archive object layout과 publish API.
- [docs/CICD.md](docs/CICD.md): 수동 GitHub Actions 상태.
- [ops-ui/docs/FRONTEND_ARCHITECTURE.md](ops-ui/docs/FRONTEND_ARCHITECTURE.md): Ops UI 구조.

기존 Docker, AWS, GHCR, nginx, ngrok 자료는 참고용으로만 `legacy/` 아래에 남아 있다.
