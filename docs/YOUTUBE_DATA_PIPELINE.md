# YouTube Data Pipeline

Last updated: 2026-06-25

이 문서는 YouTube channel resolve부터 videos, transcripts, cues, micro-events, timeline compose까지 이어지는 데이터 파이프라인의 공통 설계 원칙을 정리한다. 특정 endpoint 구현 절차보다, 앞으로 새 수집/가공 단계를 추가할 때 따라야 하는 상태 추적과 데이터 연결 규칙을 우선한다.

## Target Flow

1. 사용자가 streamer를 수동 등록한다.
2. streamer에 연결할 YouTube channel을 resolve한다.
3. channel 기반으로 videos를 수집한다.
4. video 기반으로 transcripts를 수집한다.
5. transcript 기반으로 prompt-friendly cue row를 생성한다.
6. transcript cue 기반으로 micro-event 후보와 ASR 보정 후보를 추출한다.
7. micro-event 후보 기반으로 사용자 탐색용 timeline composition을 생성한다.
8. 작업 이력, operation events, Codex usage를 운영 UI/API에서 조회한다.

각 단계는 동기 REST API, 수동 실행, 또는 DB polling worker queue로 실행될 수 있다. 실행 방식이 달라도 job/attempt/raw/domain row 연결 규칙은 동일해야 한다.

## Core Model

파이프라인은 네 종류의 데이터를 분리한다.

- `pipeline_jobs`: 사용자가 의도한 논리 작업이다. 예: 한 streamer의 channel resolve, 한 channel의 videos collect, 한 video의 transcript collect.
- `pipeline_job_attempts`: job을 실제로 실행한 1회 시도다. retry가 생기면 같은 job 아래에 attempt가 추가된다.
- `external_api_calls`: 외부 API 요청/응답 metadata다. raw response body는 object storage에 저장하고, DB에는 저장 위치, hash, 검증 상태, sanitized request metadata만 둔다.
- `video_tasks`: video 단위 durable work item이다. 수동 channel API가 대상을 고르더라도 중복 방지와 완료 상태는 이 row가 소유한다.
- Domain tables: `channels`, `videos`, `youtube_transcripts`,
  `transcript_cues`, `micro_event_extraction_windows`,
  `micro_event_candidates`, `asr_correction_candidates`,
  `timeline_compositions`, `timeline_blocks`, `timeline_episodes`,
  `timeline_topic_clusters`, `timeline_review_flags`처럼
  애플리케이션이 사용하는 정규화 결과다.
- `operation_events`와 `codex_run_usages`: 작업 timeline과 Codex token usage를
  관측하기 위한 운영 read model이다. 원본 데이터의 source of truth를 대체하지 않는다.

연결 방향은 다음을 기본으로 한다.

- attempt는 반드시 하나의 job에 속한다.
- external API call은 가능하면 해당 attempt를 참조한다.
- domain row는 자신을 만든 job과 필요한 raw metadata row를 참조한다.
- raw JSON body를 domain table에 직접 크게 저장하지 않는다.

## Identity Rules

- local DB row id와 외부 플랫폼 id는 이름으로 구분한다.
- local id는 `channelId`, `videoId`, `transcriptId`, `jobId`, `jobAttemptId`처럼 표현한다.
- YouTube id는 `youtubeChannelId`, `youtubeVideoId`처럼 외부 출처가 드러나는 이름을 사용한다.
- 외부 id를 사용자가 입력하지 않아야 하는 단계에서는 외부 API 응답에서 검증된 값만 저장한다.

## Job Lifecycle

새 pipeline step은 입력을 normalize하고 최소 validation을 통과한 뒤 job을 만든다. 아직 작업 대상 domain row가 생성되기 전이면 `subject_type`과 `subject_id`는 현재 알고 있는 상위 local row를 가리켜도 된다. Channel resolve는 streamer가 현재 subject이고, 성공 후 channel row가 output이 된다. Video collect부터는 channel이 subject다.

권장 job status:

