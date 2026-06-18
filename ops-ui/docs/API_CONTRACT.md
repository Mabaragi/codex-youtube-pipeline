# API Contract

The frontend contract is generated from the FastAPI OpenAPI schema.

## Files

- `ops-ui/openapi/codex-api.openapi.json`: exported FastAPI schema.
- `ops-ui/src/generated/codex-api.ts`: generated TypeScript types.

## Commands

```powershell
pnpm --filter codex-sdk-ops-ui api:export
pnpm --filter codex-sdk-ops-ui api:generate
pnpm --filter codex-sdk-ops-ui api:check
```

`api:check` exports and regenerates the contract, then fails if generated files
have uncommitted diffs.

## Rules

- Do not hand-write backend DTO types in frontend code.
- Backend endpoint shape changes must update the generated contract.
- Frontend agents can rely on generated types without reading backend internals.
