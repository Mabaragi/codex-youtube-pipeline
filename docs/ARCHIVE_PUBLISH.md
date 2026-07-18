# Streamer-scoped archive publication

Archive publication converts completed timelines into a canonical private
artifact and then publishes projections through the active profile assigned to
the video's streamer. It still runs inline through
`POST /ops/operations/archive-publish`; there is no publication worker.

## Data boundary

The canonical timeline JSON is stored only in the private local MinIO
connection `local-artifact-store`, normally the `archive-artifacts` bucket:

```text
artifacts/sha256/{first-two-sha256-characters}/{sha256}.json
```

Destinations receive only publication data: timeline objects, catalog rows,
destination-specific immutable indices, and mutable pointers. Each profile
revision has a route per `(publishMode, environment)`. A route binds one or
more object destinations and catalog destinations; every catalog binding names
the object binding whose timeline URL it stores.

The primary object destination preserves the compatibility URL returned by the
composite API. Required destination failure fails the operation. Optional
failure produces `succeededWithWarnings`. All required indices must exist
before any pointer is updated, and the primary pointer is written last.

## Connections and databases

Physical endpoints and credentials are outside the control database. Configure
the registry selected by `CODEX_CLI_PUBLISH_CONNECTIONS_FILE` (default
`.home-deploy/publish-connections.json`). The supported connection kinds are:

- `s3_compatible_object` for local MinIO or a remote object service;
- `sql_catalog` for PostgreSQL, including local `codex_public_catalog`;
- `http_catalog` for a remote catalog compatibility endpoint.

Copy `scripts/local-home/publish-connections.example.json` to the private
registry path and replace every placeholder locally. Keep `archive-artifacts`
and `archive-publication-staging` private; expose only the intended
`archive-public` read path.

The control plane remains in `codex`. The local public catalog uses its own
SQLAlchemy metadata and Alembic tree and must point to a database named
`codex_public_catalog`:

```powershell
uv run python -m alembic upgrade head
.\scripts\local-home\migrate-public-catalog.ps1
```

The API returns connection references and safe targets, never DSNs, tokens, or
access keys:

```text
GET /ops/publish/connections
```

Legacy R2/D1-named settings are read only by
`publication connections import-legacy`. The active runtime fails closed when
the generic connection registry is absent.

## Profiles and channels

Create object/catalog destinations, create a profile, add a draft revision
with routes and bindings, then activate it. Active revisions are immutable;
configuration changes require another draft revision. Mutating endpoints
require an `X-Operator-Reason` header and emit an operation event.

```text
GET|POST /ops/publish/object-destinations
GET|POST /ops/publish/catalog-destinations
GET|POST /ops/publish/profiles
GET      /ops/publish/profiles/{profileId}
POST     /ops/publish/profiles/{profileId}/revisions
POST     /ops/publish/profiles/{profileId}/revisions/{revisionId}/activate
```

Every new streamer must explicitly provide `publishProfileId`. A streamer that
already has archive artifacts cannot change profiles through the ordinary
streamer update endpoint.

## Composite and recovery APIs

The existing composite operation resolves the streamer's active revision and
stores the route snapshot in the work input. It runs canonical build, object
delivery, catalog publication, index build, and pointer publication inline.
Process-to-publish and explicit timeline-patch publication continue to use this
same flow.

Recovery can run each stage independently:

```text
POST /ops/operations/archive-artifact-build
POST /ops/operations/archive-object-deliver
POST /ops/operations/archive-catalog-publish
POST /ops/operations/archive-publication-build
POST /ops/operations/archive-pointer-publish
```

Stages after artifact build accept `artifactIds`, `profileRevisionId`,
`publishMode`, `environment`, and optional `destinationIds`; publication build
also accepts `schemaVersion`. Pointer publication accepts `publicationId` and
optional destinations. The server rejects artifacts belonging to another
profile. Cutover is the only internal flow authorized to prepare the moving
streamer's snapshotted membership on the target profile.

If a predecessor checkpoint is missing, the API returns HTTP 409 with
`missingPreconditions` and does not run it implicitly. Succeeded deliveries are
reused; pending or failed deliveries change only when that stage is explicitly
retried. A failed pointer can therefore be retried without rebuilding its
artifact or index. `running` and pre-index `building` checkpoints hold a
15-minute lease: concurrent retries are rejected while the lease is active, and
an explicit stage retry reclaims an expired lease after a stopped process.

Inspect durable state with:

```text
GET /ops/publish/publications?streamerId=...&profileId=...&publishMode=prod&environment=prod
```

The streamer's filter is based on publication membership, not its current
profile assignment.

## Profile cutover

For a streamer with published data, prepare and resume a durable cutover:

```text
POST /ops/publish/cutovers
POST /ops/publish/cutovers/{cutoverId}/resume
GET  /ops/publish/cutovers
GET  /ops/publish/cutovers/{cutoverId}
```

Preparation builds target objects, catalog rows, and indices without moving a
pointer. Resume applies the ordered sequence `target pointer -> streamer DB
assignment -> source index rebuild -> source pointer`. Every completed step and
failure is stored so the same API can resume safely; no background cutover
worker is registered.

## Object and catalog contract

Published timeline JSON contains public video, streamer, and channel metadata;
timeline summary; blocks, episodes, and micro-events; topic clusters; and
playback anchors. It excludes transcript text, raw model responses, internal
candidate IDs, work IDs, diagnostics, and secrets.

Each SQL catalog video upsert and replacement of its block, episode,
micro-event, and topic-cluster children occurs in one target-database
transaction. The catalog key scope is `(profile_key, publish_mode,
environment, video_id, variant)`. A source-profile cutover reconciles that SQL
scope against the rebuilt membership snapshot, removing rows and child
projections for streamers that moved out of the profile.

For offline legacy migration and its inventory guarantees, see
[Publication data migration](PUBLICATION_MIGRATION.md).