- `pending`: 실행 대기 중.
- `running`: 현재 실행 중.
- `succeeded`: 모든 필수 output과 연결 row가 저장됨.
- `failed`: 실행이 실패했고 error metadata가 attempt에 남음.
- `skipped`: 실행 조건상 처리하지 않기로 결정됨.
- `canceled`: 사용자나 시스템에 의해 중단됨.

권장 attempt status:

- `running`: 실행 중.
- `succeeded`: 이 시도에서 필요한 output 저장이 완료됨.
- `failed`: 이 시도가 실패함.
- `canceled`: 이 시도가 중단됨.

실패한 attempt는 `error_type`, `error_message`를 남긴다. 재시도는 기존 attempt를 덮어쓰지 않고 새 attempt로 추가한다.

## Step Output Rules

각 단계는 현재 use case에 필요한 projection만 반환하고, raw response 전체는 object storage와 `external_api_calls`로 추적한다.

- Channel resolve output: normalized channel row, YouTube channel id, uploads playlist id, source API call metadata.
- Videos collect output: normalized video rows, source listing/details API call metadata.
- Transcript collect output: transcript metadata row, raw transcript storage metadata.
- Transcript cue generate output: transcript row에서 파생된 cue count와 cue id 범위다. 원본 transcript JSON은 storage에 유지하고, DB cue row는 prompt/후처리용 식별 단위다.
- Micro-event extract output: stored cue window 범위별 raw Codex response와
  정규화된 `micro_event_candidates`, `asr_correction_candidates` 후보 row다.
  최종 timeline/chapter/summary는 만들지 않고 후속 merge 단계가 재구성할 수
  있도록 cue id 범위와 후보만 저장한다.
- Timeline compose output: video summary, blocks, episodes, topic clusters,
  review flags, validation warnings, raw model text, and normalized output JSON.
  복구 가능한 LLM 출력 흔들림은 실패 대신 warning으로 남기고, micro-event coverage나
  block membership 같은 hard invariant가 깨질 때만 실패한다.
  Failed timeline attempts store raw Codex diagnostics in
  `pipeline_job_attempts.output_json.rawResponses[*].rawResponseText`; video task
  output and operation events keep only response count, length, hash, and storage
  pointer fields.

API 응답에는 사용자가 다음 상태를 추적할 수 있도록 필요한 local identifiers를 포함할 수 있다. pipeline step을 실행하는 endpoint는 가능하면 `jobId`, `jobAttemptId`, 그리고 raw metadata id를 응답에 포함한다.

## Operational APIs

운영 API는 pipeline state를 직접 수정하는 작업을 최소화하고, 먼저 관측 가능성을
제공한다.

- `GET /pipeline/jobs`: 최근 job 목록을 조회한다. `step`, `status`,
  `subjectType`, `subjectId`, `externalKey`, `cursor`, `limit` 필터를 지원하고,
  latest attempt 상태와 attempt count를 함께 반환한다.
- `GET /pipeline/jobs/{jobId}`: 단일 job의 입력, attempts, 연결된
`external_api_calls`, 현재 구현된 domain output인 `channels`, `videos`,
`transcripts`, `transcriptCues`, `microEventExtractions`, timeline output을 함께 반환한다.
- `POST /pipeline/jobs/{jobId}/retry`: failed job 재시도 command다. 현재
  `channel_resolve`, `video_collect`, `transcript_collect`,
  `transcript_cue_generate`, `micro_event_extract`, `timeline_compose`를 지원한다.
- `POST /video-tasks/transcript-collect` and
  `POST /channels/{channel_id}/video-tasks/transcript-collect`: manually select
  stored videos and execute transcript collection through durable `video_tasks`.
- `POST /channels/{channel_id}/video-tasks/transcript-cue-generate` and
  `POST /video-tasks/transcript-cue-generate`: manually execute cue generation
  through durable `video_tasks` rows for videos with succeeded transcript tasks.
- `POST /videos/{video_id}/video-tasks/micro-event-extract`: synchronously
  executes `video_tasks.task_name="micro_event_extract"` for one stored video
  after a succeeded cue-generation task exists.
