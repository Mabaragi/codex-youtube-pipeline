# Legacy Home Deployment Flow

This document is retained for historical reference. The current Home PC runtime
is local native and does not use GHCR image pulls, Nginx, ngrok, or GitHub
Actions deploy jobs. Use `docs/LOCAL_NATIVE_DEPLOYMENT.md` instead.

---

This document records the current Home PC deployment flow and the concrete
change from local Docker builds to GHCR image pulls.

## What Changed

Before the optimization, a `main` push used two separate image paths:

| Area | Previous behavior | Current behavior |
| --- | --- | --- |
| Main CI image publish | `Docker Publish` workflow also ran on `main` and pushed the API image. | `CI` workflow owns deploy images for `main`; `Docker Publish` is tag-only. |
| API image | Home PC rebuilt `codex-sdk-cli:home` from the checkout. | CI publishes `ghcr.io/mabaragi/codex-sdk:sha-<short-sha>` and Home PC pulls it. |
| Ops UI image | Home PC rebuilt `codex-sdk-ops-ui:home` from the checkout. | CI publishes `ghcr.io/mabaragi/codex-sdk-ops-ui:sha-<short-sha>` and Home PC pulls it. |
| Home deploy command | `docker compose build api ops-ui`, then `up -d --build --force-recreate ...`. | `docker compose pull api micro-event-worker timeline-compose-worker codex ops-ui`, then `up -d --no-build --remove-orphans ...`. |
| Recreate policy | Every deploy forced service recreation. | Compose updates services whose image/config changed; infra containers are not forced. |
| Local fallback | Normal deploy and local rebuild used the same compose file. | `compose.home.yaml` is image-based; `compose.home.build.yaml` is the explicit local-build fallback. |

The goal is to keep the quality gates while removing the slow Home PC Docker
build from the deployment path.

## Main Push Flow

`main` push now runs only the `CI` workflow:

1. `quality` runs backend tests, Ruff, Pyrefly, FastAPI import, and OpenAPI export check.
2. `frontend` runs OpenAPI client check, ops-ui lint/typecheck/test/build.
3. `publish_images` builds and pushes immutable SHA images:
   - `ghcr.io/mabaragi/codex-sdk:sha-<short-sha>`
   - `ghcr.io/mabaragi/codex-sdk-ops-ui:sha-<short-sha>`
4. `home_deploy_preflight` checks required Home PC secrets and variables.
5. `home_deploy` runs on the Windows self-hosted runner labeled `codex-home`.
6. `public_tunnel_health` verifies the ngrok URL from a GitHub-hosted runner.

`Docker Publish` no longer runs on `main`. It only runs for release tags
matching `v*.*.*` and publishes release/version image tags.

## Home PC Deploy Steps

The Home PC runner receives the exact image tags from `publish_images` outputs:

- `CODEX_API_IMAGE`
- `CODEX_OPS_UI_IMAGE`

The deploy job then runs:

```powershell
docker compose --project-name codex-sdk-home -f compose.home.yaml pull api micro-event-worker timeline-compose-worker codex ops-ui
docker compose --project-name codex-sdk-home -f compose.home.yaml run --rm --no-deps --entrypoint alembic api upgrade head
docker compose --project-name codex-sdk-home -f compose.home.yaml up -d --no-build --remove-orphans api micro-event-worker timeline-compose-worker ops-ui nginx ngrok minio
docker compose --project-name codex-sdk-home -f compose.home.yaml restart nginx
docker compose --project-name codex-sdk-home -f compose.home.yaml ps
```

Important details:

- `api` and `codex` use the same API image through `CODEX_API_IMAGE`.
- `ops-ui` uses `CODEX_OPS_UI_IMAGE`.
- Alembic runs from the pulled API image before the stack is updated.
- Nginx, ngrok, MinIO, the SQLite `db-data` volume, MinIO data, and Codex login
  volume remain part of the same Home stack.
- The deploy restarts only `nginx` after `up -d`. This keeps the GHCR pull path
  fast while forcing Nginx to refresh Docker DNS after `api` or `ops-ui`
  containers are recreated with new IPs.
- The job still validates local `/health`, `/ops`, and
  `/ops/api/backend/ops/summary` through Nginx Basic Auth.

## Compose Files

`compose.home.yaml` is the normal deployment compose file. It should not contain
build instructions for deployable app services:

```yaml
api:
  image: ${CODEX_API_IMAGE:-codex-sdk-cli:home}

codex:
  image: ${CODEX_API_IMAGE:-codex-sdk-cli:home}

ops-ui:
  image: ${CODEX_OPS_UI_IMAGE:-codex-sdk-ops-ui:home}
```

