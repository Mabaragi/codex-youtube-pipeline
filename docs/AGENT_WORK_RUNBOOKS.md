# Agent Work Runbooks

Operational runbooks for agents. Keep `/openapi.json` open for exact schemas and
use `docs/AGENT_API_OPERATIONS.md` for endpoint catalog details.

## Micro-Event To Publish Batch

Use this when the user asks to process cue-ready videos through publish.

1. Find candidates:
   `GET /ops/candidates/micro-event-ready?category=readyNoHistory&limit=200`.
2. Pick the requested videos. Prefer newest items unless the user names a
   channel, streamer, or explicit IDs.
3. Run the full pipeline:
   `POST /video-tasks/process-to-publish` with `videoIds`,
   `microReasoning`, `timelineReasoning`, `retryFailed=true`, and the requested
   `publishMode`.
4. Report per-video `items[]`: `status`, `reason`, micro task, timeline task,
   publish artifact URL.
5. If the API returns wait timeout, do not cancel the worker task. Tell the user
   the task is still running and continue tracking through `/ops/video-tasks`.

Prefer `process-to-publish` over manual stage calls for ordinary batches.

## Timeline-Ready Batch

Use this when micro-events already succeeded and only timeline/publish remains.

1. Find candidates:
   `GET /ops/candidates/timeline-ready?category=readyNoHistory&limit=200`.
2. Enqueue timeline:
   `POST /video-tasks/timeline-compose/enqueue` with `target=selected_videos`,
   deduped `videoIds`, `retryFailed=true`, and requested `reasoningEffort`.
3. Track `timeline_compose` tasks through
   `GET /ops/video-tasks?taskName=timeline_compose&limit=200`.
4. Publish successes:
   `POST /video-tasks/archive-publish` with `target=selected_videos`,
   successful `videoIds`, `regenerateSucceeded=true`, and the requested
   `publishMode`.
5. Report the resulting artifact URLs and any skipped/failed videos.

Do not assume latest task status means result absence. Confirm whether a
succeeded timeline exists via candidate/detail endpoints.

## Failed Job Or Timed-Out Task

1. List failures:
   `GET /ops/video-tasks?taskName=micro_event_extract&status=failed&limit=200`
   or the timeline equivalent. Check `status=timed_out` separately when a task
   exceeded its execution timeout.
2. Inspect job detail:
   `GET /pipeline/jobs/{jobId}`.
3. For timeline failures, read failed attempt
   `outputJson.rawResponses[*].rawResponseText` when present.
4. If the pipeline job itself has status `failed` and the same input is desired,
   use `POST /pipeline/jobs/{jobId}/retry`.
5. If the linked task is `timed_out`, or model/reasoning must change, re-enqueue
   the task through its task endpoint with `retryFailed=true`. Job retry reuses
   original input and does not accept `timed_out` as a job status.
6. For stale running tasks, use:
   `uv run codex-demo ops detect-stuck --task micro_event_extract --minutes 15`
   or `timeline_compose`.

Micro-event `retryFailed=true` can reuse succeeded partial windows and rerun
failed/missing windows when the cue window shape still matches.

## Timeline Patch

Use patch API before direct DB edits.

1. Resolve target video and timeline:
   `GET /ops/videos?search={youtubeVideoId}&limit=20`, then
   `GET /videos/{videoId}/timelines/latest`.
2. Convert the user's natural-language instruction into structured operations.
   Supported v1 operations include:
   `split_block_after_episode`, `edit_display_copy`,
   `edit_topic_cluster_copy`, and `edit_micro_event_copy`.
3. Dry-run first:
   `POST /videos/{videoId}/timelines/{videoTaskId}/patch` with
   `dryRun=true`.
4. Check `before`, `after`, operation results, and validation warnings.
5. Apply with publish only after dry-run is sane:
   `dryRun=false`, `publish.enabled=true`, `environment`, `variant`,
   `schemaVersion`.
6. Verify R2 output using the publish result URL.

Patch API changes display copy and micro-event `event` safely. It does not yet
support episode `summary`, episode `topics`, or micro-event `topics`.

## Published Data Correction

Use this when the user asks to change already-published data.

1. Search existing workflow first: timeline patch, archive publish, and domain
   knowledge APIs. If no safe workflow exists, stop and explain the gap.
2. Identify the video by YouTube ID with `/ops/videos?search=...`.
3. Read latest timeline and source micro-event task.
4. Locate the bad text in timeline fields and micro-event fields.
5. If only supported patch fields are affected, use Timeline Patch.
6. If unsupported fields are affected, stop before direct DB edits unless the
   user explicitly accepts DB source correction.
7. After correction, republish exactly the affected video with
   `POST /video-tasks/archive-publish` and `regenerateSucceeded=true`.
8. Verify the public artifact:
   pointer URL -> current index -> video `timelineVariants[].url` -> timeline
   JSON. Decode as UTF-8 and check old/new text.

Never edit raw LLM response text, trace raw response files, or prompt packs for
a published-data typo fix.

## Domain Knowledge And ASR Alias

Use this when a repeated ASR/caption error should influence future LLM work.

1. Check duplicates:
   `GET /domain-entries?q={canonicalOrAlias}&active=true&limit=20`.
2. Use an existing type when possible. Common types include `Game`, `Content`,
   `Person`, `Term`, and `Meme`.
3. Create a domain entry:
   `POST /domain-entries` with `promptPolicy=AUTO_ON_MATCH`.
4. For ASR-only corrections, add an alias with:
   `aliasKind=ASR_ERROR`, `certainty=HIGH`, and
   `applyScope=SEARCH_AND_SUMMARY`.
5. Keep the detail explicit: canonical form, mistaken surface form, and “use
   only when the surface appears in input.”
6. Verify the entry is active and the alias is present.

`AUTO_ON_MATCH` means micro-event and timeline prompts include the entry only
when the cue/event/topic text contains the canonical name, display name, or one
of its aliases.

## LLM Trace Inspection

Trace root defaults to `.home-deploy/logs/llm-traces/YYYY-MM-DD/`.

- Micro-event events: `micro_event_extract.jsonl`
- Timeline events: `timeline_compose.jsonl`
- Raw responses: `raw/*.response.txt`

Useful phases:

- Micro-event: `window_started`, `llm_response_received`, `parse_failed`,
  `validation_failed`, `repair_requested`, `repair_response_received`,
  `window_retry_started`, `window_retry_succeeded`, `task_failed`.
- Timeline: `compose_started`, `compose_response_received`,
  `compose_validation_failed`, `repair_requested`, `repair_response_received`,
  `compose_succeeded`, `compose_failed`.

JSONL stores raw response path/hash/length and prompt hash/length. It does not
store raw prompt text.

## R2 Publish Verification

1. Get current pointer:
   `GET /ops/archive/current?publishMode=prod` or `publishMode=dev`.
2. Fetch `latestPublication.publicUrl` or the pointer object's
   `currentIndexUrl`.
3. Find the video row by `youtubeId`.
4. Fetch `timelineVariants[].url`.
5. Parse as UTF-8 JSON. Check expected fields, old/new text, episode count, and
   event count.
6. For dev review, use `publishMode=dev` and `environment=dev`; never infer dev
   status from prod pointer URLs.

PowerShell may produce mojibake if the console encoding is wrong. Prefer JSON
parsing with UTF-8 bytes when verifying Korean text.
