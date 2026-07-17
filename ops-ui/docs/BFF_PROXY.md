# Ops UI BFF Proxy

브라우저 코드는 FastAPI를 직접 호출하지 않는다.

```text
Browser openapi-fetch
  -> /ops/api/backend/*
  -> Next route handler
  -> CODEX_OPS_BACKEND_BASE_URL
  -> FastAPI
```

## 구현

- `src/lib/api.ts`: 브라우저 `openapi-fetch` client와 Server Component client.
- `src/app/api/backend/[...path]/route.ts`: method, query, body와 허용 헤더를 전달한다.
- 기본 backend는 `http://127.0.0.1:8000`이며 브라우저 bundle에 이 주소를 넣지 않는다.
- `Content-Type`, `Accept`, `X-Operator-Reason`만 명시적으로 전달한다.

브라우저 client의 base URL은 현재 origin에 `/ops/api/backend`를 붙인다. 이는 production과
MSW 테스트 모두 동일 출처 계약을 사용하게 한다.

## Smoke check

로컬 배포 후 다음 두 경로를 모두 확인한다.

```text
/ops
/ops/api/backend/ops/summary
```

첫 경로는 Next shell, 두 번째 경로는 BFF와 FastAPI 연결을 검증한다.