`compose.home.build.yaml` is the manual fallback for building on the Home PC:

```powershell
docker compose --project-name codex-sdk-home -f compose.home.yaml -f compose.home.build.yaml build api ops-ui
docker compose --project-name codex-sdk-home -f compose.home.yaml -f compose.home.build.yaml run --rm --no-deps --entrypoint alembic api upgrade head
docker compose --project-name codex-sdk-home -f compose.home.yaml -f compose.home.build.yaml up -d --no-build --remove-orphans api micro-event-worker timeline-compose-worker ops-ui nginx ngrok minio
```

Use this fallback only when GHCR pull is unavailable or when intentionally
testing local images on the Home PC.

## Caching

The deployment speedup is paired with cache-friendly builds:

- GitHub Actions caches uv and pnpm dependency stores.
- Docker Buildx uses GitHub Actions cache scopes:
  - API image: `type=gha,scope=api`
  - Ops UI image: `type=gha,scope=ops-ui`
- The API Dockerfile separates third-party dependency install from app wheel
  install, so app-only changes do not invalidate the dependency layer.
- The ops-ui Dockerfile uses BuildKit cache mounts for pnpm store and Next.js
  build cache.

The first run after this change can still be slower while cache is populated.
Later runs should benefit from BuildKit and dependency cache reuse.

## Performance Metrics

Use the Home PC deploy job as the primary speed metric because the optimization
intentionally moved Docker build work away from the self-hosted runner and into
the CI image publish job.

| Metric | Previous local-build deploy | GHCR pull deploy | Change |
| --- | --- | --- | --- |
| Workflow run | `27781197166` | `27795139217` | - |
| Commit | `8485b6c` | `d4a8243` | - |
| Job | `Deploy API to home PC` | `Deploy API to home PC` | - |
| Job id | `82206422746` | `82253576133` | - |
| Job time | `179s` | `62s` | `117s` faster |
| Relative change | - | - | about `65%` less time, about `2.9x` faster |

The old deploy job log showed:

```powershell
docker compose --project-name codex-sdk-home -f compose.home.yaml build api ops-ui
docker compose --project-name codex-sdk-home -f compose.home.yaml up -d --build --force-recreate --remove-orphans api micro-event-worker timeline-compose-worker ops-ui nginx ngrok minio
```

The GHCR pull deploy job log showed:

```powershell
docker compose --project-name codex-sdk-home -f compose.home.yaml pull api micro-event-worker timeline-compose-worker codex ops-ui
docker compose --project-name codex-sdk-home -f compose.home.yaml up -d --no-build --remove-orphans api micro-event-worker timeline-compose-worker ops-ui nginx ngrok minio
```

The first verified GHCR run was not faster by total workflow wall time:

| Metric | Previous run | GHCR pull run |
| --- | --- | --- |
| Run created/updated window | about `284s` | about `306s` |

That total is expected to be a different metric, not a direct deploy-speed
regression: the build work moved from the Home PC deploy job into
`Publish deploy images`, and the first run also populated BuildKit/GitHub
Actions caches.

Future runs can be faster when:

- Docker Buildx cache is warm for API and ops-ui image builds.
- uv, pnpm, and Next.js caches are warm.
- The Home PC already has unchanged base/dependency layers and only pulls
  changed app layers.
- The commit does not touch Dockerfiles, lockfiles, or dependency-heavy layers.

It is not guaranteed to get faster on every run. Dependency changes, Dockerfile
changes, cache eviction, large image layer changes, or a cold Home PC Docker
cache can make a specific run slower. The durable win is that the Home PC deploy
job no longer rebuilds images and is now mostly pull, migration, container
update, and health checks.

## Verification

For a successful deploy, confirm:

- `CI` run succeeds.
- No `Docker Publish` run is created for a normal `main` push.
- `Publish deploy images` publishes both SHA images.
- Home deploy logs show `docker compose pull api micro-event-worker timeline-compose-worker codex ops-ui`.
- Home deploy logs do not show `docker compose build api ops-ui`.
- Home deploy logs show `up -d --no-build --remove-orphans`.
- Home deploy logs show `restart nginx` before the local Nginx health check.
- `Verify public ngrok health` succeeds.
- `https://mutation-runny-smelting.ngrok-free.dev` reaches Nginx and requires
  Basic Auth for protected endpoints.

The first verified run after the change was:

- Commit: `d4a8243`
- CI run: `https://github.com/Mabaragi/codex-sdk/actions/runs/27795139217`
- Home deploy job time: `62s`, down from the canonical previous local-build
  comparison of `179s`. An earlier rough observation was `137s`, but the
  Actions API job comparison above is the reference metric.
