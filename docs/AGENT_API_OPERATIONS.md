# Agent API Operations

This is the public-safe contract for agents operating the local pipeline
without reading source code. `/openapi.json` is authoritative for exact DTOs.

Base URL: `http://127.0.0.1:8000`.

## Rules

- Use `/ops/operations/*` for commands and `/ops/work-items*` for execution
  state. Do not call removed `/video-tasks/*` or `/pipeline/jobs/*` paths.
- A queued command returns `202`; channel resolve, video collect, embed refresh,
  and archive publish execute inline and return `200`.
- Retry adds an attempt to the same work item. Set `rerunSucceeded=true` only
  when a successful result must be regenerated.
- `no_transcript`, `not_embeddable`, and `dependency_failed` are outcome/reason
  codes, not failure statuses.
- `includeNonEmbeddable` defaults to `false` and should remain false unless the
  user explicitly requests an override.
- List calls use `limit <= 200`. Work/event lists use cursor pagination.

## Shared Video Selection

Video commands use one discriminated `selection` object:

```json
{"type":"selected","videoIds":[101,102]}
```

```json
{"type":"channel","channelId":4,"limit":50}
```

```json
{"type":"filter","channelId":4,"search":"keyword","limit":50}
```

```json
{"type":"nextEligible","limit":20}
```

## Commands

| Operation | Endpoint | Mode |
| --- | --- | --- |
| Resolve channel | `POST /ops/operations/channel-resolve` | inline |
| Collect videos | `POST /ops/operations/video-collect` | inline |
| Refresh embed status | `POST /ops/operations/embed-status-refresh` | inline |
| Collect transcript | `POST /ops/operations/transcript-collect` | queued |
| Generate transcript cues | `POST /ops/operations/transcript-cue-generate` | queued |
| Extract micro-events | `POST /ops/operations/micro-event-extract` | queued |
| Compose timeline | `POST /ops/operations/timeline-compose` | queued |
| Publish archive | `POST /ops/operations/archive-publish` | inline |
| Process through publish | `POST /ops/workflows/process-to-publish` | queued workflow |

Example end-to-end request:

```json
{
  "selection": {"type": "selected", "videoIds": [101]},
  "languages": ["ko", "en"],
  "microModel": "gpt-5.5",
  "microReasoningEffort": "medium",
  "timelineModel": "gpt-5.5",
  "timelineReasoningEffort": "high",
  "retryFailed": true,
  "publishMode": "prod",
  "environment": "prod",
  "variant": "control"
}
```

The response contains `batchId` and one `workflowRunId` per selected video.

## State And Control

| Purpose | Endpoint |
| --- | --- |
| List work | `GET /ops/work-items?taskType=timeline_compose&status=failed&limit=50` |
| Work detail and attempts | `GET /ops/work-items/{workItemId}` |
| Retry | `POST /ops/work-items/{workItemId}/retry` |
| Cancel pending/running work | `POST /ops/work-items/{workItemId}/cancel` |
| Batch detail | `GET /ops/work-batches/{batchId}` |
| Workflow detail | `GET /ops/workflows/{workflowRunId}` |
| Operation events | `GET /ops/events?workItemId={workItemId}` |

Retry body:

```json
{"rerunSucceeded": false}
```

Cancel body:

```json
{"reason": "Canceled by operator."}
```

## Read Models

| Purpose | Endpoint |
| --- | --- |
| Summary | `GET /ops/summary` |
| Channels | `GET /ops/channels` |
| Videos | `GET /ops/videos?limit=50&offset=0` |
| Video detail | `GET /ops/videos/{videoId}` |
| Transcript metadata | `GET /ops/transcripts` |
| Transcript content/cues | `GET /ops/transcripts/{id}/content`, `/cues` |
| Latest micro-events | `GET /ops/videos/{videoId}/micro-events/latest` |
| Latest timeline | `GET /ops/videos/{videoId}/timelines/latest` |
| Archive state | `GET /ops/archive/current`, `GET /ops/archive/videos` |
| Usage | `GET /ops/codex-usage`, `/by-video`, `/by-job` |
| Domain knowledge | `/ops/domain-entry-types`, `/ops/domain-entries` |
| Prompts | `/ops/prompts` |

## Errors

All production errors use one envelope:

```json
{
  "error": {
    "code": "work_item.transition_not_allowed",
    "message": "Only failed or timed-out work can be retried.",
    "details": {"workItemId": 41}
  }
}
```

- `409`: state transition or idempotency conflict.
- `422`: invalid request DTO.
- `502`: upstream service/runtime failure.
- `503`: configuration, storage, or persistence unavailable.

## Polling

For a queued command, poll the returned work item until it reaches a terminal
status. For a workflow, poll the workflow run; its `steps` identify the current
work item. Do not infer completion from elapsed time or from an old legacy ID.
