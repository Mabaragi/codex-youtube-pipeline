# R2 Archive Publish

Archive publish converts a completed timeline into public client JSON. It runs
inline through `POST /ops/operations/archive-publish`; there is no archive
worker.

## Object Layout

```text
{prefix}/channels/{environment}.json
{prefix}/archive/v{schemaVersion}/index.{version}.json
{prefix}/archive/v{schemaVersion}/videos/{videoId}/timeline.{version}.{variant}.json
```

Only the pointer is overwritten. Index and timeline objects are immutable.

- Pointer cache: `public, max-age=60`.
- Index/timeline cache: `public, max-age=31536000, immutable`.

Publish order is timeline -> local artifact row -> optional D1 catalog sync ->
index -> pointer. A pointer is never updated before all referenced objects are
available.

## Configuration

```text
CODEX_CLI_ARCHIVE_PUBLISH_R2_ENDPOINT=https://<ACCOUNT_ID>.r2.cloudflarestorage.com
CODEX_CLI_ARCHIVE_PUBLISH_R2_ACCESS_KEY=...
CODEX_CLI_ARCHIVE_PUBLISH_R2_SECRET_KEY=...
CODEX_CLI_ARCHIVE_PUBLISH_R2_BUCKET=...
CODEX_CLI_ARCHIVE_PUBLISH_PUBLIC_BASE_URL=https://<public-domain>
CODEX_CLI_ARCHIVE_PUBLISH_PREFIX=archive
CODEX_CLI_ARCHIVE_PUBLISH_ENVIRONMENT=prod
```

Optional D1 sync:

```text
CODEX_CLI_ARCHIVE_PUBLIC_CATALOG_SYNC_ENABLED=true
CODEX_CLI_ARCHIVE_PUBLIC_CATALOG_SYNC_URL=https://<pages-domain>/api/admin/archive/videos/upsert
CODEX_CLI_ARCHIVE_PUBLIC_CATALOG_SYNC_TOKEN=...
CODEX_CLI_ARCHIVE_PUBLIC_CATALOG_SYNC_TIMEOUT_SECONDS=15
```

R2 buckets and public access must already exist. Ops APIs never return access or
secret keys.

## Publish

```json
{
  "selection": {"type": "selected", "videoIds": [101, 102]},
  "publishMode": "prod",
  "environment": "prod",
  "variant": "control",
  "schemaVersion": 1,
  "retryFailed": true,
  "rerunSucceeded": false
}
```

Use `rerunSucceeded=true` to create a new immutable version from the current
source timeline. Non-embeddable videos are skipped by default.

Inspect state with:

```text
GET /ops/archive/current?publishMode=prod
GET /ops/archive/videos?environment=prod&limit=50
```

## Artifact Contract

Timeline JSON includes:

- public video, streamer, and channel metadata;
- timeline summary;
- blocks -> episodes -> micro-events;
- top-level episode compatibility projection;
- topic clusters and playback millisecond anchors.

It excludes transcript text, raw model responses, internal cue/candidate IDs,
repair diagnostics, work IDs, and secrets.

D1 receives list/search metadata and public hierarchy identifiers. Detailed
timeline rendering continues to read the immutable R2 URL.

## Failure And Retry

A storage, build, persistence, or catalog sync error fails the archive work
item. Inspect `GET /ops/work-items/{workItemId}` and correlated events, then use
`POST /ops/work-items/{workItemId}/retry` for the same input. Submit a new
archive operation when environment, variant, or schema version must change.