- `POST /video-tasks/micro-event-extract`: synchronously executes a small
  operator-limited batch of eligible videos.
- `POST /video-tasks/micro-event-extract/enqueue`: writes pending
  `micro_event_extract` tasks. The `codex-micro-event-worker` process claims
  pending rows by DB polling.
- `GET /videos/{video_id}/micro-event-extractions/latest` and
  `GET /videos/{video_id}/micro-event-extractions/{video_task_id}`: return the
  latest succeeded extraction or a task-specific extraction with window-level
  raw/validation state and normalized candidate rows.
- `POST /video-tasks/timeline-compose/enqueue`: writes pending
  `timeline_compose` tasks for videos with a succeeded micro-event task. The
  `codex-timeline-compose-worker` process claims pending rows by DB polling.
- `GET /videos/{video_id}/timelines/latest` and
  `GET /videos/{video_id}/timelines/{video_task_id}`: return stored timeline
  composition output and validation metadata.
- `GET /ops/events` and `/ops/codex-usage*`: provide operational timeline and
  usage views without mutating pipeline state.

## Current Baseline

현재 구현된 첫 pipeline step은 `POST /streamers/{streamer_id}/channels/resolve`다.
요청 body는 `handle`만 받는다. use case는 streamer 존재를 확인한 뒤
`channel_resolve` job과 첫 attempt를 만들고, YouTube Data API `channels.list`
raw response를 `external_api_calls`와 object storage에 기록한다. 성공하면
`channels` row를 만들거나 같은 streamer의 기존 `youtube_channel_id` row를
재사용한다. 새 row는 `channels.source_job_id`와
`channels.source_api_call_id`로 job/raw metadata를 연결한다.
`channels.uploads_playlist_id`에는 `channels.list(part=id,snippet,contentDetails)`가
반환한 `contentDetails.relatedPlaylists.uploads` 값을 저장한다. 응답에는
`channelId`, `youtubeChannelId`, `uploadsPlaylistId`, `sourceApiCallId`,
`jobId`, `jobAttemptId`가 포함된다.

요청 DTO validation 실패나 missing streamer처럼 작업 대상으로 볼 수 없는 입력은 job을
만들지 않는다. YouTube upstream/not-found/schema validation 실패처럼 attempt 실행 중
발생한 오류는 channel row를 만들지 않고 attempt와 job을 `failed`로 종료한다.

`POST /pipeline/jobs/{jobId}/retry`는 현재 `channel_resolve`, `video_collect`,
`transcript_collect`, `transcript_cue_generate`, `micro_event_extract`,
`timeline_compose` failed job을 지원한다. retry는 기존 job을 덮어쓰지 않고 같은
job 아래 새 attempt를 만든다. `succeeded`, `running`, `skipped`, `canceled` job은
retry하지 않는다. 입력이 달라져야 하는 재실행은 retry가 아니라 새 job으로 처리한다.

두 번째 pipeline step은 `POST /channels/{channel_id}/videos/collect`다. 요청은
local `channelId`만 path로 받고, DB의 `channels.uploads_playlist_id`를 사용해
YouTube Data API `playlistItems.list`를 uploads playlist 기준으로 최신순 호출한다.
값이 없으면 collect attempt 안에서 `channels.list(part=id,snippet,contentDetails)`를
한 번 호출해 채운다. 각 listing page raw response는 `external_api_calls`와 object
storage에 `operation=playlistItems.list`로 남긴다. 수집은 10 page/500 candidate v1
상한 안에서 진행하며, 같은 channel에 이미 저장된 `youtube_video_id`가 처음 나오면
그 지점에서 중단한다. 새 candidate들은 50개씩 `videos.list(part=contentDetails)`로
duration만 보강하고, 각 batch raw response는 `operation=videos.list`로 남긴다.
모든 upstream 호출과 DTO validation이 성공한 뒤에만 `videos` row를 bulk create한다.
성공 응답과 attempt output에는 `createdVideoIds`, `firstExistingYoutubeVideoId`,
`stoppedReason`, listing/detail raw API call id 목록을 포함한다.

