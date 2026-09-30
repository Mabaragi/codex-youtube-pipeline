# Independent Archive Publish Worker

Date: 2026-10-01

## Decision

- The coordinator schedules archive work and observes its result. An independent
  archive worker uses the shared execution engine, leases, attempts, and delivery
  checkpoints, initially with one slot.
- PostgreSQL stores publication intent separately from global runtime intent.
  OFF blocks new archive claims while generation and workflow advancement remain
  active. Claimed work finishes normally. ON resumes the same pending IDs.
- Publication intent is never frozen into workflow or work-item inputs. Toggling
  it does not recreate workflows, consume daily approvals, or reset failed work.
- Ops UI and `GET/PUT /ops/automation/publishing` share this persistent control.
  Direct remote stage requests also respect OFF; local artifact build remains
  available. Runtime resume preserves publication intent.
- Intentional publication waits are excluded from queue-stall and waiting-stage
  SLA observations. Actual failure observations remain enabled.
- Deploy after a normal drain. The migration moves unclaimed unfinished inline
  archive work to worker execution without altering identity or saved results.
  Explicit retries also normalize historical archive items to worker execution.

## References

- [Architecture](../../docs/CLEAN_ARCHITECTURE.md)
- [Pipeline workers](../../docs/PIPELINE_WORKER_ARCHITECTURE.md)
- [API control](../../docs/AGENT_API_OPERATIONS.md)
- [Local runtime](../../docs/LOCAL_NATIVE_DEPLOYMENT.md)
