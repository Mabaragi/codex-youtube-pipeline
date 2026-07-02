# R2 Archive Publish

Archive publish turns completed `timeline_compose` results into public client
JSON artifacts on Cloudflare R2. It runs synchronously inside
`POST /video-tasks/archive-publish`: the API request creates the
`archive_publish` video task/job/attempt, uploads the video timeline, rebuilds
the index, updates the pointer, and then returns the per-video result.

The default `publishMode` is `prod`. Dev review publishes use the same DB
timeline/micro-event source data but write to a separate dev R2 profile, so data
contract changes can be checked without touching the prod pointer or artifacts.

There is no active archive publish worker. Archive publish is handled
synchronously by the API request.

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

Optional dev review storage:

```text
CODEX_CLI_ARCHIVE_PUBLISH_DEV_R2_BUCKET=...
CODEX_CLI_ARCHIVE_PUBLISH_DEV_PUBLIC_BASE_URL=https://<dev-public-bucket-or-domain>
CODEX_CLI_ARCHIVE_PUBLISH_DEV_PREFIX=archive-dev
CODEX_CLI_ARCHIVE_PUBLISH_DEV_ENVIRONMENT=dev

# Optional. If omitted, dev mode reuses the prod endpoint/key/secret/secure
# values above and only separates the bucket/base URL/prefix.
CODEX_CLI_ARCHIVE_PUBLISH_DEV_R2_ENDPOINT=https://<ACCOUNT_ID>.r2.cloudflarestorage.com
CODEX_CLI_ARCHIVE_PUBLISH_DEV_R2_ACCESS_KEY=...
CODEX_CLI_ARCHIVE_PUBLISH_DEV_R2_SECRET_KEY=...
CODEX_CLI_ARCHIVE_PUBLISH_DEV_R2_SECURE=true
```

The app does not create R2 buckets. The bucket and public access must already be
configured in Cloudflare. Secrets are not returned by Ops APIs.

Optional public catalog sync for the user-facing Cloudflare Pages app:

```text
CODEX_CLI_ARCHIVE_PUBLIC_CATALOG_SYNC_ENABLED=true
CODEX_CLI_ARCHIVE_PUBLIC_CATALOG_SYNC_URL=https://<pages-domain>/api/admin/archive/videos/upsert
CODEX_CLI_ARCHIVE_PUBLIC_CATALOG_SYNC_TOKEN=...
CODEX_CLI_ARCHIVE_PUBLIC_CATALOG_SYNC_TIMEOUT_SECONDS=15
```

When this is configured, publish first uploads the R2 timeline artifact, then
upserts one public metadata row into the Pages project's D1 database. The D1 row
is only for listing, search, filtering, and pagination. The timeline detail JSON
continues to load from R2 via the published `timelineUrl`.

Catalog sync failure marks the current publish item/task/job as failed. The
already-created R2 artifact row records `public_catalog_sync_error`, and retry or
regenerate can publish it again after the Pages admin API is fixed. If sync is
disabled or URL/token is not configured, archive publish keeps the previous
R2-only behavior.

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
  "publishMode": "prod",
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

Dev review publish:

```json
{
  "target": "selected_videos",
  "videoIds": [101, 102],
  "publishMode": "dev",
  "schemaVersion": 1,
  "regenerateSucceeded": true
}
```

When `publishMode` is `dev`, omitted values default to `environment=dev` and
`variant=dev-preview`. `publishMode=dev` with `environment=prod` is rejected so
dev artifacts cannot appear under a prod-looking namespace.

Process through micro-event, timeline, and dev publish in one request:

```json
{
  "videoIds": [101, 102],
  "microReasoning": "medium",
  "timelineReasoning": "medium",
  "retryFailed": true,
  "publishMode": "dev"
}
```

Inspect current archive publication:

```http
GET /ops/archive/current?environment=prod
```

Inspect the dev pointer and frontend review URL:

```http
GET /ops/archive/current?publishMode=dev
```

Use `latestPublication.publicUrl` from that response as the frontend dev data
pointer. It resolves to the dev bucket/base URL and does not modify the prod
pointer.

List video publish state:

```http
GET /ops/archive/videos?environment=prod&publishStatus=ready&limit=50
```

For dev artifacts, query `environment=dev`.

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
