# CI/CD Status

This repository no longer uses GitHub-driven CI/CD for normal operation.

The Home PC runtime is local native. See `docs/LOCAL_NATIVE_DEPLOYMENT.md`.

## Current GitHub Actions Behavior

- `.github/workflows/ci.yml` is manual-only through `workflow_dispatch`.
- Pushes to `main` do not deploy the Home PC.
- Pushes to `main` do not build or publish GHCR images.
- Tag pushes do not publish release images automatically.
- No workflow starts ngrok, Nginx, or the Windows self-hosted runner deploy path.

## Normal Verification

Run checks locally:

```powershell
uv run pytest
uv run ruff check .
uv run pyrefly check --min-severity warn
uv run python scripts/export_openapi.py --check
pnpm --filter codex-sdk-ops-ui api:check
pnpm --filter codex-sdk-ops-ui lint
pnpm --filter codex-sdk-ops-ui typecheck
pnpm --filter codex-sdk-ops-ui test
pnpm --filter codex-sdk-ops-ui build
```

Run local deploy locally:

```powershell
.\scripts\local-home\deploy.ps1
```

## Manual Workflows

Use GitHub Actions only when explicitly wanted:

- `Manual Checks`: remote quality and frontend checks.

These workflows are not part of the normal deployment loop.
