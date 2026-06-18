# Ops UI BFF Proxy

`ops-ui`의 브라우저 코드는 FastAPI container를 직접 호출하지 않는다. 모든
backend 요청은 Next.js route handler가 제공하는 BFF 경로를 통과한다.

```text
Browser UI
  -> /ops/api/backend/*
  -> Next route handler
  -> CODEX_OPS_BACKEND_BASE_URL
  -> FastAPI
```

## Source Files

- `ops-ui/src/lib/api-client.ts`: 브라우저에서 사용하는 공통 JSON client다.
  `BFF_BASE_URL`은 항상 `/ops/api/backend`로 유지한다.
- `ops-ui/src/lib/queries.ts`: TanStack Query hooks와 mutations가
  `requestJson(...)`를 통해 BFF를 호출한다.
- `ops-ui/src/app/api/backend/[...path]/route.ts`: Next BFF proxy route다.
  request path와 query string을 FastAPI target URL로 옮기고, response body와
  status를 브라우저에 되돌린다.
- `compose.home.yaml`: Home stack에서 `ops-ui` service가
  `CODEX_OPS_BACKEND_BASE_URL=http://api:8000`으로 FastAPI service를 찾는다.

## Rules

- 새 browser-side API 호출은 `requestJson(...)`를 사용한다.
- client component에서 `CODEX_OPS_BACKEND_BASE_URL`, `localhost:8000`,
  `127.0.0.1:8000`, Docker service name `api`를 직접 참조하지 않는다.
- BFF route만 `CODEX_OPS_BACKEND_BASE_URL`을 읽는다.
- FastAPI path는 BFF prefix 뒤에 붙인다. 예를 들어 browser code는
  `/ops/api/backend/ops/summary`를 호출하고, BFF는 FastAPI `/ops/summary`로
  전달한다.
- backend DTO type은 hand-written type으로 복제하지 않고
  `ops-ui/src/generated/codex-api.ts`에서 가져온다.

## Deployment Checks

운영 UI 배포나 Docker wiring을 바꾼 뒤에는 page render만 확인하지 않는다.
다음 경로를 함께 확인해야 BFF-to-FastAPI 연결을 검증할 수 있다.

```text
/ops/api/backend/ops/summary
```

Home stack에서는 Nginx Basic Auth가 `/ops` 앞단에 있고, `ops-ui` container가
internal Docker network에서 `api:8000`을 호출한다. 따라서 배포 문제를 볼 때는
다음을 분리해서 확인한다.

- Browser to Nginx: Basic Auth와 `/ops` base path.
- Nginx to Next: `ops-ui` service reachability와 standalone static asset path.
- Next BFF to FastAPI: `CODEX_OPS_BACKEND_BASE_URL` 값과
  `/ops/api/backend/ops/summary` response.
