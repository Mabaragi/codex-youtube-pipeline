# Frontend Architecture

The ops UI is a Next.js App Router application mounted at `/ops`.

## Runtime Shape

- The local native runtime runs the Ops UI as a Windows process on
  `127.0.0.1:3000`; Docker is used only for local infrastructure such as MinIO.
- Next.js proxies backend calls through `/ops/api/backend/*`.
- The BFF targets `CODEX_OPS_BACKEND_BASE_URL`, normally
  `http://127.0.0.1:8000` in `.home-deploy/local.env`.
- Browser code never calls FastAPI directly.

Read `ops-ui/docs/BFF_PROXY.md` before changing browser/backend calls, proxy
route behavior, or deployment wiring around `CODEX_OPS_BACKEND_BASE_URL`.

## State Boundaries

- TanStack Query owns server state and mutation invalidation.
- Zustand owns local UI state such as filters and selected ERD table.
- TanStack Table owns table rendering state.
- React Flow is isolated under the ERD feature and loaded dynamically.

## Screen Map

- `/ops`: API/storage health, counts, recent failures.
- `/ops/channels`: channel inventory and manual collect actions.
- `/ops/videos`: stored videos and latest task/transcript state.
- `/ops/videos/[videoId]`: one video’s task, transcript, micro-event, and
  timeline detail.
- `/ops/archive`: current dev/prod archive pointers and published artifacts.
- `/ops/tasks`: durable video task state and retry actions.
- `/ops/jobs`: pipeline jobs and retry actions.
- `/ops/logs`: operation event timeline with linked job/task/channel/video filters.
- `/ops/usage`: Codex usage aggregates and per-video/job usage views.
- `/ops/prompts`: public-safe prompt-version administration.
- `/ops/domain-knowledge`: domain entry, alias, and streamer-scope management.
- `/ops/erd`: React Flow schema viewer from `/ops/schema-graph`, including
  table groups, PK/FK/UQ/IX badges, column-level relationship anchors,
  crow's-foot cardinality markers, relation metadata, and constraint/index
  inspector panels.

## Mutation Rules

Mutations call existing FastAPI write APIs through the BFF. After success, they
invalidate both `ops` and `pipeline` query groups because task/job updates affect
multiple screens.
