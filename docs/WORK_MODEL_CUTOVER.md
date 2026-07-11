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
`PRAGMA foreign_key_check`. 기존 DB에 이미 존재하는 FK 위반은 row와 constraint
기준으로 candidate와 정확히 같아야 하며, 새 위반이나 migration 중의 암묵적 데이터
수정은 실패로 처리한다. 기존 위반 건수는 검증 결과에 별도로 출력한다.

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

## Contract-Phase Removal Criteria

The expand migration deliberately retains legacy execution tables while
compatibility processors remain. A later contract revision may remove them only
when all of these are true:

- micro-event, timeline, archive, and channel processors persist directly by
  `work_item_id` / `work_attempt_id`;
- no runtime composition imports legacy task/job repositories;
- all provenance columns are non-null for newly generated output;
- a production backup rehearsal proves row and object-key preservation;
- public OpenAPI and Ops UI contain no legacy mutation or lookup dependency.

Until then, `work_items` is the public operational source of truth and legacy
rows are compatibility provenance, not an operator contract.
