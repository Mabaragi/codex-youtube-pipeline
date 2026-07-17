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
| Automation status | `GET /ops/automation/status` |
| Request runtime drain | `POST /ops/automation/runtime/drain` |
| Mark drained runtime stopped | `POST /ops/automation/runtime/mark-stopped` |
| Resume runtime | `POST /ops/automation/runtime/resume` |
| Open incidents | `GET /ops/incidents?state=open&limit=50` |
| Incident detail | `GET /ops/incidents/{incidentId}` |
| Safe remediation | `POST /ops/incidents/{incidentId}/actions` |

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

Workflow v2 responses include `waitingReason`, `availableAt`, caption/ASR SLA
deadlines, and step outputs. While ASR is running its step output includes the
latest completed chunk count.

Incident actions are limited to `retry`, `recover_lease`, `extend_timeout`, and
`set_temporary_concurrency`. Model, prompt, code, secret, and destructive data
changes are not accepted by this endpoint.

`retry` and `extend_timeout` require an incident with a linked work item;
otherwise the API returns `422 automation.incident_action_not_allowed`.
`extend_timeout` accepts `extensionSeconds` as a bounded increment and also
supports an absolute `timeoutSeconds` value for API clients.

`GET /ops/automation/status` includes
`runtime` and `dataIntegrity.orphanVideoCount`. Runtime state is `active`,
`draining`, or `stopped`; `runningWorkItemCount`, `runningWorkflowCount`,
`runningByTaskType`, and `readyToStop` are the source of truth for a safe local
shutdown. `mark-stopped` returns `409 pipeline.runtime_not_drained` until both
running counts reach zero. Videos whose `channel_id` no longer resolves
to a channel are excluded from automatic workflow candidates and backfill
completion counts. The supervisor records one deduplicated `data_integrity`
incident with error code `pipeline.orphan_video_channel`; it does not delete or
reassign the video.

An incident `retry` action resets the failed work item and any linked failed or
blocked workflow in one transaction. Its result includes `workflowRunIds` so
the caller can poll the resumed workflows. Persistence, validator, and data
integrity error codes are not automatically retried even if their message also
contains a transient-looking word such as `connection`.
Permanent YouTube download responses such as removed or private videos are
reported as `asr.audio_unavailable`; automatic workflows do not retry them.
When an incident retry resumes a legacy automatic workflow, its historical
`retry_failed` option is cleared so downstream failures return to incident-led
recovery instead of coordinator-level blanket retries.

When a successful micro-event extraction contains zero events, timeline
composition skips Codex and stores a deterministic guidance timeline. Timeline
responses, work output, and archives report `timelineState: "empty"`,
`emptyReason: "no_micro_events"`, and
`generationMode: "deterministic_empty"`; `model`, `reasoningEffort`, and Codex
thread/turn IDs are null. The single guidance episode spans the full video and
publishes with an empty `microEvents` list.
