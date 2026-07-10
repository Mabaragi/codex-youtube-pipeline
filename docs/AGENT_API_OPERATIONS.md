# Agent API Operations

Public-safe API reference for agents operating the local YouTube data pipeline.
Use `/openapi.json` as the source of truth for exact request and response
schemas. For step-by-step procedures, read `docs/AGENT_WORK_RUNBOOKS.md`.

## Operating Principles

- Prefer API-only operations. Do not inspect source code unless the API/docs do
  not explain the behavior you need.
- Keep list requests at `limit <= 200`; the API validates this upper bound on
  Ops and pipeline list endpoints.
- Separate latest task state from stored successful results. `/ops/video-tasks`
  is a task status projection; a latest task can be `canceled` or `failed` while
  an older successful micro-event or timeline result still exists.
- Use succeeded result existence to decide whether downstream work is possible.
  For timeline provenance, check `outputJson.sourceMicroEventTaskId`.
- During API-only operation, do not restart workers. Restart only when the
  immediate task context explicitly says worker code changed and no relevant
  `running` tasks exist.
- Prefer `POST /video-tasks/process-to-publish` for end-to-end batches. Use
  lower-level enqueue/publish APIs when debugging or intentionally controlling a
  single stage.

## Status And Candidate APIs

| Purpose | Endpoint |
| --- | --- |
| Ops summary | `GET /ops/summary` |
| Videos with generation status | `GET /ops/videos?limit=200&offset=0` |
| One video detail | `GET /ops/videos/{videoId}` |
| Video tasks by task/status | `GET /ops/video-tasks?taskName=timeline_compose&status=failed&limit=200` |
| Cue-ready but no successful micro-event | `GET /ops/candidates/micro-event-ready?limit=200` |
| Micro-event succeeded but no successful timeline | `GET /ops/candidates/timeline-ready?limit=200` |
| Pipeline jobs | `GET /pipeline/jobs?step=timeline_compose&status=failed&limit=200` |
| Pipeline job detail | `GET /pipeline/jobs/{jobId}` |

Candidate categories are `readyNoHistory`, `retryableCanceled`, `failed`,
`active`, and `blocked`. Use category filters to avoid hand-combining
`/ops/videos` and `/ops/video-tasks`.

## Execution APIs

### Process To Publish

`POST /video-tasks/process-to-publish` runs micro-event enqueue/wait, timeline
enqueue/wait, then archive publish. It returns per-video success, failure, or
skip details.

```json
{
  "videoIds": [101, 102],
  "microReasoning": "medium",
  "timelineReasoning": "medium",
  "retryFailed": true,
  "waitTimeoutMinutes": 30,
  "pollIntervalSeconds": 10,
  "publishMode": "dev"
}
```

`publishMode` applies only to the final archive publish step.

### Micro-Event

Use `POST /video-tasks/micro-event-extract/enqueue` for queued worker execution.

Common body:

```json
{
  "target": "selected_videos",
  "videoIds": [101, 102],
  "limit": 2,
  "retryFailed": true,
  "reasoningEffort": "medium"
}
```

`retryFailed=true` resumes reusable partial windows when available. Succeeded
windows are reused when their transcript/window shape still matches.

### Timeline

Use `POST /video-tasks/timeline-compose/enqueue`.

Common body:

```json
{
  "target": "selected_videos",
  "videoIds": [101, 102],
  "limit": 2,
  "retryFailed": true,
  "reasoningEffort": "medium"
}
```

`POST /pipeline/jobs/{jobId}/retry` reuses the original job input. To change
model or reasoning, enqueue the video again with the desired request values
instead of retrying the old job.

### Archive Publish

Use `POST /video-tasks/archive-publish`.

```json
{
  "target": "selected_videos",
  "videoIds": [101, 102],
  "publishMode": "prod",
  "environment": "prod",
  "variant": "control",
  "schemaVersion": 1,
  "retryFailed": true,
  "regenerateSucceeded": true
}
```

Archive publish is synchronous in the API process; there is no archive worker.

## Dev And Prod Publish

`publishMode=prod` is the default. `publishMode=dev` writes the same DB-backed
timeline/micro-event data to the dev R2 profile and defaults to
`environment=dev`, `variant=dev-preview`.

- Dev pointer: `GET /ops/archive/current?publishMode=dev`
- Prod pointer: `GET /ops/archive/current?publishMode=prod`
- Dev artifact list: `GET /ops/archive/videos?environment=dev&limit=50`
- Prod artifact list: `GET /ops/archive/videos?environment=prod&limit=50`

`publishMode=dev` with `environment=prod` is rejected.

## Investigation And Repair APIs

| Task | Endpoint |
| --- | --- |
| Inspect failed raw timeline diagnostics | `GET /pipeline/jobs/{jobId}` |
| Retry a failed job with the same input | `POST /pipeline/jobs/{jobId}/retry` |
| Patch timeline display/block/micro-event copy | `POST /videos/{videoId}/timelines/{videoTaskId}/patch` |
| Read latest timeline | `GET /videos/{videoId}/timelines/latest` |
| Read specific timeline | `GET /videos/{videoId}/timelines/{videoTaskId}` |
| Read latest micro-event extraction | `GET /videos/{videoId}/micro-event-extractions/latest` |
| Read specific micro-event extraction | `GET /videos/{videoId}/micro-event-extractions/{videoTaskId}` |
| Manage domain knowledge | `/domain-entry-types`, `/domain-entries`, `/domain-entries/{id}/aliases` |

`POST /pipeline/jobs/{jobId}/retry` accepts only a job whose status is `failed`.
If the linked `video_tasks` row is `timed_out`, re-enqueue that task through its
task endpoint with `retryFailed=true` instead of treating `timed_out` as a job
status.

For failed `timeline_compose`, check failed attempt
`outputJson.rawResponses[*].rawResponseText` in `GET /pipeline/jobs/{jobId}`
when it is present. The job-detail attempt is the diagnostic source; task
projections and operation events keep only raw response hashes/lengths and do
not duplicate the full text.

## CLI Helpers

- Stuck detector:
  `uv run codex-demo ops detect-stuck --task micro_event_extract --minutes 15`
- Timeline style backfill:
  `uv run codex-demo timeline normalize-style --dry-run`
- LLM trace helper:
  `scripts/local-home/llm-traces.ps1`

LLM traces default to `.home-deploy/logs/llm-traces/YYYY-MM-DD/`. JSONL files
record phases and raw response paths; raw prompt text is intentionally not
stored.

## API Gaps And TODOs

- Archive cleanup API: `POST /ops/archive/cleanup` with `dryRun`, retention
  policy, protected pointer/latest index/latest artifact rules, and optional
  storage object deletion.
- Public read API: Worker/D1/R2 hybrid for infinite scroll, sorting, and
  filtering while R2 keeps heavy timeline detail JSON.
- Publish finalization optimization: batch publish should upload changed video
  artifacts first, then rebuild index/pointer once per batch.
- Timeline patch expansion: add structured operations for episode `summary`,
  `topics`, and micro-event `topics` so published data corrections do not need
  direct DB edits.
