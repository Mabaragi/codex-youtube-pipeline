# YouTube Data Pipeline

Last updated: 2026-06-16

이 문서는 YouTube channel resolve부터 videos, transcripts, LLM summaries까지 이어지는 데이터 파이프라인의 공통 설계 원칙을 정리한다. 특정 endpoint 구현 절차보다, 앞으로 새 수집/가공 단계를 추가할 때 따라야 하는 상태 추적과 데이터 연결 규칙을 우선한다.

## Target Flow

1. 사용자가 streamer를 수동 등록한다.
2. streamer에 연결할 YouTube channel을 resolve한다.
3. channel 기반으로 videos를 수집한다.
4. video 기반으로 transcripts를 수집한다.
5. transcript 기반으로 LLM summary를 생성한다.

각 단계는 동기 REST API, 수동 실행, 또는 future worker/queue로 실행될 수 있다. 실행 방식이 달라도 job/attempt/raw/domain row 연결 규칙은 동일해야 한다.

## Core Model

파이프라인은 네 종류의 데이터를 분리한다.

- `pipeline_jobs`: 사용자가 의도한 논리 작업이다. 예: 한 streamer의 channel resolve, 한 channel의 videos collect, 한 video의 transcript collect.
- `pipeline_job_attempts`: job을 실제로 실행한 1회 시도다. retry가 생기면 같은 job 아래에 attempt가 추가된다.
- `external_api_calls`: 외부 API 요청/응답 metadata다. raw response body는 object storage에 저장하고, DB에는 저장 위치, hash, 검증 상태, sanitized request metadata만 둔다.
- `video_tasks`: video 단위 durable work item이다. 수동 channel API가 대상을 고르더라도 중복 방지와 완료 상태는 이 row가 소유한다.
- Domain tables: `channels`, `videos`, `youtube_transcripts`, future summaries처럼 애플리케이션이 사용하는 정규화 결과다.

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
- Summary generate output: future summary row, LLM request/response metadata.

API 응답에는 사용자가 다음 상태를 추적할 수 있도록 필요한 local identifiers를 포함할 수 있다. pipeline step을 실행하는 endpoint는 가능하면 `jobId`, `jobAttemptId`, 그리고 raw metadata id를 응답에 포함한다.

## Operational APIs

운영 API는 pipeline state를 직접 수정하는 작업을 최소화하고, 먼저 관측 가능성을
제공한다.

- `GET /pipeline/jobs`: 최근 job 목록을 조회한다. `step`, `status`,
  `subjectType`, `subjectId`, `externalKey`, `cursor`, `limit` 필터를 지원하고,
  latest attempt 상태와 attempt count를 함께 반환한다.
- `GET /pipeline/jobs/{jobId}`: 단일 job의 입력, attempts, 연결된
  `external_api_calls`, 현재 구현된 domain output인 `channels`, `videos`, `transcripts`를 함께 반환한다.
- `POST /pipeline/jobs/{jobId}/retry`: failed job 재시도 command다. 현재는
  `channel_resolve`, `video_collect`, `transcript_collect`를 지원한다.

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

`POST /pipeline/jobs/{jobId}/retry`는 현재 `channel_resolve`, `video_collect`, `transcript_collect`
failed job을 지원한다. retry는 기존 job을 덮어쓰지 않고 같은 job 아래 새 attempt를
만든다. `succeeded`, `running`, `skipped`, `canceled` job은 retry하지 않는다.
입력이 달라져야 하는 재실행은 retry가 아니라 새 job으로 처리한다.

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
`timeoutSeconds=600`, `concurrencyLimit=1`을 사용하며, 각 실행 video마다
`subject_type="video"`인 pipeline job과 attempt를 만든다.

같은 `youtubeVideoId`, requested languages, `preserveFormatting` 조합의 transcript
metadata가 이미 있으면 외부 transcript fetch를 다시 하지 않고 task를 `succeeded`로
마감한다. 실제 fetch/store는 `asyncio.wait_for`로 감싸며 timeout 또는 upstream/storage
오류는 해당 task와 job/attempt를 failed 계열 상태로 남긴 뒤 다음 video 처리를 계속한다.

## Implementation Rules

- FastAPI route handler는 얇게 유지하고 pipeline orchestration은 use case에 둔다.
- Use case는 repository/client/storage Protocol에 의존한다.
- 외부 API client는 raw body를 직접 반환하지 말고, raw 저장/검증 후 projection과 raw metadata id를 반환한다.
- DB schema 변경은 SQLAlchemy model과 Alembic revision으로만 수행한다.
- 자동 테스트에서는 live YouTube, MinIO, OpenAI, Codex runtime을 호출하지 않는다. fake port와 dependency override를 사용한다.
- 작업 상태 추적은 "나중에 worker를 붙일 수 있는 동기 실행"을 기준으로 설계한다. worker/queue 도입 전에도 job/attempt 기록은 남긴다.

## Backlog

구현 TODO는 `docs/YOUTUBE_DATA_PIPELINE_TODO.md`에 둔다. 장기 설계 결정과 rationale은 `vaults/decisions/`에 기록한다.
