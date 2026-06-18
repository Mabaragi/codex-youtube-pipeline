# Frontend Architecture

The ops UI is a Next.js App Router application mounted at `/ops`.

## Runtime Shape

- Nginx applies Basic Auth and proxies `/ops` to the `ops-ui` service.
- Next.js proxies backend calls through `/ops/api/backend/*`.
- The BFF targets `CODEX_OPS_BACKEND_BASE_URL`, which is `http://api:8000` in
  Docker Compose.
- Browser code never calls the FastAPI container directly.

## State Boundaries

- TanStack Query owns server state and mutation invalidation.
- Zustand owns local UI state such as filters and selected ERD table.
- TanStack Table owns table rendering state.
- React Flow is isolated under the ERD feature and loaded dynamically.

## Screen Map

- `/ops`: API/storage health, counts, recent failures.
- `/ops/channels`: channel inventory and manual collect actions.
- `/ops/videos`: stored videos and latest task/transcript state.
- `/ops/tasks`: durable video task state and retry actions.
- `/ops/jobs`: pipeline jobs and retry actions.
- `/ops/erd`: React Flow schema viewer from `/ops/schema-graph`, including
  table groups, PK/FK/UQ/IX badges, relation metadata, and constraint/index
  inspector panels.

## Mutation Rules

Mutations call existing FastAPI write APIs through the BFF. After success, they
invalidate both `ops` and `pipeline` query groups because task/job updates affect
multiple screens.
