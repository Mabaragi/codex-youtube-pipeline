# R2 Archive Publish

Archive publish turns completed `timeline_compose` results into public client
JSON artifacts on Cloudflare R2. It runs synchronously inside
`POST /video-tasks/archive-publish`: the API request creates the
`archive_publish` video task/job/attempt, uploads the video timeline, rebuilds
the index, updates the pointer, and then returns the per-video result.

There is no active archive publish worker. The old worker implementation is kept
under `legacy/` only as historical reference.

## Object Model

The public archive uses a pointer -> index -> video timeline structure.

```text
{prefix}/channels/{environment}.json
{prefix}/archive/v{schemaVersion}/index.{version}.json
{prefix}/archive/v{schemaVersion}/videos/{videoId}/timeline.{version}.{variant}.json
```

Only the pointer object is overwritten. Index and timeline objects are versioned
and treated as immutable.

Cache headers:

- pointer: `public, max-age=60`
- index and timeline: `public, max-age=31536000, immutable`

## Environment

Set these in `.home-deploy/local.env` before publishing to R2:

```text
CODEX_CLI_ARCHIVE_PUBLISH_R2_ENDPOINT=https://<ACCOUNT_ID>.r2.cloudflarestorage.com
CODEX_CLI_ARCHIVE_PUBLISH_R2_ACCESS_KEY=...
CODEX_CLI_ARCHIVE_PUBLISH_R2_SECRET_KEY=...
CODEX_CLI_ARCHIVE_PUBLISH_R2_BUCKET=...
CODEX_CLI_ARCHIVE_PUBLISH_R2_SECURE=true
CODEX_CLI_ARCHIVE_PUBLISH_PUBLIC_BASE_URL=https://<public-bucket-or-domain>
CODEX_CLI_ARCHIVE_PUBLISH_PREFIX=archive
CODEX_CLI_ARCHIVE_PUBLISH_ENVIRONMENT=prod
```

The app does not create R2 buckets. The bucket and public access must already be
configured in Cloudflare. Secrets are not returned by Ops APIs.

## APIs

Publish archive artifacts:

```http
POST /video-tasks/archive-publish
```

Targets:

- `next_eligible`: scan newest timeline-ready videos and publish only needed work.
- `selected_videos`: publish explicit `videoIds`.
- `current_filters`: publish newest timeline-ready videos matching `channelId`
  and `search`.

Useful body:

```json
{
  "target": "next_eligible",
  "limit": 20,
  "environment": "prod",
  "variant": "control",
  "schemaVersion": 1,
  "retryFailed": false,
  "regenerateSucceeded": false
}
```

The response includes `processedCount`, `publishedCount`,
`alreadyPublishedCount`, `failedCount`, `failedSkippedCount`, and per-video
items. A failed item does not stop later videos in the same request.

Inspect current archive publication:

```http
GET /ops/archive/current?environment=prod
```

List video publish state:

```http
GET /ops/archive/videos?environment=prod&publishStatus=ready&limit=50
```

## Artifact Contents

Timeline artifacts include playback-ready metadata:

- video metadata, channel metadata, streamer metadata, and timeline summary
- a three-level navigation hierarchy: `blocks[].episodes[].microEvents[]`
- top-level `episodes[]` as a compatibility projection of the same episode data
- episodes with `startMs`, `endMs`, display text, tags, and nested
  micro-event summaries
- micro-events with event text, program/content classification, topics,
  and playback time anchors
- topic clusters

They intentionally do not include full transcript text, raw Codex output, raw
micro-event windows, ASR correction candidates, review flags, validation
warnings, job/task IDs, source timeline IDs, micro-event candidate IDs, cue IDs,
or repair diagnostics.

The index `videos[]` row and the timeline artifact `video` object both include
the same public ownership metadata:

```json
{
  "streamer": {
    "id": 1,
    "name": "Amane Nagi"
  },
  "channel": {
    "id": 7,
    "name": "Nagi channel",
    "handle": "@nagi",
    "youtubeChannelId": "UC..."
  }
}
```

Clients should use index-level `streamer` and `channel` for listing, filtering,
and grouping. Timeline-level copies are included so detail pages do not need a
second lookup.

## Retry

Failed jobs can be retried through:

```http
POST /pipeline/jobs/{jobId}/retry
```

Retry is task-aware and only reuses an `archive_publish` task that is still
`failed` or `timed_out`. Retry also runs in the API process; no archive worker is
required.
