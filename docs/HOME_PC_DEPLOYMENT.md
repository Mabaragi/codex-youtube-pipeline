# Home PC Deployment Guide

The current Home PC deployment is local native.

Use:

- [docs/LOCAL_NATIVE_DEPLOYMENT.md](LOCAL_NATIVE_DEPLOYMENT.md) for starting,
  stopping, deploying, and recovering the local runtime.

The previous Docker Compose + Nginx + ngrok + GHCR deployment path is not part
of this public repository. The normal operating model is local native runtime.

Current runtime summary:

```text
PostgreSQL: Docker only, 127.0.0.1:5432, persistent named volume
MinIO: Docker only, 127.0.0.1:9000 and 127.0.0.1:9001
FastAPI: Windows process, 127.0.0.1:8000
Workers: Windows processes
Ops UI: Windows process, 127.0.0.1:3000
SQLite: retained only as the pre-PostgreSQL source/backup
Runtime files: ./.home-deploy/
```

Quick commands:

```powershell
.\scripts\local-home\deploy.ps1
.\scripts\local-home\status.ps1
.\scripts\local-home\start.ps1 -NoBuild
.\scripts\local-home\stop.ps1
```
