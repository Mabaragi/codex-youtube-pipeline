# Codex SDK CLI Demo 프로젝트 설명

## 한 줄 요약

이 프로젝트는 OpenAI Codex Python SDK를 이용해 Codex thread 실행, thread 재개, 로그인, 계정 확인을 터미널 명령과 REST API로 해보고, YouTube transcript 저장과 streamer/channel metadata 관리를 함께 실험하는 작은 Python 예제다.

## 왜 만들었나

Codex SDK는 애플리케이션 안에서 Codex를 programmatic하게 제어할 때 쓴다. 이 저장소는 SDK 사용법을 복잡한 서비스에 넣기 전에 CLI와 FastAPI 형태로 작게 검증하기 위한 예제다.

## 무엇을 할 수 있나

`codex-demo` 명령은 다음 작업을 지원한다.

- 새 Codex thread를 만들고 prompt 실행.
- 기존 thread id로 대화 이어가기.
- ChatGPT browser login.
- ChatGPT device-code login.
- API key login.
- 현재 Codex account 상태 JSON 출력.
- Codex account logout.

`codex-api`는 다음 REST endpoint 계열을 제공한다.

- `POST /codex/runs`: prompt와 optional instructions 요청으로 새 thread를 실행한다.
- `GET /codex/account`: 현재 account 상태 확인.
- `POST /codex/login/device-code`: device-code login 실행.
- `POST /codex/login/api-key`: API key 로그인.
- `POST /codex/logout`: account logout.
- `GET /pipeline/jobs`, `GET /pipeline/jobs/{id}`: pipeline job 목록과 상세 attempts/raw calls/domain outputs를 조회한다.
- `POST /pipeline/jobs/{id}/retry`: 실패한 pipeline job을 같은 job 아래 새 attempt로 재시도한다. 현재 `channel_resolve`, `video_collect`, `transcript_collect`, `transcript_cue_generate`, `micro_event_extract`, `timeline_compose`를 지원한다.
- `POST /streamers`, `GET /streamers`, `GET/PATCH/DELETE /streamers/{id}`: streamer metadata CRUD.
- `POST /streamers/{id}/channels`, `GET /streamers/{id}/channels`: 특정 streamer에 속한 channel 생성과 목록 조회.
- `GET /channels`, `GET/PATCH/DELETE /channels/{id}`: channel metadata 조회/수정/삭제.
- `POST /streamers/{id}/channels/resolve`: 등록된 streamer에 붙일 YouTube handle을 공식 YouTube Data API로 resolve하고 pipeline job/attempt 및 raw 응답 metadata를 남긴 뒤 `channels` row 하나를 생성하거나 같은 streamer의 기존 row를 재사용한다.
- `POST /channels/{id}/videos/collect`: local channel row의 uploads playlist ID로 `playlistItems.list` 최신순 수집을 실행하고, 기존 video를 만나면 중단하며, `videos.list(part=contentDetails)`로 duration metadata와 raw API call metadata를 남긴다.
- `GET /channels/{id}/videos`: 저장된 video metadata를 `publishedAt desc` 순서로 조회한다.
- `POST /video-tasks/transcript-collect`, `POST /channels/{id}/video-tasks/transcript-collect`: 저장된 videos를 전체 또는 채널 단위로 고른 뒤 `video_tasks` 상태를 기준으로 transcript 수집을 순차 실행한다. `no_transcript`는 generic failure와 분리된 terminal 상태다.
- `POST /video-tasks/transcript-cue-generate`, `POST /channels/{id}/video-tasks/transcript-cue-generate`: succeeded transcript task의 output transcript에서 prompt-friendly cue row를 생성한다.
- `GET /channels/{id}/video-tasks`: 저장된 video task rows를 `taskName`, `status`, `limit`, `offset`으로 조회한다.
- `POST /videos/{id}/video-tasks/micro-event-extract`: 단일 video의 cue-ready transcript를 30분 기본 window로 나눠 micro-event 후보와 ASR correction 후보를 추출한다.
- `POST /video-tasks/micro-event-extract`: 최신 cue-ready videos 중 제한된 개수를 request 안에서 즉시 처리한다.
- `POST /video-tasks/micro-event-extract/enqueue`: selected/current-filter/next-eligible videos에 `micro_event_extract` pending task를 예약한다.
- `GET /videos/{id}/micro-event-extractions/latest`, `GET /videos/{id}/micro-event-extractions/{videoTaskId}`: 저장된 micro-event extraction detail을 조회한다.
- `POST /video-tasks/timeline-compose/enqueue`: succeeded micro-event task를 가진 videos에 `timeline_compose` pending task를 예약한다.
- `GET /videos/{id}/timelines/latest`, `GET /videos/{id}/timelines/{videoTaskId}`: 저장된 timeline summary, blocks, episodes, topic clusters, review flags, validation warnings를 조회한다.
- `POST /youtube-transcripts`: YouTube URL 또는 video ID로 captions/subtitles를 조회하고 응답 JSON을 MinIO에 저장한 뒤 DB에 메타데이터와 object 경로를 저장한다.
- `GET /youtube-transcripts`: 저장된 transcript metadata를 조회한다.
- `GET /youtube-transcripts/{id}`: 저장된 transcript metadata 단건을 조회한다.
- `GET /youtube-transcripts/{id}/content`: 저장된 transcript metadata와 원본 segment content를 조회한다.
- `GET /youtube-transcripts/{id}/cues`: 저장된 transcript에서 생성된 cue 목록과 timing metadata를 조회한다.
- `GET /youtube-transcripts/{id}/prompt-cues`: LLM prompt에 넣기 좋은 `cueId + text` payload를 조회한다. timing 값은 포함하지 않는다.
- `POST /youtube-transcripts/{id}/cues/generate`: 저장된 transcript JSON을 읽어 cue row를 생성하거나 재생성한다.
- `PATCH /youtube-transcripts/{id}`: 저장된 transcript metadata의 `notes`만 수정한다.
- `DELETE /youtube-transcripts/{id}`: 저장된 transcript metadata row만 삭제한다.
- `/domain-entry-types`, `/domain-entries`, `/domain-entries/{id}/aliases`, `/domain-entries/{id}/streamers`: LLM prompt에 주입할 domain knowledge entry/type/alias/scope를 관리한다.
- `/ops/summary`, `/ops/channels`, `/ops/videos`, `/ops/videos/{id}`, `/ops/video-tasks`, `/ops/schema-graph`, `/ops/events`: Ops UI와 API-only operator용 조회 projection과 operation event log를 제공한다.
- `/ops/codex-usage`, `/ops/codex-usage/by-video`, `/ops/codex-usage/by-job`: Codex runtime usage/token 기록을 조회한다.
- `GET /health`: API health check.
- `GET /health/s3`: 컨테이너에서 보이는 `/data/s3` mount 상태 진단.

