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
5. `ops-ui/docs/UI_STYLE.md` when adding or changing screens, components,
   tables, forms, buttons, status feedback, or layout styling.
6. `ops-ui/docs/BFF_PROXY.md` when browser/backend calls, proxy routes, or
   deployment wiring change.
7. `ops-ui/docs/API_CONTRACT.md` when API calls or generated types change.
8. Relevant UI code and tests.

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
- Follow `ops-ui/docs/UI_STYLE.md` for visual styling and interaction patterns.

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

- Home PC deployment is local native now. Docker is used only for local
  infrastructure such as MinIO.
- `pnpm --filter codex-sdk-ops-ui build` verifies the Next.js build. Runtime
  smoke checks should hit `/ops` and `/ops/api/backend/ops/summary` after
  `scripts/local-home/start.ps1` or `scripts/local-home/deploy.ps1`.
- Browser API calls stay under `/ops/api/backend/*`; only the Next BFF calls
  `CODEX_OPS_BACKEND_BASE_URL`.
- Local native Ops UI reads `CODEX_OPS_BACKEND_BASE_URL` from the local
  environment; do not hard-code Docker service names in browser code.
- Windows PowerShell 5.1 deploy checks that call `Invoke-WebRequest` against
  Next HTML must use `-UseBasicParsing`.
