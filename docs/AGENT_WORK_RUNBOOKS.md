# Agent Work Runbooks

Use these procedures with `docs/AGENT_API_OPERATIONS.md` and `/openapi.json`.
They are designed for agents that have not explored the repository.

## Process Videos Through Publish

1. Identify videos with `GET /ops/videos` or use `nextEligible`.
2. Call `POST /ops/workflows/process-to-publish`.
3. Record the returned `batchId` and each `workflowRunId`.
4. Poll `GET /ops/workflows/{workflowRunId}` until terminal.
5. For a failed step, read its `workItemId`, then inspect
   `GET /ops/work-items/{workItemId}` and
   `GET /ops/events?workItemId={workItemId}`.
6. Report artifact URLs from the workflow output or archive read model.

Do not manually enqueue every downstream step when the requested behavior is
the standard transcript -> cue -> micro-event -> timeline -> archive flow.

## Run One Stage

Use the matching `/ops/operations/*` endpoint with a shared selection DTO.
Queued responses contain item-level `workItemId`, status, and reason.

- Existing equivalent work is reused.
- Failed/timed-out work is skipped unless `retryFailed=true`.
- Succeeded work is reused unless `rerunSucceeded=true`.
- Non-embeddable videos are skipped unless explicitly overridden.

## Diagnose And Retry

1. List failures:
   `GET /ops/work-items?taskType=micro_event_extract&status=failed&limit=50`.
2. Read attempts and exact error:
   `GET /ops/work-items/{workItemId}`.
3. Read correlated warnings/events:
   `GET /ops/events?workItemId={workItemId}&limit=200`.
4. Retry the same input:
   `POST /ops/work-items/{workItemId}/retry`.
5. To change model, reasoning, prompt, or window options, submit a new operation
   command instead of retrying the old input.

Micro-event window retries preserve successful windows. Timeline repair keeps
warnings in output and events. Never erase warning history to make a run look
clean.

For automated operation, inspect `GET /ops/incidents?state=open` first. Known
transient errors are retried twice by the supervisor before they appear as open
incidents. Use the incident action endpoint only for its validated safe actions;
submit a new stage operation when model or prompt inputs must change.

For a host shutdown or deploy, request `POST /ops/automation/runtime/drain`
before stopping processes. While draining, scheduler ticks and new work/workflow
claims are blocked, but running work keeps its heartbeat and may finish. Poll
`GET /ops/automation/status` until `runtime.readyToStop=true`, then call
`POST /ops/automation/runtime/mark-stopped`. Do not substitute work-item
cancellation or data deletion for this sequence.

## Recheck No Transcript

`no_transcript` is a successful terminal outcome. A generic retry does not mean
"check again later." Submit transcript collect with:

```json
{
  "selection": {"type": "selected", "videoIds": [101]},
  "recheckNoTranscript": true
}
```

The scheduler applies the configured no-transcript recheck interval separately.

For workflow v2, no manual recheck is needed. Starting from the first
`no_transcript` completion, the workflow rechecks every 30 minutes, performs a
final check at the six-hour boundary, and only then sends the video to the
single-GPU ASR worker when necessary. A discovered transcript proceeds directly
to cue generation without creating ASR work.

## Publish Existing Timeline

1. Confirm `GET /ops/videos/{videoId}/timelines/latest` succeeds.
2. Call `POST /ops/operations/archive-publish` with a selected-video selection.
3. Use `rerunSucceeded=true` only to publish a new immutable artifact version.
4. Verify the returned work item and its latest attempt are both `succeeded`.
5. Verify `GET /ops/archive/current` and `GET /ops/archive/videos`; the latest
   artifact must have no public catalog sync error.
6. Fetch the returned R2 URL as UTF-8 JSON and verify counts and video identity.

Archive publish is inline; there is no archive worker.

If the API reports a work-state transition error after an artifact was written,
stop automatic retries. An artifact proves data-plane output, not a consistent
work item/attempt pair. Read the work detail and API log, then correct the
execution adapter or recover the interrupted inline attempt before rerunning.

## Domain Knowledge Alias

1. Search `GET /ops/domain-entries?q={surface}&active=true&limit=20`.
2. Reuse an existing entry where possible.
3. Use `ASR_ERROR` for recognition mistakes, `NICKNAME` for nicknames, and
   `ALIAS` for ordinary spelling variants.
4. Keep detail to one sentence containing only unique facts or exceptions.
5. Use `AUTO_ON_MATCH` when the entry should be injected only after canonical
   or alias text is found; use the always policy only for small essential
   context.

## Runtime Recovery

After a reboot:

```powershell
.\scripts\local-home\start.ps1
.\scripts\local-home\status.ps1
Invoke-RestMethod http://127.0.0.1:8000/health
```

Workers recover expired leases. Do not manually patch `running` rows unless a
lease has not expired and the process state has been verified.

For a work-model DB migration, follow `docs/WORK_MODEL_CUTOVER.md`; do not run
the cutover while any worker is mutating the DB.