`POST /pipeline/jobs/{jobId}/retry`는 failed `video_collect` job도 지원한다.
retry는 저장된 `input_json.channelId`와 `input_json.youtubeChannelId`를 복원해 같은
job 아래 새 attempt로 실행한다. local channel의 현재 YouTube channel id가 저장된
입력과 달라졌으면 새 job으로 다시 실행해야 하며, retry attempt는 failed로 닫힌다.

`POST /channels/{channel_id}/video-tasks/transcript-collect`는 scheduler 없이 사람이 호출하는
manual selector API다. 겉으로는 channel id를 받지만 실제 작업 상태는
`video_tasks(video_id, task_name, task_version, input_hash)` unique key가 소유한다.
이미 `succeeded` 또는 `running`인 task는 건너뛰고, `failed`/`timed_out` task는
`retryFailed=true`일 때만 다시 실행한다. `transcript_collect` v1은 기본
`timeoutSeconds=600`, `concurrencyLimit=1`, 실제 fetch 간 `delaySeconds=300`을 사용하며,
각 실행 video마다 `subject_type="video"`인 pipeline job과 attempt를 만든다.

같은 `youtubeVideoId`, requested languages, `preserveFormatting` 조합의 transcript
metadata가 이미 있으면 외부 transcript fetch를 다시 하지 않고 task를 `succeeded`로
마감한다. 실제 fetch/store는 `asyncio.wait_for`로 감싸며 timeout 또는 upstream/storage
오류는 해당 task와 job/attempt를 failed 계열 상태로 남긴 뒤 다음 video 처리를 계속한다.
기존 metadata 재사용이나 `no_transcript`처럼 외부 fetch가 없거나 retrievable transcript가
없다고 확정된 경우에는 다음 video 처리를 위해 300초 delay를 둘 필요가 없다.

Transcript fetch can also end as `no_transcript`. This is reserved for
`YouTubeTranscriptNotFound`, where YouTube has no retrievable transcript for the
video. It is a terminal task outcome, but not an infrastructure or persistence
failure. Manual retry controls therefore split generic `failed` retries from
`no_transcript` rechecks: `retryFailed=true` re-runs failed/timed-out work, while
`recheckNoTranscript=true` explicitly asks the system to try videos previously
marked `no_transcript` again. The child `transcript_collect` pipeline job is
completed with a `no_transcript` output so job history records that the work was
handled, not crashed.

Cue generation is now also owned by `video_tasks`. A stored transcript or an
existing transcript metadata hit creates or reuses a
`video_tasks.task_name="transcript_cue_generate"` row and executes it
immediately to preserve the current operator UX. The cue task `input_hash` is
based on local `videoId`, `youtubeVideoId`, `transcriptId`, transcript
`responseSha256`, and task version. Success stores the source transcript id in
`output_transcript_id` and writes a compact `output_json` with `cueCount`,
`firstCueId`, `lastCueId`, `jobId`, and `jobAttemptId`. Existing succeeded cue
tasks are treated as effective success, while `failed` and `timed_out` cue tasks
are skipped unless the selector request sets `retryFailed=true`.

Manual cue selectors are exposed as
`POST /channels/{channel_id}/video-tasks/transcript-cue-generate` and
`POST /video-tasks/transcript-cue-generate`. Both select latest videos that have
a succeeded `transcript_collect` task with `outputTranscriptId`, then apply the
same cue task lifecycle. `POST /youtube-transcripts/{transcript_id}/cues/generate`
uses this task-aware path when the transcript belongs to a local `videos` row and
keeps the legacy direct pipeline job path for orphan transcripts. Retry for
`pipeline_jobs.step="transcript_cue_generate"` reuses the linked cue video task
when `input_json.videoTaskId` is present; legacy cue jobs without a task id still
use the direct retry path.

