# Architecture Linting

This project uses `import-linter` as the static gate for Python clean
architecture boundaries.

## Command

Run the official gate from the repository root:

```powershell
uv run lint-imports
```

If local Home PC worker processes are running and Windows keeps executable files
locked during `uv` sync, stop the local runtime first:

```powershell
.\scripts\local-home\stop.ps1
uv run lint-imports
```

`uv run --no-sync lint-imports --config pyproject.toml` is acceptable only as a
local diagnostic when the environment is already synced.

## Layers

The enforced import direction is:

```text
api | workers -> infra -> domains
```

- `domains`: inner application/domain layer. Contains schemas, ports,
  use cases, exceptions, constants, and pure helpers.
- `infra`: concrete adapters for persistence, object storage, external APIs,
  and SDK clients.
- `api`: FastAPI routers, exception mapping, dependency wiring, and concrete
  use case assembly.
- `workers`: long-running process entrypoints that call domain use cases through
  infra wiring.

## Domain Rules

Domain code must not import:

- `codex_sdk_cli.api`
- `codex_sdk_cli.infra`
- `codex_sdk_cli.workers`
- `codex_sdk_cli.settings`
- external adapter frameworks such as `fastapi`, `sqlalchemy`, `httpx`,
  `minio`, `uvicorn`, `youtube_transcript_api`, or `openai_codex`

Pydantic request/response DTOs stay in `domains/<domain>/schemas.py` because
they are part of the public contract in this codebase. FastAPI route handlers
and dependency providers live in `api/routes` and `api/use_case_dependencies`.

## Fixing Violations

Prefer moving code to the owning layer instead of adding ignores.

- FastAPI `APIRouter`, `Depends`, status codes, and dependency aliases belong in
  `api`.
- SQLAlchemy metadata inspection and query construction belong in `infra`.
- Domain use cases should depend on `Protocol` ports and small domain records.
- Settings should be translated into explicit domain input/default records in
  the API or worker wiring layer.
- Worker entrypoints may assemble concrete infra, but infra must not import
  workers or API modules.

When a contract fails, read the import chain in `lint-imports` output and move
the outer dependency outward until imports point only inward.
