# Architecture Linting

The repository has two static clean-architecture gates.

## Commands

```powershell
uv run lint-imports --no-cache
uv run python scripts/check_architecture.py
uv run ruff check .
```

Import Linter enforces six contracts:

1. `api | workers -> bootstrap -> infra -> application -> domains`.
2. Domains cannot import outer app layers.
3. Domains cannot import adapter frameworks such as FastAPI, SQLAlchemy,
   HTTPX, MinIO, Uvicorn, YouTube Transcript API, or Codex SDK.
4. Application cannot import outer layers, settings, or adapter frameworks.
5. Infrastructure cannot import API, bootstrap, or workers.
6. Application cannot import legacy `video_tasks` or `pipeline_jobs` models.

The size gate limits new entry/application modules to 700 lines and functions
to 120 lines. Other production modules are capped at 2,000 and 300 lines. Ruff
enforces `C901` with maximum complexity 10 across the repository.

## Repair Rules

- Move FastAPI routing and dependency aliases to `api`.
- Put commands, queries, workflows, and Protocol ports in `application`.
- Put SQLAlchemy queries and external clients in `infra`.
- Convert settings to focused config in `bootstrap`.
- Split orchestration, parsing, normalization, repair, and persistence instead
  of adding an ignore.
- Keep executor registry entries lazy; do not eagerly build every external
  dependency for one selected task type.

Compatibility adapters are allowed only in `infra/work` and bootstrap. They do
not justify a new dependency from application back to legacy task/job domains.
