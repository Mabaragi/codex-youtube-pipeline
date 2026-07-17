# Ops UI API Contract

프런트엔드 계약은 FastAPI OpenAPI에서 생성한다.

## 파일과 명령

- `openapi/codex-api.openapi.json`: FastAPI schema export.
- `src/generated/codex-api.ts`: `openapi-typescript` 생성 타입.

```powershell
pnpm --filter codex-sdk-ops-ui api:export
pnpm --filter codex-sdk-ops-ui api:generate
pnpm --filter codex-sdk-ops-ui api:check
```

`api:check`는 실행 전후 두 생성 파일의 SHA-256을 비교한다. dirty worktree에 의도된 API
변경이 있어도 오탐하지 않으며, 현재 파일이 backend와 어긋나 재생성될 때만 실패한다.

## v2 운영 계약

- `GET /ops/automation/processes`: 검증된 process identity만 반환하며 command line과
  저장소 경로는 노출하지 않는다.
- `GET /ops/workflows`, `GET /ops/work-batches`: 최신 ID 순 cursor 목록.
- destructive channel, streamer, transcript, knowledge relationship, prompt archive 요청은
  `X-Operator-Reason`이 필수다.
- 브라우저는 한국어 사유를 percent-encode하고 BFF가 헤더를 전달한다. FastAPI는 decode한
  뒤 공백 제거 및 3~500자 검증을 수행한다.

feature hook은 `src/features/<owner>/api.ts`에 두고 생성 schema 타입을 그대로 사용한다.
API 경로, request body, response DTO를 수동 타입으로 다시 작성하지 않는다.
