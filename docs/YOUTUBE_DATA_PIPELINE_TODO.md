# YouTube Data Pipeline Backlog

Last updated: 2026-06-16

공통 설계 원칙은 `docs/YOUTUBE_DATA_PIPELINE.md`를 따른다. 이 문서는 구현 TODO와 완료 상태만 추적한다.

## Completed

- [x] YouTube Data API `channels.list` 응답을 Pydantic external DTO로 검증한다.
- [x] `channels.list` 요청은 channel 생성에 필요한 필드를 받을 수 있도록 `part=id,snippet`을 사용한다.
- [x] Pydantic DTO는 우리가 의존하는 필드를 검증하되, Google의 추가 필드는 `extra="allow"`로 허용한다.
- [x] `/streamers/{streamer_id}/channels/resolve`는 path의 streamer와 body의 `handle`로 `channels` row 하나를 생성하거나 같은 streamer의 기존 row를 재사용한다.
- [x] 요청에 `youtubeChannelId`를 받지 않는다. YouTube 식별자는 YouTube API 응답의 `items[].id`에서만 온다.
- [x] API 응답에서는 local row 식별자를 `channelId`, YouTube 식별자를 `youtubeChannelId`로 구분한다.
- [x] 외부 API 요청/응답 raw metadata 테이블 `external_api_calls`를 추가한다.
- [x] raw JSON body는 object storage에 저장하고 DB에는 metadata를 둔다.
- [x] 검증 성공 응답뿐 아니라 검증 실패 응답도 raw 저장 대상으로 둔다.
- [x] channel resolve로 생성된 `channels` row는 `source_api_call_id`로 raw metadata row를 참조한다.
- [x] `pipeline_jobs`와 `pipeline_job_attempts` SQLAlchemy model, repository, Alembic revision을 추가한다.
- [x] `external_api_calls.pipeline_job_attempt_id` nullable FK를 추가한다.
- [x] domain result row가 source job을 참조할 수 있도록 현재 `channels`부터 `source_job_id` nullable FK를 추가한다.
- [x] `/streamers/{streamer_id}/channels/resolve`가 job/attempt를 생성하고, 성공 응답에 `jobId`, `jobAttemptId`를 포함하도록 연결한다.
- [x] resolve 실패 시 channel row를 만들지 않고 job/attempt를 `failed`로 종료한다.
- [x] ops schema graph와 database tests를 새 pipeline schema에 맞게 갱신한다.
- [x] `POST /pipeline/jobs/{jobId}/retry`로 failed `channel_resolve` job을 같은 job 아래 새 attempt로 재시도한다.
- [x] `GET /pipeline/jobs`와 `GET /pipeline/jobs/{jobId}`로 운영용 job 목록/상세 조회를 제공한다.
- [x] Channel code를 `channels` domain/infra로 분리하고 public resolve route에서 `youtube_data` 이름을 제거한다.
- [x] `channels.youtube_channel_id`를 nullable unique로 전환하고 같은 streamer resolve는 기존 row를 재사용한다.
- [x] `videos` table을 추가한다.
- [x] `videos.youtube_video_id`처럼 YouTube 외부 식별자를 local `id`와 분리해서 명명한다.
- [x] video 수집 raw 응답과 normalized video row를 분리한다.
- [x] `POST /channels/{channel_id}/videos/collect`로 local channel 기반 YouTube video 수집을 지원한다.
- [x] `GET /channels/{channel_id}/videos`로 저장된 videos를 최신순 조회한다.
- [x] `video_collect` failed job retry를 지원하도록 step별 executor registry를 도입한다.
- [x] `video_collect` 후보 수집을 `search.list`에서 uploads playlist 기반
  `playlistItems.list`로 전환한다.
- [x] `channels.uploads_playlist_id`를 추가하고 channel resolve 또는 first collect 시
  `channels.list(part=id,snippet,contentDetails)`로 채운다.
- [x] `videos.source_search_api_call_id`를 playlist 방식에 맞춰
  `source_listing_api_call_id`로 교체한다.
- [x] `videos` normalized projection에서 `statistics`, `status`,
  `liveBroadcastContent`를 제거하고 duration/details만 유지한다.
- [x] `video_tasks` table과 repository를 추가해 video 단위 task 상태와 중복 방지를 저장한다.
- [x] `POST /channels/{channel_id}/video-tasks/transcript-collect`로 channel selector 기반 manual transcript 수집을 지원한다.
- [x] `GET /channels/{channel_id}/video-tasks`로 저장된 task 상태를 조회한다.
- [x] `transcript_collect` task 기본 정책을 `timeoutSeconds=600`, `concurrencyLimit=1`로 둔다.
- [x] `transcript_collect` 실제 fetch 사이 기본 대기 시간을 300초로 둔다.
- [x] `transcript_collect` failed job retry를 executor registry에 연결한다.
- [x] `YouTubeTranscriptNotFound`를 generic `failed`가 아닌 `no_transcript` task outcome으로 분리하고, `recheckNoTranscript=true`로 재확인을 지원한다.
- [x] pipeline job detail에서 linked transcript output을 반환한다.

## Future Domain Work

- [ ] LLM summary 결과는 transcript metadata와 분리된 summary domain table에 저장한다.
- [ ] summary 생성 request/response raw도 재현성과 감사 가능성을 위해 저장한다.

## Open Implementation Details

- `pipeline_jobs.input_hash`에 unique 제약을 둘지 여부는 idempotency 정책을 정할 때 결정한다.
- job 조회/list API는 pipeline state table 도입 후 별도 endpoint로 설계한다.
- worker/queue 도입 전에는 REST use case 안에서 동기 실행하되, job/attempt 기록은 먼저 남긴다.
