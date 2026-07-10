# Docs Index

Public-safe human-facing documentation lives here. Agent workflow routing is in
`vaults/INDEX.md`; the two API operation references below remain public-safe so
operators can use them without private runtime context.

- [Project overview](PROJECT_OVERVIEW.md): project structure, representative
  CLI/FastAPI behavior, configuration, and verification. Read when orienting to
  the backend or documenting a cross-cutting change.
- [Agent API operations](AGENT_API_OPERATIONS.md): public-safe endpoint catalog
  for local pipeline operations. Read when an API-only task needs endpoint,
  status, or payload guidance.
- [Agent work runbooks](AGENT_WORK_RUNBOOKS.md): public-safe step-by-step
  pipeline, retry, publish, and artifact-verification procedures. Read when
  carrying out an operational request rather than changing implementation.
- [YouTube data pipeline](YOUTUBE_DATA_PIPELINE.md): channel, video,
  transcript, cue, micro-event, timeline, scheduler, and retry behavior. Read
  when changing pipeline state, task ownership, or execution orchestration.
- [YouTube data pipeline backlog](YOUTUBE_DATA_PIPELINE_TODO.md): implemented
  milestones and remaining domain work. Read when scoping the next pipeline
  capability.
- [Local native deployment](LOCAL_NATIVE_DEPLOYMENT.md): Home PC setup, local
  process topology, scheduler prerequisites, MinIO, and R2 publishing. Read
  when deploying, starting, or recovering the local runtime.
- [Home PC deployment entrypoint](HOME_PC_DEPLOYMENT.md): short route to the
  current local-native deployment flow. Read when a legacy Docker deployment
  reference needs redirecting.
- [Architecture linting](ARCHITECTURE_LINTING.md): Import Linter layer rules
  and repair guidance. Read when imports or domain boundaries change.
- [Archive publish](ARCHIVE_PUBLISH.md): archive API, object layout, cache
  policy, and required environment variables. Read when publishing or
  validating public timeline artifacts.
- [CI/CD status](CICD.md): current manual GitHub Actions behavior and local
  quality gates. Read when changing verification or deployment automation.
- [Ops UI documentation index](../ops-ui/docs/INDEX.md): Next.js architecture,
  BFF, generated contract, and visual rules. Read before changing `ops-ui/`.