DB persistence는 async SQLAlchemy와 Alembic으로 관리한다. 현재
`streamers`, `channels`, `videos`, `youtube_transcripts`, `transcript_cues`,
`video_tasks`, `pipeline_jobs`, `pipeline_job_attempts`, `external_api_calls`,
`operation_events`, `codex_run_usages`, `domain_entries`,
`domain_entry_aliases`, `domain_entry_streamers`, `domain_entry_types`,
`micro_event_extraction_windows`, `micro_event_candidates`,
`micro_event_excluded_ranges`, `asr_correction_candidates`,
`timeline_compositions`, `timeline_blocks`, `timeline_episodes`,
`timeline_topic_clusters`, `timeline_review_flags` 테이블을 사용한다.
Raw transcript, external API, and Codex response content는 필요한 경우 MinIO나
raw response text/hash로 분리하고, SQLite에는 운영 조회와 재시도에 필요한 metadata와
normalized domain row를 저장한다.

## 실행 예시

의존성을 설치한다.

```powershell
uv sync --dev
```

도움말을 확인한다.

```powershell
uv run codex-demo --help
uv run codex-demo run --help
```

브라우저 로그인 후 새 ephemeral thread를 실행한다.

```powershell
uv run codex-demo login browser
uv run codex-demo run "이 저장소를 한 문장으로 설명해줘"
```

