# Docs Index

Human-facing project and operations docs live here. Agent-facing process rules
remain in root `AGENTS.md` and `vaults/`.

- `docs/PROJECT_OVERVIEW.md`: project structure, CLI/FastAPI behavior, and
  common verification commands.
- `docs/YOUTUBE_DATA_PIPELINE.md`: YouTube channel, video, transcript, cue,
  micro-event, and timeline pipeline behavior.
- `docs/YOUTUBE_DATA_PIPELINE_TODO.md`: remaining pipeline backlog.
- `docs/LOCAL_NATIVE_DEPLOYMENT.md`: current Home PC deployment path. MinIO runs
  in Docker; API, workers, and Ops UI run as local Windows processes.
- `docs/AGENT_API_OPERATIONS.md`: API-only operations index. Agents should read
  it first, then load only the matching guide under `docs/agent-api-operations/`.
- `docs/ARCHITECTURE_LINTING.md`: Import Linter clean architecture gate,
  layer rules, and violation repair guidance.
- `docs/ARCHIVE_PUBLISH.md`: R2 archive publish API, worker, object layout,
  cache policy, and required environment variables.
- `docs/CICD.md`: current GitHub Actions status. Workflows are manual checks
  only and are not the normal deployment path.
- `docs/HOME_PC_DEPLOYMENT.md`: short entrypoint that routes to the current
  local native deployment guide.
- `legacy/docs/HOME_DEPLOYMENT_FLOW.md`: legacy GHCR/ngrok Home PC deployment flow,
  retained for reference only.
- `legacy/docs/AWS_DEPLOYMENT.md`: old Terraform/EC2/SSM deployment notes, not the
  current target.
- `ops-ui/docs/FRONTEND_ARCHITECTURE.md`: Next.js Ops UI structure, BFF, state,
  and screen organization.
- `ops-ui/docs/API_CONTRACT.md`: OpenAPI export and generated frontend type
  update workflow.
