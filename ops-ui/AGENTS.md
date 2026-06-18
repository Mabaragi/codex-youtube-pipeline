# Ops UI Agent Guide

## Purpose

This directory contains the Next.js operational console for the FastAPI backend.
Frontend agents should keep their default context inside `ops-ui/` and the
generated OpenAPI contract.

## Reading Order

1. Root `AGENTS.md`.
2. This `ops-ui/AGENTS.md`.
3. `ops-ui/docs/INDEX.md`.
4. `ops-ui/docs/FRONTEND_ARCHITECTURE.md` for UI runtime, state, routing, or
   screen structure work.
5. `ops-ui/docs/BFF_PROXY.md` when browser/backend calls, proxy routes, or
   deployment wiring change.
6. `ops-ui/docs/API_CONTRACT.md` when API calls or generated types change.
7. Relevant UI code and tests.

## Boundaries

- Do not read backend domain guides for pure UI layout or component work.
- Read backend docs only when changing FastAPI endpoints, OpenAPI generation, or
  deployment wiring shared with the backend.
- Treat `ops-ui/openapi/codex-api.openapi.json` and
  `ops-ui/src/generated/codex-api.ts` as the frontend contract.
- Keep browser calls behind the Next BFF at `/ops/api/backend/*`.
- Keep BFF details in `ops-ui/docs/BFF_PROXY.md` instead of repeating the full
  proxy explanation in this guide.

## Implementation Rules

- Use TanStack Query for server state.
- Use Zustand only for local UI state that spans components.
- Use TanStack Table for operational tables.
- Keep React Flow ERD code isolated from ordinary pages and load it dynamically.
- Do not duplicate backend DTO types by hand when generated OpenAPI types exist.

## Verification

Run these for frontend changes:

```powershell
pnpm --filter codex-sdk-ops-ui api:check
pnpm --filter codex-sdk-ops-ui lint
pnpm --filter codex-sdk-ops-ui typecheck
pnpm --filter codex-sdk-ops-ui test
pnpm --filter codex-sdk-ops-ui build
```

## Deployment Pitfalls

- `pnpm --filter codex-sdk-ops-ui build`만으로 Home PC 배포 가능성을 판단하지
  않는다. Docker or Compose wiring을 바꿨다면
  `docker compose -f compose.home.yaml build ops-ui`도 확인한다.
- Next standalone output은 monorepo path를 포함한다. Runtime server는
  `/app/ops-ui/server.js`에서 뜨고, static assets는
  `/app/ops-ui/.next/static` 아래에 있어야 한다.
- Browser API calls stay under `/ops/api/backend/*`; only the Next BFF calls
  `CODEX_OPS_BACKEND_BASE_URL`.
- 배포 검증은 `/ops` page뿐 아니라 `/ops/api/backend/ops/summary`도 확인한다.
  page가 떠도 BFF-to-FastAPI wiring이 깨질 수 있다.
- Windows PowerShell 5.1 deploy checks that call `Invoke-WebRequest` against
  Next HTML must use `-UseBasicParsing`.
