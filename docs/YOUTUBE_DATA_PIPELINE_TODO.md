# YouTube Data Pipeline TODO

Last updated: 2026-06-16

이 문서는 YouTube Data API 기반 channel resolve부터 video, transcript, LLM summary 수집까지의 계획과 구현 TODO를 정리한다. 현재 목표는 전체 파이프라인 구현이 아니라, 지금 바꾸는 API 흐름이 나중의 데이터 파이프라인으로 자연스럽게 확장되도록 결정사항을 남기는 것이다.

## Terminology

- `channelId`: local `channels.id`. 애플리케이션 내부 DB row 식별자다.
- `youtubeChannelId`: YouTube의 `UC...` channel identifier. YouTube Data API `channels.list` 응답의 `items[].id`에서 온다.
- `handle`: YouTube handle. 예: `@example`.
- `streamerId`: local `streamers.id`. channel row가 반드시 참조해야 하는 parent key다.
- Raw response: 외부 API가 반환한 원본 JSON body. use case가 직접 소비하는 값이 아니라 저장/검증/추적 대상이다.
- Projection: raw response에서 현재 use case에 필요한 필드만 추출한 내부 결과 객체다.

## Target Flow

1. 사용자가 streamer 이름을 수동 등록한다.
2. 등록된 streamer에 YouTube channel을 resolve해서 `channels` row 하나를 완성한다.
3. channel 정보를 기반으로 videos를 수집한다.
4. video 정보를 기반으로 transcript를 수집한다.
5. transcript를 기반으로 LLM summary를 생성한다.

## Current Implementation Change TODO

- [x] YouTube Data API `channels.list` 응답을 Pydantic external DTO로 검증한다.
- [x] `channels.list` 요청은 channel 생성에 필요한 필드를 받을 수 있도록 `part=id,snippet`을 사용한다.
- [x] Pydantic DTO는 우리가 의존하는 필드를 검증하되, Google의 추가 필드는 `extra="allow"`로 허용한다.
- [x] `items[].id`는 내부 projection에서 `youtube_channel_id`로 매핑한다.
- [x] `items[].snippet.title`은 `channels.name` 후보로 사용한다.
- [x] `/youtube-data/channels/resolve`는 기존 local channel row들을 handle로 찾아 업데이트하지 않는다.
- [x] `/youtube-data/channels/resolve`는 `streamerId`, `handle`만 입력받아 `channels` row 하나를 생성한다.
- [x] 요청에 `youtubeChannelId`를 받지 않는다. YouTube 식별자는 YouTube API 응답의 `items[].id`에서만 온다.
- [x] API 응답에서는 local row 식별자를 `channelId`, YouTube 식별자를 `youtubeChannelId`로 명확히 구분한다.
- [x] 내부 메서드명에서 모호한 `channel_id` 표현을 피하고 `youtube_channel_id` 또는 `youtubeChannelId` 의미를 드러낸다.
- [x] README, `docs/PROJECT_OVERVIEW.md`, `vaults/agents/api-domains.md`의 기존 "matching local channel rows update" 설명을 새 create flow로 갱신한다.
- [x] 관련 API/use-case/client 테스트를 새 흐름에 맞게 갱신한다.

## Raw Data Storage TODO

- [x] 외부 API 요청/응답 raw 기록용 테이블을 추가한다. 이름은 `external_api_calls`다.
- [x] raw JSON body는 DB에 직접 크게 저장하지 않고, 기존 transcript 흐름처럼 object storage에 저장하고 DB에는 metadata를 둔다.
- [x] 검증 성공 응답뿐 아니라 검증 실패 응답도 raw 저장 대상으로 둔다.
- [x] use case는 raw JSON을 반환받지 않고, 검증된 projection만 반환받는다.
- [x] YouTube Data API key는 request metadata나 raw body에 저장하지 않는다.
- [x] channel resolve로 생성된 `channels` row는 `source_api_call_id`로 raw metadata row를 참조한다.

### Proposed `external_api_calls`

- `id`
- `provider`: `youtube_data`, `youtube_transcript`, `openai` 등
- `operation`: `channels.list`, `videos.list`, `transcripts.fetch`, `summaries.create` 등
- `request_method`
- `request_url_or_path`
- `request_params_json`
- `request_body_json`
- `response_status_code`
- `response_headers_json`
- `response_storage_bucket`
- `response_storage_object`
- `response_sha256`
- `schema_name`
- `schema_version`
- `validation_status`: `not_validated`, `valid`, `invalid`
- `validation_error`
- `duration_ms`
- `quota_cost`
- `created_at`

Future extension:

- `pipeline_job_attempt_id`: nullable future FK

## Pipeline State Design TODO

전체 파이프라인은 지금 구현하지 않는다. 다만 videos 수집 단계로 넘어가기 전에 다음 테이블 설계를 확정한다.

### Proposed `pipeline_jobs`

- `id`
- `step`: `streamer_register`, `channel_resolve`, `videos_collect`, `transcripts_collect`, `summary_generate`
- `subject_type`: `streamer`, `channel`, `video`, `transcript`
- `subject_id`: local DB id. 아직 생성 전이면 nullable 허용을 검토한다.
- `external_key`: `youtubeChannelId`, video id 등 외부 식별자
- `input_json`
- `input_hash`
- `idempotency_key`
- `status`: `pending`, `running`, `succeeded`, `failed`, `skipped`, `canceled`
- `parent_job_id`
- `created_at`
- `updated_at`
- `completed_at`

### Proposed `pipeline_job_attempts`

- `id`
- `job_id`
- `attempt_no`
- `status`
- `started_at`
- `finished_at`
- `worker_id`
- `error_type`
- `error_message`
- `output_json`

## Future Domain Tables TODO

- [ ] `videos` table을 추가한다.
- [ ] `videos.youtube_video_id`처럼 YouTube 외부 식별자를 local `id`와 분리해서 명명한다.
- [ ] video 수집 raw 응답과 normalized video row를 분리한다.
- [ ] transcript raw 저장과 transcript metadata 저장 규칙을 현재 `youtube_transcripts` 흐름과 맞춘다.
- [ ] LLM summary 결과는 transcript metadata와 분리된 `llm_summaries` 계열 테이블에 저장한다.
- [ ] summary 생성 request/response raw도 재현성과 감사 가능성을 위해 저장한다.

## Remaining Implementation Order

1. videos 수집 구현에 들어가기 전에 `pipeline_jobs`와 `pipeline_job_attempts` migration을 추가한다.
2. video 수집, transcript 수집, summary 생성 단계가 각각 job/attempt/raw 기록을 연결하도록 확장한다.
3. `external_api_calls`에 `pipeline_job_attempt_id`를 추가해 job attempt와 raw call을 연결한다.

## Open Decisions

- `youtubeChannelId`는 resolve 요청 입력이 아니라 응답 필드로만 제공한다.
- `external_api_calls`는 모든 외부 요청에 공통 사용하고, raw body는 object storage에 둔다.
- pipeline 상태 테이블을 channel resolve 단계부터 바로 만들지, videos 수집 단계에서 만들지 결정해야 한다. 현재 추천은 raw 저장 테이블을 먼저 만들고 pipeline job 테이블은 videos 수집 직전에 추가하는 방식이다.
