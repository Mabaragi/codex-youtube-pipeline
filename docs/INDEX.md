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
  process topology, the control/public-catalog PostgreSQL databases, MinIO, and
  publication connection registry. Read
  when deploying, starting, or recovering the local runtime.
- [Codex SDK runtime compatibility](CODEX_RUNTIME_COMPATIBILITY.md): bundled CLI
  selection, the external-CLI model-availability escape hatch, version/cache
  failure signatures, and the supported upgrade procedure. Read before changing
  `openai-codex` or `CODEX_CLI_CODEX_BIN`.
- [PostgreSQL local database](POSTGRESQL_LOCAL_DATABASE.md): worker concurrency,
  SQLite migration, persistence, backup, and recovery. Read when changing the
  database or diagnosing claim/heartbeat contention.
- [Home PC deployment entrypoint](HOME_PC_DEPLOYMENT.md): short route to the
  current local-native deployment flow. Read when a legacy Docker deployment
  reference needs redirecting.
- [Architecture linting](ARCHITECTURE_LINTING.md): Import Linter layer rules
  and repair guidance. Read when imports or domain boundaries change.
- [Clean architecture](CLEAN_ARCHITECTURE.md): enforced package boundaries,
  Unit of Work ownership, unified execution model, and compatibility boundary.
- [Work model cutover](WORK_MODEL_CUTOVER.md): historical offline SQLite rehearsal,
  validation, atomic replacement, rollback, and contract-removal criteria.
- [Archive publish](ARCHIVE_PUBLISH.md): streamer profiles, canonical local
  artifacts, multi-destination routes, recovery stages, status, and cutover.
  Read when publishing or validating timeline projections.
- [Publication data migration](PUBLICATION_MIGRATION.md): offline preparation,
  canonical/local copy, historical index preservation, catalog replay, resume,
  and verification. Read before migrating existing archive data.
- [One-shot model evaluation](MODEL_EVALUATION.md): private evaluation database and
  object storage preparation, plan format, blind micro selection, timeline comparison,
  resume behavior, verification, and report interpretation.
- [CI/CD status](CICD.md): current manual GitHub Actions behavior and local
  quality gates. Read when changing verification or deployment automation.
- [Human learnings](learnings/INDEX.md): public-safe discoveries, debugging
  narratives, tradeoffs, and reusable explanations. Use it when recording what
  developers should learn later rather than agent state or work status.
- [Ops UI documentation index](../ops-ui/docs/INDEX.md): Next.js architecture,
  BFF, generated contract, and visual rules. Read before changing `ops-ui/`.
