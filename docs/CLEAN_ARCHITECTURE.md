# Clean Architecture

The backend separates policy, orchestration, adapters, and entrypoints so the
same pipeline can be driven by FastAPI, workers, the scheduler, or the CLI.

## Dependency Direction

```text
api | cli | workers
        |
     bootstrap
        |
       infra
        |
   application
        |
      domains
```

- `domains` contains framework-free enums, dataclasses, value objects, and
  validation policy.
- `application` contains commands, queries, workflows, and Protocol ports.
- `infra` implements ports with SQLAlchemy, YouTube, MinIO/R2, Codex, and HTTP
  clients.
- `bootstrap` is the composition root. It converts `CliSettings` into focused
  config and lazily builds the selected executor.
- `api`, `cli`, and `workers` are thin entrypoints.

FastAPI DTOs live in `api/schemas`. Application commands/results are not
Pydantic models. SQLAlchemy models do not cross the infra boundary.

## Transactions

New work-model application use cases open a `WorkUnitOfWorkPort`, mutate one
business operation, then call `commit()` once. Work repositories flush when an
identifier is required but do not commit. The unit of work rolls back when its
context exits without a successful commit.

Processing algorithms still expose a task-shaped internal port while they are
incrementally decomposed, but its SQLAlchemy implementation reads and writes
`work_items` / `work_attempts`. Runtime composition does not construct the old
task/job repositories. New application code must not import the historical
`video_tasks` or `pipeline_jobs` domains; Import Linter enforces this boundary.

## Work Model

- `work_items`: durable requested work and its latest state/output.
- `work_attempts`: every concrete execution, including retry and rerun.
- `work_item_dependencies`: prerequisite edges used by claim queries.
- `work_batches` / `work_batch_items`: one operator command and its selection.
- `workflow_runs` / `workflow_steps`: per-video process-to-publish progress.
- `legacy_work_refs`: immutable mapping from historical task/job IDs to work
  IDs during the expand/compatibility phase.

Statuses are `pending`, `running`, `succeeded`, `failed`, `timed_out`,
`blocked`, and `canceled`. Domain outcomes such as `no_transcript` and
`not_embeddable` use `outcome_code`; they are not extra states.

## Execution

`WorkExecutionEngine` owns claim, dependency blocking, attempt creation,
heartbeat, timeout, lease recovery, and terminal state recording. Registries
store lazy factories so only the selected task type resolves its external
dependencies.

- Inline: channel resolve, video collect, archive publish.
- Worker: transcript collect, cue generation, micro-event extraction, timeline
  composition.
- Coordinator: advances `process_to_publish` after confirmed upstream output.

The coordinator is restart-safe: a workflow lease can expire, be recovered,
and continue from its recorded steps.

## Contracted Legacy Boundary

Alembic revision `20260711_0028` remaps historical job and attempt IDs through
`legacy_work_refs`, rewires provenance foreign keys to `work_items` and
`work_attempts`, then drops the physical `video_tasks`, `pipeline_jobs`, and
`pipeline_job_attempts` tables. Those names remain as read-only SQL views for
historical operational projections; they are not writable sources of truth.

Micro-event, timeline, archive, channel resolution, and video collection now
execute against the current work item/attempt supplied by `WorkExecutionEngine`.
They do not enqueue a second task or create a second job. Startup recovery also
updates only unified work rows.

`legacy_work_refs` is retained as immutable audit provenance. Removing the
read-only views is a separate query-model cleanup and does not block the work
model contract.

## Gates

```powershell
uv run lint-imports --no-cache
uv run python scripts/check_architecture.py
uv run ruff check .
uv run pyrefly check --min-severity warn
```

Ruff enforces cyclomatic complexity `C901 <= 10`. The architecture script also
caps new entry/application modules at 700 lines and functions at 120 lines;
other production modules are capped at 2,000 and 300 lines respectively.