나중에 이어갈 thread는 생성 시점에 명시적으로 저장한다.

```powershell
uv run codex-demo run --persist "이 저장소를 한 문장으로 설명해줘"
```

기존 thread를 이어간다.

```powershell
uv run codex-demo run --thread-id <thread-id> "방금 답변을 더 짧게 요약해줘"
```

읽기 전용으로 실행한다.

```powershell
uv run codex-demo run --sandbox read-only --approval deny-all "이 프로젝트 구조를 검토해줘"
```

SDK 기본 base instructions 없이 실험하려면 빈 base instructions override를 보낸다.

```powershell
uv run codex-demo run --empty-base-instructions "짧게 답해줘"
uv run codex-demo run --empty-developer-instructions "짧게 답해줘"
```

FastAPI 앱을 로컬에서 import 확인한다.

```powershell
uv run python -c "from codex_sdk_cli.api.main import app; print(app.title)"
```

로컬 네이티브 API를 실행한다.

```powershell
uv run uvicorn codex_sdk_cli.api.main:app --host 127.0.0.1 --port 8000
```

Home PC deployment is local native. MinIO runs in Docker, while the API,
workers, and optional Ops UI run as Windows processes. There is no public ngrok
URL or GitHub-driven deploy. See `docs/LOCAL_NATIVE_DEPLOYMENT.md`.

YouTube 자막 조회 API는 URL과 raw video ID를 모두 받는다.

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://localhost:8000/youtube-transcripts `
  -ContentType "application/json" `
  -Body '{"video":"https://www.youtube.com/watch?v=dQw4w9WgXcQ","languages":["ko","en"],"preserveFormatting":false}'
```

저장된 metadata row는 같은 `/youtube-transcripts` resource에서 list/get/patch/delete
한다. 삭제는 SQLite metadata row만 제거하고 MinIO raw JSON은 남긴다.

## 코드 구조

```text
src/codex_sdk_cli/
├── api/             # FastAPI app, dependency composition, exception handlers
├── domains/codex/   # Codex domain router, schemas, use cases, ports
├── domains/codex_usage/ # Codex runtime usage list/aggregate API
├── domains/domain_knowledge/ # LLM prompt domain entry/type/alias API
├── domains/external_api_calls/ # 외부 API raw response metadata ports/exceptions
├── domains/micro_events/ # transcript cue 기반 micro-event extraction API
├── domains/operation_events/ # 작업 중심 operation event log API
├── domains/ops/ # Ops UI read-model API
├── domains/pipeline_jobs/ # pipeline job/attempt 상태 ports/exceptions
├── domains/channels/ # Channel API router, schemas, use cases, ports
├── domains/videos/ # YouTube video 수집 API router, schemas, use cases, ports
├── domains/video_tasks/ # Video 단위 manual task API, schemas, use cases, ports
├── domains/streamers/ # Streamer API router, schemas, use cases, ports
├── domains/timelines/ # micro-event 후보 기반 timeline compose API
├── domains/transcript_cues/ # prompt-friendly transcript cue ports/schemas
├── domains/youtube_data/ # YouTube Data API client ports/exceptions
├── domains/youtube_transcripts/ # YouTube transcript API router, schemas, use cases, ports
├── infra/codex/     # 실제 Codex SDK client adapter
├── infra/codex_usage/ # Codex usage SQLAlchemy repository
├── infra/database/  # SQLAlchemy Base, async engine/session factory
├── infra/domain_knowledge/ # Domain knowledge SQLAlchemy repository
├── infra/external_api_calls/ # raw response object storage recorder와 SQLAlchemy repository
├── infra/micro_events/ # Micro-event repository와 Codex extractor adapter
├── infra/operation_events/ # Operation event SQLAlchemy repository/recorder
├── infra/ops/ # Ops UI read-model SQLAlchemy queries
├── infra/pipeline_jobs/ # pipeline job/attempt SQLAlchemy repository
├── infra/channels/  # Channel SQLAlchemy repository
├── infra/videos/ # Video SQLAlchemy repository
├── infra/video_tasks/ # Video task SQLAlchemy repository
├── infra/streamers/ # Streamer SQLAlchemy repository
├── infra/timelines/ # Timeline composition repository와 Codex composer adapter
├── infra/transcript_cues/ # Transcript cue SQLAlchemy repository
├── infra/youtube_data/ # official YouTube Data API HTTP client
├── infra/youtube_transcripts/   # youtube-transcript-api adapter, MinIO transcript storage
├── workers/         # DB polling workers for queued micro-event and timeline tasks
├── cli.py           # Click command 정의와 사용자 출력
├── runner.py        # Codex SDK 호출 helper와 adapter
├── settings.py      # CODEX_CLI_ 환경변수 설정
└── __main__.py      # python -m codex_sdk_cli 진입점
```