Transcript가 성공적으로 저장되면 후속 child job `transcript_cue_generate`가 실행된다.
이 단계는 `youtube_transcripts` metadata와 storage의 transcript JSON을 읽어
`transcript_cues` row를 만든다. v1 cue는 원본 transcript segment 1개를 그대로
1개 cue로 매핑하고, cue id는 `tr{transcriptId}-c000001` 형식으로 안정적으로
생성한다. cue 생성 실패는 저장된 transcript 성공 상태를 되돌리지 않고 cue job만
`failed`로 남긴다.

`micro_event_extract`는 cue generation이 succeeded인 video를 대상으로 한다. 단건/소형
동기 실행 API와 enqueue API가 모두 같은 task-aware execution path를 사용한다. Enqueue는
`video_tasks.status="pending"`과 `input_json`에 model, reasoning effort, window/overlap,
transcript id, input hash를 저장하고, `codex-micro-event-worker`가 pending row를 하나씩
claim한다. 한 video 안에서는 owned cue window를 bounded async worker pool로 처리하며
`CODEX_CLI_MICRO_EVENT_EXTRACT_CONCURRENCY_LIMIT`가 window worker 수를 제어한다.
복구 가능한 LLM 출력 흔들림은 정규화와 window-level warning으로 남기고, owned range
coverage 누락/중복/겹침처럼 결과 무결성을 깨는 경우만 task/job을 failed로 둔다.

`timeline_compose`는 succeeded micro-event task를 입력으로 한다. Enqueue API는
selected/current-filter/next-eligible videos에 pending timeline task를 만들고,
`codex-timeline-compose-worker`가 DB polling으로 claim한다. Worker는 영상 단위로
`CODEX_CLI_TIMELINE_COMPOSE_CONCURRENCY_LIMIT`개까지 동시에 처리하며, 같은 video의
timeline task가 이미 running이면 추가 claim하지 않는다. 결과는
`timeline_compositions`와 block/episode/topic/review flag 테이블에 정규화해 저장한다.
Prompt version과 input hash가 task idempotency를 결정하며, `validation_warnings`는
topics/highlight truncation, enum/content-kind alias 보정, block semantic repair처럼
저장 가능한 흔들림을 기록한다. JSON 파싱 실패, micro-event coverage 파괴, block membership
불일치 같은 hard invariant는 계속 failed로 처리한다.
episode range가 micro-event를 빠뜨리거나 중복/겹침으로 덮는 경우에는 hard invariant
실패로 닫기 전에 문제가 된 연속 구간만 `repair_episode` LLM 작업으로 재작성해 기존
timeline에 재조합한다. 이 recovery도 target 구간을 정확히 한 번씩 순서대로 덮어야 하며,
상한 횟수 안에 고치지 못하면 기존과 같이 failed attempt로 남긴다.
실패한 timeline attempt의 원문 Codex 응답은 해당 `pipeline_job_attempts.output_json`의
`rawResponses` 배열에 남긴다. `/ops/video-tasks`와 operation events에는
`rawResponseCount`, `rawResponseSha256s`, `rawResponseLengths`, `rawResponseStoredIn`
요약만 남기고 full raw text는 복제하지 않는다.

## Implementation Rules

- FastAPI route handler는 얇게 유지하고 pipeline orchestration은 use case에 둔다.
- Use case는 repository/client/storage Protocol에 의존한다.
- 외부 API client는 raw body를 직접 반환하지 말고, raw 저장/검증 후 projection과 raw metadata id를 반환한다.
- DB schema 변경은 SQLAlchemy model과 Alembic revision으로만 수행한다.
- 자동 테스트에서는 live YouTube, MinIO, OpenAI, Codex runtime을 호출하지 않는다. fake port와 dependency override를 사용한다.
- 작업 상태 추적은 "동기 실행과 DB polling worker가 같은 task/job/attempt 모델을 공유"하는 기준으로 설계한다. FastAPI process 안에 long-running worker loop를 넣지 않는다.

## Backlog

구현 TODO는 `docs/YOUTUBE_DATA_PIPELINE_TODO.md`에 둔다.
