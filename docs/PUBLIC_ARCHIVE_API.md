# Public archive API

The FastAPI server exposes the local SQL publication catalog through a
Planetip-compatible, read-only HTTP contract. It does not read the control
database, canonical artifacts, unpublished timelines, or remote D1 data.

The default scope is the local StelLive Cliche publication:

```text
profileKey  stellive-cliche-local
publishMode prod
environment prod
catalog     local-public-catalog
```

Configure that scope through `CliSettings` without putting a database DSN in
the browser:

```env
CODEX_CLI_PUBLIC_ARCHIVE_CATALOG_CONNECTION_REF=local-public-catalog
CODEX_CLI_PUBLIC_ARCHIVE_PROFILE_KEY=stellive-cliche-local
CODEX_CLI_PUBLIC_ARCHIVE_PUBLISH_MODE=prod
CODEX_CLI_PUBLIC_ARCHIVE_CORS_ORIGINS=["http://127.0.0.1:3001","http://localhost:3001"]
```

The connection registry remains the only source of the catalog DSN. PostgreSQL
requests run in read-only transactions.

## Frontend base URL

Point the local Planetip frontend at the FastAPI server:

```env
VITE_ARCHIVE_API_BASE_URL=http://127.0.0.1:8000
```

The existing frontend paths then resolve without a D1 adapter change:

```text
GET  /api/archive/videos
GET  /api/archive/videos/{videoId}
HEAD /api/archive/videos/{videoId}
GET  /api/archive/streamers
GET  /api/archive/catalog-version
```

`videos` accepts the existing `environment`, `sort`, `limit`, `cursor`, `q`,
`streamerId`, `channelId`, `youtubeVideoId`, and `includeStats` query
parameters. Cursor values use the existing URL-safe base64 payload containing
`publishedAt` and `videoId`. Numeric legacy IDs and 11-character YouTube IDs
both work on the detail route.

The response retains the D1 field names, including `youtubeId`, `streamer`,
`channel`, `timelineVariants`, `nextCursor`, and `totalCount`. The SQL catalog
does not store interaction analytics, so the three optional counters are
returned as zero when `includeStats=true`.

## Data authority

The SQL catalog is authoritative for list membership, search, streamer counts,
detail availability, and timeline URLs. A video with `is_embeddable=false` is
not served. MinIO only serves the timeline URL recorded in the selected catalog
row; the API does not reconstruct a list from object-store pointers or indices.

`catalog-version` returns a stable string derived from the latest catalog row
update and current row count. The frontend can continue polling this endpoint
to invalidate its cached list.
