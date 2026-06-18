# Ops UI Agent Guide

## Purpose

This directory contains the Next.js operational console for the FastAPI backend.
Frontend agents should keep their default context inside `ops-ui/` and the
generated OpenAPI contract.

## Reading Order

1. Root `AGENTS.md`.
2. This `ops-ui/AGENTS.md`.
3. `ops-ui/docs/FRONTEND_ARCHITECTURE.md`.
4. `ops-ui/docs/API_CONTRACT.md` when API calls or generated types change.
5. Relevant UI code and tests.

## Boundaries

- Do not read backend domain guides for pure UI layout or component work.
- Read backend docs only when changing FastAPI endpoints, OpenAPI generation, or
  deployment wiring shared with the backend.
- Treat `ops-ui/openapi/codex-api.openapi.json` and
  `ops-ui/src/generated/codex-api.ts` as the frontend contract.
- Keep browser calls behind the Next BFF at `/ops/api/backend/*`.

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
