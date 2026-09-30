# Timeline Segment Classification

새 `process_to_publish` v3는 `timeline_compose → segment_classify → archive_publish`로
진행한다. 기존 v1/v2는 기존 단계로 완료된다.

## 분류 계약

taxonomy `v1.6`의 활동은 `chat`, `game`, `sing`, `watch`, `cafe`, `setup`, `asmr`,
`other`다. 합방은 별도 `collab`·`partners`로 표현한다. cafe는 팬카페 게시판 탐방이며
게시글 속 콘텐츠를 포함한다. 팬 제작 웹게임은 game이다. 퀴즈·버라이어티·나무위키
탐방·선곡은 chat, 게임 속 이벤트·역할극 준비는 game이다. 식사·휴식·자리비움은
진행 중인 활동에 포함한다. 시청자 참여와 팬덤 호칭은 합방으로 취급하지 않는다.

영상 전체 metadata, block·episode 제목·요약·토픽·시간, streamer별 domain knowledge를
한 번에 입력한다. 원문 자막은 입력하지 않는다. 출력은 episode index 범위이며 전체를
정확히 한 번씩 덮는지 검사한다. 잘못된 출력은 work attempt 안에서 최대 3회 생성한다.
빈 timeline은 LLM 호출 없이 빈 segment 목록으로 저장한다.

결정적 policy `v1`은 오프닝·클로징을 양 끝에서 각각 최대 15분으로 제한하고,
20분 미만 watch를 chat으로 바꾼다. 같은 활동 사이의 10분 미만 chat과 5분 미만
조각은 이웃 활동에 흡수하며 짧은 setup은 뒤 활동에 붙인다. 실제 합방 합류·퇴장
경계는 보존하므로 서로 다른 참여자 구간은 짧아도 남을 수 있다.

## 저장과 게시

- `segment_classifications`: work item/attempt, source composition/timeline work item,
  입력 fingerprint, taxonomy/policy, prompt version/hash, model/effort, 원본 출력.
- `timeline_segments`: classification별 순서, millisecond 경계, episode anchor,
  category/collab과 정규화 payload.
- 결과는 attempt별로 보존한다. 같은 입력은 재사용하고 source, prompt, model/effort,
  taxonomy/policy가 바뀌면 새 identity로 생성한다.
- 게시 입력은 timeline과 classification을 함께 pin하고 두 작업에 의존한다.
  source fingerprint와 실행 provenance가 일치해야 게시한다. 분류 후 원본이 수정되면
  새 분류를 요청한다. `archive_video_artifacts.source_classification_id`가 게시 결과를 추적한다.
- 공개 JSON의 `taxonomyVersion`, `segments`, `segmentClassification`에는 분류와 ID·checksum을
  포함한다. 프롬프트·원본 출력은 포함하지 않는다. `start`·`end`는 **초**이며 SQL은 **밀리초**다.

## 운영 API

| 작업 | API | 실행 |
| --- | --- | --- |
| 분류만 생성 | `POST /ops/operations/segment-classify` | worker |
| 기존 timeline 분류 후 게시 | `POST /ops/workflows/classify-to-publish` | 두 단계 workflow |
| 분류 결과를 포함해 게시 | `POST /ops/operations/archive-publish`, `includeSegments: true` | worker queue (`202`) |
| 전체 처리 | `POST /ops/workflows/process-to-publish`, `segmentEnabled: true` | v3 workflow |

기존 `selection` 구조를 사용한다. 기본값은 `gpt-6-luna` / `high` / `v1.6`이다.
상태·오류·재시도는 `/ops/work-items/{id}`, `/ops/workflows/{id}`로 확인한다.

`classify_to_publish`는 선택한 environment·variant·schema에서 **현재 게시된 성공한
timeline**과 분류 입력을 고정한다. 이후 만든 미게시 실험 timeline으로 교체하지 않는다.
transcript, cue, micro-event, timeline 작업을 생성하지 않고 일일 신규 영상 승인
한도도 사용하지 않는다. 같은 요청을 반복하면 workflow/result를 재사용한다.
원본이나 프롬프트가 바뀌면 다시 요청해 새 workflow를 만든다.
자동 재시도를 소진한 실패 workflow도 `retryFailed: true`로 다시 요청하면 같은 작업 ID로
새 시도를 시작한다. 성공 단계와 과거 시도 기록은 보존한다.

자동 승인 집계와 활성·종료 작업의 중복 검사는 `process_to_publish` v2/v3를 함께
포함한다. 코디네이터는 새 일반 처리와 다음 단계로 진행 가능한 일반 처리 작업을
분류 전용 백필보다 먼저 선택한다. 워커 결과를 기다리는 일반 작업은 백필 진행을
막지 않는다.

운영 프롬프트는 `segment_classify` key의 DB `prompt_versions`에 게시한다. 공개 sample
fallback만 있는 상태에서는 비어 있지 않은 영상의 분류 요청을 거부한다.
코디네이터에서 프롬프트 준비 또는 원본 검증에 실패하면 해당 workflow만 `blocked`로
기록하고 다른 영상 처리를 계속한다. 원인을 해결한 뒤 workflow를 다시 요청한다.

단독 archive 게시의 `includeSegments`는 기본 `null`(자동)이다. 호환되는 성공 분류가
있으면 포함하고, 없으면 기존 형식으로 게시한다. `true`는 분류를 필수로 요구하며
`false`는 분류 없이 게시한다. v3/백필 workflow는 선택한 분류를 항상 포함한다.

## 워커와 전환

워커는 `codex-segment-classify-worker` 또는 `uv run python -m codex_sdk_cli.workers.segments`로
실행하며 공유 WorkExecutionEngine을 사용한다.

| 환경 변수 | 기본값 |
| --- | --- |
| `CODEX_CLI_SEGMENT_CLASSIFY_ENABLED` | `true` |
| `CODEX_CLI_SEGMENT_CLASSIFY_MODEL` | `gpt-6-luna` |
| `CODEX_CLI_SEGMENT_CLASSIFY_REASONING_EFFORT` | `high` |
| `CODEX_CLI_SEGMENT_CLASSIFY_CONCURRENCY_LIMIT` | `2` |
| `CODEX_CLI_SEGMENT_CLASSIFY_TIMEOUT_SECONDS` | `600` |
| `CODEX_CLI_SEGMENT_CLASSIFY_WORKER_POLL_INTERVAL_SECONDS` | `5` |

환경 변경은 기존 drain/restart 절차로 적용한다. 끄면 자동 스케줄러의 새 요청은 v2로
생성하고 분류 워커를 시작하지 않는다. 기존 v3/백필의 대기 분류는 유지된다.
배포는 기존 `draining/stopped` runtime 의도를 덮어쓰지 않는다.

Planetip은 D1에서 선택한 R2 timeline JSON의 segment를 사용한다. 분류가 없는 기존
아티팩트는 기존 필터로 표시한다. DEV 미리보기는 게시 segment가 없을 때만 사용하며
프로덕션 번들에는 포함되지 않는다. 카테고리·시간 연속성·참여자 타입을 렌더링 전에 검증한다.
