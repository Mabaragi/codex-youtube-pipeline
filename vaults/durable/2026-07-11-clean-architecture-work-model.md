# Clean Architecture Work-Model Boundary

Problem: a broad refactor can expose a new API while old task/job models remain
reachable through application code, creating two operational sources of truth.

Rule: `application` owns commands, queries, workflows, and work ports and must
not import legacy `video_tasks` or `pipeline_jobs`. Temporary bridges belong
only in `infra/work` and are assembled in bootstrap.

Rule: do not drop legacy tables merely to make the package tree look complete.
First make result persistence work-item native, validate all provenance, rehearse
against a copied DB, and keep an atomic rollback backup.

Enforcement: Import Linter contract, OpenAPI test excluding old mutation paths,
architecture size/complexity gates, and `docs/WORK_MODEL_CUTOVER.md`.

Runtime rules discovered during cutover:

- Register the complete SQLAlchemy model registry in the engine factory. Do not
  rely on worker-module import side effects to resolve string foreign keys.
- Keep `httpx` and `httpcore` below INFO in long-running workers when request
  URLs can contain credentials.
- Reuse exact stored transcript metadata across task-version changes, and do
  not apply the upstream cooldown when no network fetch occurred.

Status: active.
