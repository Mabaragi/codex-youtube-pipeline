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

Status: active.
