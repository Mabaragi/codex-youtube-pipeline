# API And Domain Agent Guide

## Read Order

1. `docs/CLEAN_ARCHITECTURE.md`.
2. Relevant `domains/<area>` policy/models.
3. Relevant `application/<area>` command/query/workflow.
4. Owning infra adapter and tests.
5. API schema, route, and bootstrap wiring only when the HTTP contract changes.

## Ownership

- Put FastAPI DTOs and route aliases in `api/schemas` and `api/routes`.
- Put dependency providers in `api/use_case_dependencies`; keep them thin.
- Put commands/results/ports in `application`.
- Put pure models and validation policy in `domains`.
- Put SQLAlchemy and external SDK code in `infra`.
- Build concrete object graphs only in `bootstrap`.

Repositories used by the new work core do not commit. The Unit of Work owns the
transaction. Executor registries hold lazy factories so unrelated external
storage or clients are not resolved for the selected task.

Do not add a new `/video-tasks/*` or `/pipeline/jobs/*` endpoint. Commands belong
under `/ops/operations`, execution reads under `/ops/work-items`, and end-to-end
orchestration under `/ops/workflows`.

## Required Gates

```powershell
uv run ruff check .
uv run pyrefly check --min-severity warn
uv run lint-imports --no-cache
uv run python scripts/check_architecture.py
uv run python scripts/export_openapi.py --check
```