테스트는 `tests/`에 있다.

- `tests/test_cli.py`: Click CLI command가 올바르게 동작하는지 fake Codex client로 검증한다.
- `tests/test_runner.py`: SDK enum mapping, thread start/resume 분기, login helper를 검증한다.
- `tests/test_api.py`: FastAPI route가 use case와 fake infra port를 통해 동작하는지 검증한다.
- `tests/test_database.py`: DB 설정, async session, Alembic migration 적용을 검증한다.
- `tests/test_external_api_calls_repository.py`: 외부 API raw metadata repository와 pipeline attempt 연결을 검증한다.
- `tests/test_external_api_calls_storage.py`: 외부 API raw response MinIO storage boundary를 검증한다.
- `tests/test_domain_knowledge_api.py`, `tests/test_domain_knowledge_repository.py`: prompt domain entry/type/alias/scope API와 repository를 검증한다.
- `tests/test_micro_events_api.py`, `tests/test_micro_events_repository.py`: micro-event task selection, Codex output normalization, window/candidate persistence를 검증한다.
- `tests/test_timelines_api.py`, `tests/test_timelines_use_cases.py`, `tests/test_timeline_worker.py`: timeline enqueue, composition normalization/repair, worker claim flow를 검증한다.
- `tests/test_ops_api.py`, `tests/test_ops_repository.py`: Ops UI read-model API를 검증한다.
- `tests/test_codex_usage_repository.py`: Codex usage aggregation과 filtering을 검증한다.
- `tests/test_pipeline_jobs_repository.py`: pipeline job/attempt repository lifecycle을 검증한다.
- `tests/test_streamers_api.py`: Streamer CRUD, channel CRUD, streamer-scoped resolve route, exception mapping을 검증한다.
- `tests/test_streamer_repository.py`: Streamer와 channel SQLAlchemy repository를 검증한다.
- `tests/test_youtube_data_api.py`: YouTube Data client를 사용하는 channel resolve flow와 pipeline job 연결을 검증한다.
- `tests/test_youtube_data_client.py`: official YouTube Data API client boundary와 channel/search/video response DTO 검증을 확인한다.
- `tests/test_youtube_videos_api.py`: channel 기반 video collect/list API와 `video_collect` retry를 검증한다.
- `tests/test_videos_repository.py`: Video SQLAlchemy repository insert/list/existing lookup을 검증한다.
- `tests/test_video_tasks_api.py`: channel 기반 transcript collect selector, `video_tasks` 중복 방지, timeout, retry API를 검증한다.
- `tests/test_video_tasks_repository.py`: Video task SQLAlchemy repository create/list/state transition을 검증한다.
- `tests/test_youtube_transcripts_api.py`: YouTube transcript fetch와 metadata CRUD API를 검증한다.
- `tests/test_youtube_transcripts_repository.py`: YouTube transcript metadata repository insert/update/list/get/patch/delete를 검증한다.
- `tests/test_youtube_transcripts_storage.py`: MinIO transcript storage boundary를 검증한다.

