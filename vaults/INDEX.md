# Agent Context Vault

Read the root `AGENTS.md` first. Use this index to load only the context needed
for the current task. Public product and operations documentation lives in
`docs/`; secrets and private runtime logs do not belong here.

## Workflows

- [Verification](workflows/verification.md): choose backend/frontend gates.
- [Completion](workflows/completion.md): summarize substantial work and decide
  whether a private worklog is needed.
- [Documentation](workflows/documentation.md): place and index durable docs.
- [Durable improvements](durable/INDEX.md): reusable process rules learned from
  repeated gaps.
- [Private worklog template](worklogs/README.md): ignored monthly fallback.

## Project Context

- [Drain-based local runtime decision](decisions/2026-07-14-drain-based-local-runtime-orchestration.md):
  explains why runtime intent is persisted as `active/draining/stopped`, which
  operations drain blocks, and why timeout never escalates to force. Read before
  changing local start, stop, deploy, claim gating, or runtime-state semantics.
- [Public docs](../docs/INDEX.md): architecture, API, pipeline, deployment, and
  archive references.
- [API operations](../docs/AGENT_API_OPERATIONS.md): source for API-only agent
  operation.
- [Work runbooks](../docs/AGENT_WORK_RUNBOOKS.md): repeatable pipeline, retry,
  publish, and recovery procedures.
- [API/domain agent guide](agents/api-domains.md): code ownership and dependency
  boundaries for backend changes.
- [Ops UI guide](../ops-ui/AGENTS.md): frontend context and verification.

## Boundary

Use `docs/` for facts people and API-only agents need. Use `vaults/` for agent
workflow routing and reusable engineering rules. Keep private operational state
in ignored worklogs or the configured external system.
