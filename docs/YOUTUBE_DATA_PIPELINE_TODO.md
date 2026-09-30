# YouTube Pipeline Backlog

## Completed Baseline

- Unified work items, attempts, dependencies, batches, and workflow runs.
- Shared leased worker engine for transcript, cue, micro-event, and timeline.
- Process-to-publish coordinator, independent archive worker, and persistent publishing control.
- `/ops/operations/*`, `/ops/work-items*`, and standardized error envelope.
- Embeddable gating, warning-preserving LLM repair, R2/D1 publish, and Ops UI.
- Candidate DB migration, provenance validation, and atomic cutover tooling.
- Versioned v1.6 segment classification, v3 processing, classification-only
  backfill, and published segment JSON. See [segment classification](SEGMENT_CLASSIFICATION.md).

## Remaining Contract Phase

- Make micro-event, timeline, archive, and channel result persistence directly
  work-item native.
- Remove compatibility adapters under `infra/work`.
- Prove no runtime import of legacy task/job repositories.
- Add and rehearse the Alembic contract revision that removes legacy execution
  tables and columns.

The removal criteria are normative in `docs/WORK_MODEL_CUTOVER.md`. Do not drop
legacy tables before those criteria pass.

## Product Follow-ups

- Cursor pagination for remaining offset-based read projections.
- Archive cleanup/retention command with pointer protection.
- Structured timeline correction for episode summaries/topics.
- Human-labeled segment gold set for measuring category and collaboration
  boundary accuracy. The 30-video runtime evaluation and preview agreement
  check do not establish gold-set accuracy. See
  [the classification experiment](learnings/notes/2026-09-30-segment-category-classification.md).
- Optional external queue only if DB polling becomes a measured bottleneck.
