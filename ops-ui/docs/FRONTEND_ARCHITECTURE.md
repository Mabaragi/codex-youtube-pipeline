# Ops UI v2 Frontend Architecture

Ops UI v2는 `/ops`에 마운트되는 Next.js App Router 운영 콘솔이다. 로컬
`127.0.0.1` 런타임을 전제로 하며 별도 로그인 화면이나 임의 Codex prompt 실행 기능은
제공하지 않는다.

## 데이터 경계

- Server Component는 첫 화면 데이터를 FastAPI에서 `cache: no-store`로 읽는다.
- 서로 독립적인 첫 요청은 `Promise.allSettled`로 실행하여 일부 API가 실패해도 shell을
  렌더링한다.
- 브라우저의 조회와 mutation은 모두 `/ops/api/backend/*` BFF를 통과한다.
- `openapi-fetch`와 `src/generated/codex-api.ts`를 사용하며 DTO를 수동 복제하지 않는다.
- TanStack Query는 실행 중 상태에서 5초, 안정 상태에서 15초마다 갱신하고 숨겨진
  탭에서는 polling을 중지한다.
- 필터, 탭, cursor와 offset은 URL에 저장한다.

## 화면 구조

- `/ops`: API, 프로세스, runtime, queue, incident, 실행 work, publication을 요약한다.
- `/ops/operations`: 채널 확인, 영상 수집, 전체 process-to-publish와 단계별 실행.
- `/ops/executions`: workflow, batch, work item 목록과 상세 provenance.
- `/ops/incidents`: 사건 상태 변경과 서버가 허용한 안전 복구 조치.
- `/ops/content/videos`, `/ops/content/transcripts`: 생성 상태와 cue/event/timeline artifact.
- `/ops/publishing`: prod/dev archive 최신성과 영상별 publish.
- `/ops/configuration/*`: channel/streamer, domain knowledge, prompt lifecycle.
- `/ops/observability/*`: operation events와 Codex usage.
- `/ops/system/schema`: 동적 import되는 React Flow schema graph.

기존 `channels`, `videos`, `tasks`, `jobs`, `logs`, `archive`, `usage`, `prompts`,
`domain-knowledge`, `erd` 경로는 새 위치로 redirect한다. 영상 상세 ID도 보존한다.

## 컴포넌트 계약

`ActionDialog`, `DataTable`, `SelectionBuilder`는 provider가 `state`, `actions`,
`meta`를 소유하는 compound component다. 페이지는 조합만 담당하고 boolean prop 조합을
늘리지 않는다. `ActionDialog`는 Radix Dialog의 focus trap, Escape, trigger focus 복귀를
사용한다. 50건을 넘는 cue 목록은 TanStack Virtual로 가상화한다.

## Mutation 규칙

- enqueue, retry, cancel, incident action, production publish는 확인 dialog를 거친다.
- cancel/runtime/incident 상태 변경에는 서버가 지원하는 reason 또는 note가 필요하다.
- 삭제와 archive는 대상 ID 재입력과 3~500자 운영 사유가 모두 필요하다.
- incident action의 idempotency key는 mutation 변수에 포함하여 같은 네트워크 시도 동안
  유지한다.
- 성공 후 관련 query group만 invalidate한다. placeholder row의 mutation 버튼은
  비활성화한다.
