# One-shot model evaluation

`codex-demo evaluation` compares micro-event and timeline model candidates without an API,
Ops UI, scheduler, publication call, or long-running worker. The control database is read only
while the experiment snapshot is created. All later execution uses that immutable snapshot.

Evaluation state and token usage are stored in the separate PostgreSQL database
`codex_model_evaluations`. Source snapshots, normalized results, raw responses, and trace events
are stored only in the private, versioned MinIO bucket `model-evaluations`. Do not commit the
private connection registry, bundles, reports, or experiment data.

## Prepare the infrastructure

1. Create the PostgreSQL database `codex_model_evaluations` with the same application owner used
   for local databases.
2. Keep the existing private, versioned MinIO bucket `model-evaluations` private.
3. Copy
   [`evaluation-connections.example.json`](../scripts/local-home/evaluation-connections.example.json)
   to `.home-deploy/evaluation-connections.json` and replace the placeholder credentials. To use a
   different ignored location, set `CODEX_CLI_EVALUATION_CONNECTIONS_FILE`.
4. Validate the exact database and bucket names and apply the evaluation-only Alembic tree:

   ```powershell
   uv run codex-demo evaluation prepare
   ```

`prepare` never creates a bucket and never migrates the operational `codex` database. A missing
bucket, disabled bucket versioning, or a connection pointing at a different database is a hard
failure.

## Plan format

The v1 plan requires an immutable experiment key, explicit operational video IDs, at least one
candidate for each stage, and the candidate prompt and generation settings. A missing prompt ID is
resolved to the active prompt during `create`; the exact body, hash, and resolved ID are stored in
each source snapshot, and the resolved ID is frozen in the experiment's candidate configuration.

```json
{
  "version": 1,
  "experimentKey": "july-micro-timeline-baseline",
  "videoIds": [101, 202],
  "microCandidates": [
    {
      "key": "micro-balanced",
      "model": "gpt-5.6-terra",
      "reasoningEffort": "medium",
      "promptVersionId": 12,
      "windowMinutes": 30,
      "overlapMinutes": 5
    },
    {
      "key": "micro-quality",
      "model": "gpt-5.6-sol",
      "reasoningEffort": "high",
      "windowMinutes": 30,
      "overlapMinutes": 5
    }
  ],
  "timelineCandidates": [
    {
      "key": "timeline-balanced",
      "model": "gpt-5.6-terra",
      "reasoningEffort": "medium",
      "copyStyle": "LIGHT_FANDOM_V1"
    }
  ],
  "repetitions": 1,
  "runConcurrency": 1,
  "microWindowConcurrency": 1
}
```

The same `experimentKey` and canonical plan hash return the existing experiment. Reusing the key
with a different plan is rejected. Candidate aliases and blind run IDs are stable within an
experiment.

## Agent execution sequence

All commands emit result JSON on stdout and progress on stderr. They never print transcripts, raw
model responses, connection secrets, or unblinded model mappings.

```powershell
uv run codex-demo evaluation create --plan .home-deploy/experiments/plans/july.json
uv run codex-demo evaluation run --experiment-id <id> --stage micro
uv run codex-demo evaluation bundle --experiment-id <id> --stage micro
uv run codex-demo evaluation score import --experiment-id <id> --file .home-deploy/experiments/scores/micro.json
uv run codex-demo evaluation select-micro --experiment-id <id> --file .home-deploy/experiments/selections/micro.json
uv run codex-demo evaluation run --experiment-id <id> --stage timeline
uv run codex-demo evaluation bundle --experiment-id <id> --stage timeline
uv run codex-demo evaluation score import --experiment-id <id> --file .home-deploy/experiments/scores/timeline.json
uv run codex-demo evaluation status --experiment-id <id> --json
uv run codex-demo evaluation report --experiment-id <id> --format md
uv run codex-demo evaluation verify --experiment-id <id>
```

The micro bundle exposes cues, normalized candidate output, and validation warnings. It omits
models, reasoning effort, token usage, raw responses, and runtime identifiers. Score files use the
bundle's `blindRunId`. New micro bundles use rubric v2 with these six 1–5 scores:

- `asrComprehensionAccuracy`: understands noisy or fragmented ASR in context, including proper
  nouns, corrections, and transcription errors, without inventing unsupported meaning

- `boundaryEvidenceAccuracy`
- `meaningfulCoverage`
- `semanticTopicAccuracy`
- `noiseDuplicationControl`
- `timelineInputUsefulness`

A score import file uses the blind run ID and the exact rubric keys. Notes and evidence are
optional:

```json
{
  "version": 1,
  "stage": "micro",
  "evaluator": "agent",
  "rubricVersion": "micro-v2",
  "items": [
    {
      "blindRunId": "<blind-run-id>",
      "scores": {
        "asrComprehensionAccuracy": 4,
        "boundaryEvidenceAccuracy": 4,
        "meaningfulCoverage": 5,
        "semanticTopicAccuracy": 4,
        "noiseDuplicationControl": 4,
        "timelineInputUsefulness": 5
      },
      "notes": "Strong evidence alignment; one overlapping event could be merged.",
      "evidence": ["cue-001 through cue-008"]
    }
  ]
}
```

Every experiment pins its micro and timeline rubric versions when it is created. The score file's
`rubricVersion` must match the corresponding blind bundle; a `micro-v1` score cannot satisfy a
`micro-v2` experiment because it omits ASR comprehension accuracy.

Timeline score files use the same shape with `stage: "timeline"` and
`rubricVersion: "timeline-v1"`, plus the five timeline rubric keys below.

The selection file must map every experiment video to one successful, scored micro run:

```json
{
  "version": 1,
  "selections": [
    {"videoId": 101, "blindRunId": "<blind-run-id>"},
    {"videoId": 202, "blindRunId": "<blind-run-id>"}
  ]
}
```

Every timeline candidate for a video uses that same selected micro run. Once any timeline attempt
starts, the selection cannot change. Create another experiment to compare a different micro input.
Timeline rubric v1 requires these five 1–5 scores:

- `coverageOrdering`
- `boundaryCoherence`
- `titleSummaryFactuality`
- `topicNavigationUsefulness`
- `concisionReadability`

## Recovery and interpretation

If the process stops, run `resume` for the failed stage. A PostgreSQL advisory lock prevents two
CLI processes from running the same experiment. `resume` marks a leftover running attempt as
abandoned, retains its token records, reuses successful micro-window checkpoints, and creates a
new attempt only for failed or interrupted runs. Timeline retry regenerates the whole timeline;
successful runs are never regenerated.

```powershell
uv run codex-demo evaluation resume --experiment-id <id> --stage micro
uv run codex-demo evaluation resume --experiment-id <id> --stage timeline
```

The report separates tokens from successful attempts from actual consumed tokens, which include
failed calls, repairs, and retries. Both totals are split into input, output, cached input, and
reasoning output tokens so output-heavy candidates remain visible. It does not estimate money.
`--unblind` is accepted only after
all runs are terminal and every successful run has a score. `verify` compares every recorded
object key, SHA-256, and byte size against MinIO. A result is never marked successful before its
required normalized result object is stored.

Evaluation commands do not write operational work items, micro-events, timelines, usage rows,
archive artifacts, or publication tables. Publication is never called by this workflow.
