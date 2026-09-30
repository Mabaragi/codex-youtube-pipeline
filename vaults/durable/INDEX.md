# Durable Improvements

Record the smallest public-safe rule when the same process gap appears more
than once. Promote the rule to a narrower source of truth when appropriate.

## Entries

- [Independent Windows Terminal for operation](2026-09-30-independent-runtime-terminal.md):
  start the runtime in a visible terminal, verify its parent chain, and preserve
  drain-based lifecycle commands.
- [Clean architecture work-model boundary](2026-07-11-clean-architecture-work-model.md):
  keep application independent from legacy execution models, then complete the
  contract migration after native persistence and rehearsal criteria pass.
- [PostgreSQL for concurrent workers](2026-07-12-postgres-worker-concurrency.md):
  use row-level locking and `SKIP LOCKED` for multi-slot production workers;
  retain SQLite only for isolated tests and migration backups.
- [Drain before local runtime shutdown](2026-07-14-safe-local-runtime-shutdown.md):
  block new enqueue and claim work, wait for `readyToStop`, and never turn a
  timeout or forced stop into an implicit resume.
- [Confirm product taxonomy before encoding it](2026-09-30-confirm-product-taxonomy.md):
  present generic categories as candidates with data evidence, and put only
  user-confirmed categories and boundary decisions into prompts, enums, and UI.
- [Streamer-scoped publication routing](../../docs/ARCHIVE_PUBLISH.md): keep the
  canonical artifact in private local storage, route only publication outputs,
  and model object/catalog destinations with vendor-neutral connection refs.
