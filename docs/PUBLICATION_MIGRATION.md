# Publication Data Migration

This runbook moves legacy archive history into the streamer-scoped publication
model. It preserves every existing remote object and pointer: the migration only
reads the legacy primary destination, writes canonical/local copies, and records
checkpoints in the control database.

## Safety boundary

Before `apply`, drain and stop the runtime, back up the `codex` PostgreSQL
database, and export the remote object listing as JSON. The listing may be an
array of keys or an object with an `objects` array whose entries contain `key`.
`apply`, `resume`, and `verify` require this manifest. The CLI reports remote
timeline objects that have no control-DB row without importing them. Index and
pointer objects without a control-DB row are reported and preserved byte-for-byte
in private staging. No source object is modified or deleted.

Secrets and physical endpoints belong only in
`.home-deploy/publish-connections.json`, selected with
`CODEX_CLI_PUBLISH_CONNECTIONS_FILE`. Run the one-time legacy settings importer
to preview and then merge the old remote object/catalog values:

```powershell
uv run codex-demo publication connections import-legacy
uv run codex-demo publication connections import-legacy --apply
```

The importer never replaces an existing connection. Configure the generic local
entries separately: `local-artifact-store` targets the private
`archive-artifacts` bucket, `local-publication-staging` targets private staging,
`local-public-object` targets `archive-public`, and `local-public-catalog` uses
the `codex_public_catalog` PostgreSQL database. When legacy development publish
settings are configured, the importer also creates `legacy-dev-remote-object`;
the seeded `dev/dev` route requires that separate connection so development
objects never fall back to the production bucket.

## Database preparation

Upgrade the control database first, then create and migrate the independent
public catalog database:

```powershell
uv run python -m alembic upgrade head
.\scripts\local-home\migrate-public-catalog.ps1
```

The helper rejects a PostgreSQL catalog URL whose database name is not
`codex_public_catalog`. Normal `deploy.ps1` invokes it unless
`-SkipPublicCatalogMigration` is explicitly supplied.

## Rehearsal and execution

`dry-run` and `verify` perform reads and write only a private JSON report under
`.home-deploy/migration-reports/`. They do not modify the control DB, object
stores, pointer, or catalog. `apply` and `resume` use the same idempotent
checkpoints; succeeded immutable objects and catalog rows are verified/reused.

```powershell
uv run codex-demo publication migrate `
  --mode dry-run `
  --source-manifest .home-deploy/manifests/legacy-objects.json

uv run codex-demo publication migrate `
  --mode apply `
  --source-manifest .home-deploy/manifests/legacy-objects.json

uv run codex-demo publication migrate --mode resume `
  --source-manifest .home-deploy/manifests/legacy-objects.json
uv run codex-demo publication migrate --mode verify `
  --source-manifest .home-deploy/manifests/legacy-objects.json
```

The production defaults enforce the agreed inventory: 802 total artifacts, 450
ready, 352 `legacy_source_missing`, zero SHA/size mismatches, and 179
publish-eligible artifacts in the latest local publication. The source snapshot
has 180 unique video/variant pairs, but one is currently non-embeddable and is
intentionally excluded to preserve the existing publication selection rule.
The verified source manifest contains 876 objects: 459 timelines, 416 indices,
and one pointer. Of the timelines, 450 match control-DB artifacts and nine are
manifest-only objects that are reported but not imported. Of the indices, 407
match control-DB history and nine are manifest-only; all 416 are preserved
byte-for-byte in private staging. A further 395 control-DB index records have no
source object. They remain `unavailable/legacy_source_missing` and do not make
the source manifest incomplete. Completion means preserving every index that
actually exists in the source manifest, not reconstructing absent source
history.

Rehearsal fixtures can override the five `--expected-*-count` options,
including `--expected-history-count`.

For every available artifact, the command verifies the legacy bytes before
copying them to the content-addressed canonical key
`artifacts/sha256/{first-two}/{sha256}.json`. Missing source objects are retained
as `unavailable` only when the source explicitly reports that the key is absent.
Authentication, network, and read failures stop the migration instead of being
misclassified as missing. Artifacts are never regenerated. Legacy index bytes
and the current pointer bytes are preserved byte-for-byte in private staging. Historical
local indices are generated only when every referenced artifact is available.
Only the latest local pointer is updated; the legacy primary pointer is never
written by this migration.

The latest local catalog is replayed transactionally. Existing remote catalog
state is checkpointed for every ready legacy artifact (450 by default), while
only the latest 179 are replayed locally. Remote success is imported from its
recorded control-DB timestamp and the remote HTTP endpoint is not called.

## Completion checks

Treat the run as complete only when the report has `ok: true`, no blockers, no
artifact/index mismatch, all legacy indices preserved, 179 latest artifacts,
and 179 successful local catalog deliveries. Run `verify` after `apply` or
`resume`, then activate the new runtime and resume processing. If verification
fails, leave remote storage untouched and restore the control DB backup before
retrying.
