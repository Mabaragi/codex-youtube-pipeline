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

Legacy content repositories still used by the compatibility processors own
their historical commits. New application code must not import the legacy
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

## Compatibility Boundary

Micro-event, timeline, archive, and channel adapters currently bridge proven
legacy persistence code while writing canonical work provenance. These adapters
are confined to `infra/work` and assembled only in `bootstrap`. They are not
public API contracts and must not leak back into `application`.

Do not drop `video_tasks`, `pipeline_jobs`, or their provenance columns until
the conditions in `docs/WORK_MODEL_CUTOVER.md` are satisfied. Data preservation
takes priority over an unsafe one-step contract migration.

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