## 동작 흐름

`run` 명령을 실행하면 흐름은 다음과 같다.

1. `cli.py`가 command option과 prompt를 읽는다.
2. `settings.py`의 `CliSettings`가 `CODEX_CLI_` 환경변수 기본값을 적용한다.
3. `runner.py`가 sandbox와 approval 문자열을 SDK enum으로 변환한다.
4. thread id가 없으면 `thread_start`, 있으면 `thread_resume`을 호출한다.
5. `thread.run(prompt)` 결과에서 `thread_id`, `turn_id`, `status`, final response를 출력한다.

새 thread는 기본적으로 `ephemeral=True`로 생성한다. Codex SDK schema 기준으로 ephemeral thread는 디스크에 materialize하지 않는 thread다. 장기 재사용이 필요한 경우 `--persist`를 지정하면 `ephemeral=False`로 생성한다. `--thread-id`로 resume할 때는 기존 thread의 저장 상태를 바꾸지 않으므로 `--persist`는 동작에 영향을 주지 않는다.

`--empty-base-instructions`와 `--empty-developer-instructions`를 지정하면 `thread_start` 또는 `thread_resume`에 blank instruction override를 전달한다. 실제 빈 문자열은 turn 실행 시점에 SDK 서버가 거절하므로, CLI는 공백 override로 SDK 기본 instructions를 대체한다. 지정하지 않으면 `None`으로 두어 SDK 기본값을 그대로 사용한다.

REST API는 route handler를 얇게 유지한다. `router.py`는 HTTP DTO를 받고 use case를 호출한다. Codex use case는 `CodexRuntimePort` Protocol에만 의존하고, 실제 SDK 호출은 `infra/codex/client.py`의 `CodexRuntimeClient`가 담당한다. Channel use case는 `ChannelRepositoryPort`, `StreamerRepositoryPort`, `PipelineJobRepositoryPort`, YouTube Data client projection에 의존해 `channel_resolve` job/attempt와 local channel row 하나를 연결한다. Video collect use case는 local channel row의 `uploads_playlist_id`로 `playlistItems.list` 최신순 page를 가져오고 기존 video를 만나면 중단한 뒤, 새 candidates를 `videos.list(part=contentDetails)` duration metadata로 보강해 `videos` row와 raw API call metadata를 연결한다. YouTube Data client는 official channel/playlist/video metadata를 조회하면서 raw 응답을 MinIO에 저장하고 `external_api_calls` metadata row를 남긴 뒤 projection만 반환한다. Transcript, cue, micro-event, timeline 단계는 `video_tasks`가 중복 방지와 durable status를 소유하고, `pipeline_jobs`/`pipeline_job_attempts`가 실행 이력을 기록한다. Micro-event와 timeline queue는 FastAPI 프로세스가 아니라 `workers/`의 별도 DB polling process가 pending task를 claim한다. Pipeline retry use case는 failed job의 저장된 입력을 step별 lazy executor registry로 넘겨 지원 step을 같은 job 아래 새 attempt로 재실행한다. YouTube transcript use case도 `YouTubeTranscriptPort`, `YouTubeTranscriptStoragePort`, `YouTubeTranscriptRepositoryPort` Protocol에 의존한다. 실제 captions 조회는 `infra/youtube_transcripts/client.py`가 `youtube-transcript-api`를 통해 처리하고, 응답 JSON 저장은 `infra/youtube_transcripts/storage.py`가 MinIO에 기록하며, 저장 위치와 메타데이터 CRUD는 `infra/youtube_transcripts/repository.py`가 DB에 기록한다.

