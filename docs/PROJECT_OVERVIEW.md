# Project Overview

This project builds a local production pipeline for long-form YouTube VODs.
It collects metadata and transcripts, derives prompt-friendly cues, extracts
micro-events, composes a navigable timeline, and publishes a public archive.

## Product Flow

```text
channel resolve -> video collect -> transcript collect -> cue generation
    -> micro-event extraction -> timeline composition -> R2/D1 publish
```

Official YouTube transcripts are preferred. The CLI also supports local
faster-whisper experiments for videos without retrievable captions.

## Operational Model

Every requested stage is represented by a `work_item`; every execution is a
`work_attempt`. Dependencies decide which pending work can be claimed. Batches
record operator selection, and workflow runs coordinate one video through all
downstream stages.

Work state is exposed only through:

- `/ops/operations/*`
- `/ops/work-items*`
- `/ops/work-batches/*`
- `/ops/workflows/*`

The old public video-task and pipeline-job mutation APIs are not mounted.

## Storage

- PostgreSQL: normalized metadata, concurrent work state, outputs, provenance,
  usage, and events. SQLite remains the fast isolated test database.
- MinIO: raw transcript and external API-call JSON.
- R2: immutable public timeline/index artifacts plus a short-cache pointer.
- D1: public list/search hierarchy and interaction analytics.

Raw transcript text, LLM trace output, and secrets are not committed.

## Backend Boundaries

- `domains`: framework-free models and policies.
- `application`: use cases, workflows, and ports.
- `infra`: persistence and external adapters.
- `bootstrap`: settings projection and dependency composition.
- `api`, `workers`, `cli`: entrypoints.

New transactional paths use a Unit of Work. Generic workers share claim,
lease, heartbeat, timeout, recovery, and attempt recording.

See `docs/CLEAN_ARCHITECTURE.md` for enforced boundaries and the compatibility
adapter note.

## Ops UI

The Next.js UI uses the same-origin BFF at `/ops/api/backend/*`. TanStack Query
owns server state; generated OpenAPI types are the frontend contract. Main
screens cover overview, channels, videos, work, logs, usage, archive, prompts,
domain knowledge, and ERD.

## Configuration

All backend settings use the `CODEX_CLI_` prefix. Copy
`scripts/local-home/local.env.example` to the ignored
`.home-deploy/local.env`. Important groups are:

- database and MinIO;
- YouTube API and transcript proxy;
- model/reasoning/prompt defaults;
- scheduler and worker concurrency;
- R2 and public catalog sync;
- local trace settings.

## Operations

- API catalog: `docs/AGENT_API_OPERATIONS.md`.
- Agent procedures: `docs/AGENT_WORK_RUNBOOKS.md`.
- Local deployment: `docs/LOCAL_NATIVE_DEPLOYMENT.md`.
- Work DB migration: `docs/WORK_MODEL_CUTOVER.md`.
- Archive format: `docs/ARCHIVE_PUBLISH.md`.

## Quality Gates

The backend uses pytest, Ruff including `C901 <= 10`, Pyrefly, Import Linter,
OpenAPI drift checks, and an architecture size budget. The Ops UI uses generated
contract checks, ESLint, TypeScript, Vitest, and a production Next build.
