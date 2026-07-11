# YouTube Data Pipeline

## Stages

1. `channel_resolve` stores canonical YouTube channel and uploads playlist IDs.
2. `video_collect` pages the uploads playlist, enriches candidates with
   `videos.list`, and stores embeddable status.
3. `transcript_collect` stores transcript metadata and raw JSON in MinIO.
4. `transcript_cue_generate` converts transcript segments into stable cue IDs.
5. `micro_event_extract` processes bounded cue windows and persists normalized
   events, exclusions, corrections, warnings, and repair history.
6. `timeline_compose` merges micro-events into blocks, episodes, topic clusters,
   review flags, and user-facing copy.
7. `archive_publish` writes immutable R2 artifacts and syncs the public D1
   catalog when configured.

## Work Lifecycle

Statuses are:

- `pending`: eligible after dependencies and availability time.
- `running`: owned by a worker lease.
- `succeeded`: output committed; inspect `outcomeCode` for domain outcomes.
- `failed`: execution failed and may be retried.
- `timed_out`: timeout is recorded on both item and attempt.
- `blocked`: an upstream dependency failed.
- `canceled`: operator or eligibility policy stopped execution.

`no_transcript` is `succeeded + outcome_code=no_transcript`. A later check is a
new attempt requested with `recheckNoTranscript=true`.

## Worker Engine

Transcript, cue, micro-event, and timeline processes use the same DB-polling
engine. Claim is atomic, creates an attempt, and grants a lease. A heartbeat
extends the lease. Expired leases become timed-out attempts and can be retried.

Dependencies are explicit. The coordinator creates the next stage only after
the actual upstream output is known, so a timeline cannot run against a guessed
micro-event result.

## Scheduler

`codex-pipeline-scheduler` periodically:

1. collects channel videos when the channel interval is due;
2. enqueues bounded transcript work for new videos;
3. rechecks old no-transcript outcomes on their separate interval.

It does not run micro-events or timelines directly. The workflow coordinator is
responsible for full process-to-publish runs.

## Validation And Recovery

Micro-event output is normalized before hard invariant validation. Recoverable
enum, topic, evidence, and nearby cue-ID drift becomes warnings. Coverage gaps
can request one LLM repair and are logged. Invalid JSON or unrepaired coverage
failure remains hard failure.

Timeline output similarly normalizes viewer tags and bounded arrays, repairs
selected coverage/semantic issues, and records warnings. Complete ordered
micro-event coverage and block membership remain hard invariants.

## Embeddable Policy

`videos.list(status)` stores `is_embeddable`. A false value is excluded from
transcript, cue, micro-event, timeline, workflow, and archive selection unless
an internal command explicitly sets `includeNonEmbeddable=true`. Unknown legacy
rows remain eligible until refreshed.

## Observability

- `work_attempts`: execution errors and outputs.
- `operation_events`: work/batch/channel/video timeline.
- `codex_run_usages`: model/token usage with work provenance.
- `external_api_calls`: sanitized metadata and raw object-storage pointers.
- window/timeline warnings: normalized or repaired LLM output history.

Use `GET /ops/events?workItemId=...` and `GET /ops/work-items/{id}` together for
diagnosis.