## 설정

환경변수는 `CODEX_CLI_` prefix를 사용한다.

- `CODEX_CLI_MODEL`: Codex model. Default `gpt-5.5`; allowed values are `gpt-5.5`, `gpt-5.4`, `gpt-5.4-mini`.
- `CODEX_CLI_REASONING_EFFORT`: Codex reasoning effort. Default `medium`; allowed values are `low`, `medium`, `high`, `xhigh`.
- `CODEX_CLI_SANDBOX`: `read-only`, `workspace-write`, `full-access`.
- `CODEX_CLI_APPROVAL`: `auto-review`, `deny-all`.
- `CODEX_CLI_CODEX_BIN`: 특정 local Codex binary를 강제로 사용할 때 지정.
- `CODEX_CLI_API_KEY`: `login api-key`의 기본 API key.
- `CODEX_CLI_YOUTUBE_HTTP_PROXY`: YouTube transcript 요청에 사용할 HTTP proxy.
- `CODEX_CLI_YOUTUBE_HTTPS_PROXY`: YouTube transcript 요청에 사용할 HTTPS proxy.
- `CODEX_CLI_YOUTUBE_DATA_API_KEY`: official YouTube Data API key.
- `CODEX_CLI_YOUTUBE_DATA_TIMEOUT_SECONDS`: YouTube Data API timeout. 기본값은 `10`.
- `CODEX_CLI_TRANSCRIPT_MINIO_ENDPOINT`: transcript JSON을 저장할 MinIO endpoint.
- `CODEX_CLI_TRANSCRIPT_MINIO_ACCESS_KEY`: MinIO access key.
- `CODEX_CLI_TRANSCRIPT_MINIO_SECRET_KEY`: MinIO secret key.
- `CODEX_CLI_TRANSCRIPT_MINIO_BUCKET`: transcript JSON bucket.
- `CODEX_CLI_TRANSCRIPT_MINIO_PREFIX`: object key prefix. 기본값은 `youtube/transcripts`.
- `CODEX_CLI_TRANSCRIPT_MINIO_SECURE`: MinIO HTTPS 사용 여부. 기본값은 `false`.
- `CODEX_CLI_TRANSCRIPT_COLLECT_TIMEOUT_SECONDS`: manual `transcript_collect` task timeout. 기본값은 `600`.
- `CODEX_CLI_TRANSCRIPT_COLLECT_CONCURRENCY_LIMIT`: manual `transcript_collect` 동시 실행 제한. 기본값은 `1`.
- `CODEX_CLI_TRANSCRIPT_COLLECT_DELAY_SECONDS`: manual `transcript_collect` 실제 fetch 사이 대기 시간. 기본값은 `300`. 기존 metadata 재사용이나 `no_transcript` 처리 뒤에는 불필요한 delay를 두지 않는다.
- `CODEX_CLI_TRANSCRIPT_CUE_GENERATE_TIMEOUT_SECONDS`: `transcript_cue_generate` task timeout. 기본값은 `600`.
- `CODEX_CLI_TRANSCRIPT_CUE_GENERATE_CONCURRENCY_LIMIT`: `transcript_cue_generate` 동시 실행 제한. 기본값은 `1`.
- `CODEX_CLI_MICRO_EVENT_EXTRACT_TIMEOUT_SECONDS`: `micro_event_extract` video task timeout. 기본값은 `3600`.
- `CODEX_CLI_MICRO_EVENT_EXTRACT_CONCURRENCY_LIMIT`: `micro_event_extract` 한 영상 작업 안에서 동시에 처리할 window worker 수. 앱 기본값은 `3`, local native env 예시는 `6`.
- `CODEX_CLI_MICRO_EVENT_WORKER_POLL_INTERVAL_SECONDS`: micro-event worker DB polling interval. 기본값은 `5`.
- `CODEX_CLI_MICRO_EVENT_WORKER_ID`: micro-event worker id override.
- `CODEX_CLI_TIMELINE_COMPOSE_TIMEOUT_SECONDS`: `timeline_compose` video task timeout. 기본값은 `3600`.
- `CODEX_CLI_TIMELINE_COMPOSE_WORKER_POLL_INTERVAL_SECONDS`: timeline compose worker DB polling interval. 기본값은 `5`.
- `CODEX_CLI_TIMELINE_COMPOSE_WORKER_ID`: timeline compose worker id override.
- `CODEX_CLI_EXTERNAL_API_CALL_MINIO_PREFIX`: 외부 API raw response object key prefix. 기본값은 `external-api-calls`.
- `CODEX_CLI_DATABASE_URL`: SQLAlchemy async DB URL. 앱 기본값과 local native 기본값은
  `sqlite+aiosqlite:///./data/app.db`다.
