# Ops UI BFF Proxy

Browser code in `ops-ui` never calls FastAPI directly. All backend requests go
through the Next.js BFF route.

```text
Browser UI
  -> /ops/api/backend/*
  -> Next route handler
  -> CODEX_OPS_BACKEND_BASE_URL
  -> FastAPI
```

## Source Files

- `ops-ui/src/lib/api-client.ts`: browser JSON client. `BFF_BASE_URL` always
  points to `/ops/api/backend`.
- `ops-ui/src/lib/queries.ts`: TanStack Query hooks and mutations call
  `requestJson(...)`.
- `ops-ui/src/app/api/backend/[...path]/route.ts`: Next BFF proxy route. It
  maps the browser path and query string to the FastAPI target URL and returns
  the response status/body.
- `scripts/local-home/start.ps1` and `.home-deploy/local.env`: local native
  runtime wiring for `CODEX_OPS_BACKEND_BASE_URL=http://127.0.0.1:8000`.

## Rules

- Browser-side API calls use `requestJson(...)`.
- Client components do not reference `CODEX_OPS_BACKEND_BASE_URL`,
  `localhost:8000`, `127.0.0.1:8000`, or Docker service names directly.
- Only the BFF route reads `CODEX_OPS_BACKEND_BASE_URL`.
- Browser code calls `/ops/api/backend/ops/summary`; the BFF forwards it to
  FastAPI `/ops/summary`.
- Do not duplicate backend DTO types by hand when
  `ops-ui/src/generated/codex-api.ts` has generated types.

## Deployment Checks

After local native start or deploy, check both paths:

```text
/ops
/ops/api/backend/ops/summary
```

The page can render while BFF-to-FastAPI wiring is broken, so the summary path is
the useful smoke check for API connectivity.
