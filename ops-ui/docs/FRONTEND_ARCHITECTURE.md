# Frontend Architecture

The Ops UI is a Next.js App Router application mounted at `/ops`.

## Runtime

- Browser requests use the same-origin BFF at `/ops/api/backend/*`.
- The BFF targets `CODEX_OPS_BACKEND_BASE_URL`, normally
  `http://127.0.0.1:8000`.
- Browser modules never call FastAPI directly.

## State

- TanStack Query owns server state, mutations, and invalidation.
- Zustand owns cross-component local UI state only.
- TanStack Table owns table view state.
- React Flow is isolated to the ERD feature and loaded dynamically.

## Feature API Boundary

Server calls are split under `src/features`:

- `work/api.ts`: work items, attempts, retry, cancel.
- `videos/api.ts`: video reads and operation commands.
- `archive/api.ts`: archive reads and publish.
- `observability/api.ts`: events and usage.
- `catalog/api.ts`: channels, prompts, and domain catalog reads.
- `query-keys.ts`: shared invalidation keys.

`src/lib/queries.ts` is a compatibility re-export barrel, not the owner of new
query logic. Add new hooks to the owning feature module.

## Screens

- `/ops`: runtime health and recent state.
- `/ops/channels`: channel inventory and collect commands.
- `/ops/videos`: video selection and pipeline commands.
- `/ops/videos/[videoId]`: transcript, cue, micro-event, and timeline detail.
- `/ops/tasks`: unified work items, outcome, lease, retry, and cancel.
- `/ops/jobs`: redirect to `/ops/tasks` for old bookmarks.
- `/ops/logs`: operation events filtered by work item/attempt/batch.
- `/ops/archive`: R2/D1 publish state.
- `/ops/usage`, `/ops/prompts`, `/ops/domain-knowledge`, `/ops/erd`:
  observability and administration.

## Mutation Rules

Commands call `/ops/operations/*` or `/ops/workflows/*`. After success,
invalidate the affected video/archive projection plus work and event query
groups. Do not recreate legacy video-task or pipeline-job mutations in the UI.
