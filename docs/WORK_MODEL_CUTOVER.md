# Work Model Cutover

The work-model migration is an offline SQLite candidate migration. Never run
Alembic directly against the only production DB for this transition.

## What Is Preserved

- Channel, video, transcript, cue, micro-event, timeline, artifact, usage,
  event, and external API-call primary keys.
- Transcript and archive object keys and public URLs.
- Historical task/job/attempt identity through `legacy_work_refs`.
- Existing MinIO and R2 objects; no object is moved.
- `no_transcript` as `work_items.status=succeeded` with
  `outcome_code=no_transcript`.

## Rehearsal

Stop-changing runtime state, checkpoint the WAL, copy the DB, migrate only the
copy, and validate it:

```powershell
.\scripts\local-home\cutover-work-model.ps1 -Rehearsal -NoRestart
```

The command leaves both a timestamped backup and candidate DB. Validation
checks preserved PK sets, storage object names, artifact URLs, work/attempt
mapping counts, provenance coverage, `PRAGMA integrity_check`, and
`PRAGMA foreign_key_check`.

If the source DB already has foreign-key violations, the candidate must retain
the exact same rows, constraints, and child values. A new violation, a removed
violation, or an implicit value change fails validation. The report prints the
pre-existing violation count separately so legacy debt stays visible.

Inspect the printed report and retain the candidate until the API and worker
smoke tests pass against it.

## Cutover

After a successful rehearsal and full quality gates:

```powershell
.\scripts\local-home\cutover-work-model.ps1
```

The script:

1. stops API, UI, scheduler, workers, and coordinator;
2. checkpoints SQLite WAL;
3. creates backup and candidate copies;
4. runs `alembic upgrade head` against the candidate;
5. validates source versus candidate;
6. atomically replaces the DB file;
7. starts the local runtime.

Use `-NoRestart` when a manual smoke sequence should run before start.

## Rollback

1. Stop the local runtime.
2. Preserve the failed DB for diagnosis.
3. Replace `data/app.db` with the printed `pre-work-cutover` backup.
4. Start the previous compatible checkout.

Do not delete the backup until at least one complete pipeline and archive
publish have succeeded after cutover.

## Contract Phase

Revision `20260711_0028` completes the execution-table contract:

- historical job/attempt references are translated with `legacy_work_refs`;
- provenance foreign keys now target `work_items` / `work_attempts`;
- micro-event, timeline, archive, channel, and video collection execute the
  already-claimed work item and attempt;
- startup recovery updates unified work rows only;
- physical `video_tasks`, `pipeline_jobs`, and `pipeline_job_attempts` tables
  are dropped.

The three historical names are recreated as read-only compatibility views so
existing Ops query projections can read migrated history. Never write to these
views. `work_items` and `work_attempts` are the only execution source of truth.

This contract revision is intentionally irreversible through Alembic downgrade.
Rollback uses the timestamped pre-cutover database backup because reconstructing
the old dual-write model would risk losing attempt identity and provenance.

Before applying the contract to the active DB, all of these must pass:

```powershell
uv run pytest
uv run ruff check src tests alembic
uv run pyrefly check --min-severity warn
uv run lint-imports
uv run python scripts/check_architecture.py
.\scripts\local-home\cutover-work-model.ps1 -Rehearsal
```
