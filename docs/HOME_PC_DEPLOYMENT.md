# Home PC Deployment Guide

The current Home PC deployment is local native.

Use:

- `docs/LOCAL_NATIVE_DEPLOYMENT.md` for starting, stopping, deploying, and
  recovering the local runtime.
- `docs/AGENT_API_OPERATIONS.md` for API-only operational work by agents that
  should not inspect the codebase.

The previous Docker Compose + Nginx + ngrok + GHCR deployment path is legacy.
It is no longer the normal operating model because ngrok usage limits and image
publish/pull cycles made it slow and brittle for this project.

Current runtime summary:

```text
MinIO: Docker only, 127.0.0.1:9000 and 127.0.0.1:9001
FastAPI: Windows process, 127.0.0.1:8000
Workers: Windows processes
Ops UI: Windows process, 127.0.0.1:3000
SQLite: ./data/app.db
Runtime files: ./.home-deploy/
```

Quick commands:

```powershell
.\scripts\local-home\deploy.ps1
.\scripts\local-home\status.ps1
.\scripts\local-home\start.ps1 -NoBuild
.\scripts\local-home\stop.ps1
```