- `CODEX_CLI_DATABASE_ECHO`: SQLAlchemy SQL echo 여부. 기본값은 `false`.

## 중요한 구현 선택

Click command 함수는 일부러 얇게 유지한다. CLI에서 직접 SDK를 많이 만지면 테스트가 어려워지기 때문에 실제 작업은 `runner.py`의 함수로 넘긴다.

`runner.py`는 `CodexLike`, `ThreadLike`, login handle Protocol을 둔다. 실제 SDK 객체는 `AsyncCodex`를 사용하는 `CodexSdkAdapter`가 감싸고, 테스트에서는 async fake 객체를 넣는다. 덕분에 자동 테스트가 실제 로그인이나 Codex runtime을 띄우지 않는다.

`openai-codex`는 베타 SDK이고 prerelease runtime dependency가 필요하다. 그래서 `pyproject.toml`에는 `[tool.uv] prerelease = "allow"`가 들어 있다.

DB schema 변경은 Alembic migration으로만 수행한다. 앱 코드, 테스트 fixture,
startup hook에서 `metadata.create_all()`이나 `metadata.drop_all()`을 호출하지
않는다. Alembic scaffold는 `Base.metadata`를 target metadata로 사용하고,
현재 migration chain은 `youtube_transcripts`, `streamers`, `channels`,
`external_api_calls`, `pipeline_jobs`, `pipeline_job_attempts`, `videos`,
`video_tasks`, `transcript_cues`, `operation_events`, `codex_run_usages`,
domain knowledge, micro-event, timeline 테이블과 pipeline/raw metadata 연결 컬럼을 생성한다.

```powershell
uv run alembic check
uv run alembic revision --autogenerate -m "create <name>"
uv run alembic upgrade head
```

## 검증 방법

자동 검증은 다음 명령을 사용한다.

```powershell
uv run pytest
uv run ruff check .
uv run pyrefly check --min-severity warn
```

Pydantic DTO와 dataclass의 마이크로벤치마크는 기본 테스트에서 제외되어 있다. 필요할 때 명시적으로 실행한다.

```powershell
uv run pytest -m performance -s tests/test_pydantic_model_performance.py
```

실제 Codex SDK 호출은 인증 상태와 local runtime에 의존하므로 수동으로 확인한다.

```powershell
uv run codex-demo account
uv run codex-demo run --sandbox read-only "이 저장소를 한 문장으로 설명해줘"
uv run codex-demo run --persist --sandbox read-only "이 thread를 나중에 이어갈 수 있게 실행해줘"
.\scripts\local-home\start.ps1
```

## 확장 아이디어

- `run --json` 옵션을 추가해 결과를 machine-readable하게 출력.
- 대화형 REPL 모드 추가.
- thread 목록 조회나 archive/unarchive 명령 추가.
- streaming progress 출력 추가.
- config file support 추가.
- long-running REST job 상태 저장과 polling endpoint 추가.
