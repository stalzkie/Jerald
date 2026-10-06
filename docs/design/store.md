# SQLite store — deep module design

The spec's full data model (`Jerald Agent Degradation Harness – Spec.md`, §"Data model and
reproducibility") names nine tables (`suites`, `tasks`, `configs`, `runs`, `trials`, `steps`,
`scores`, `verdicts`, `noise_profiles`, `canary_points`) plus content-addressed artifact files
and Parquet exports. Building all of it now would be the same mistake the suite/config loaders
avoided: storing data nothing reads. This slice persists exactly what `Orchestrator.
ComparisonResult` produces today — one `Run`, its `Verdict`, and its `TrialRecord`s — so
`jerald run` has somewhere to write and a later `jerald baseline`/`report`/`replay` has
something real to read. Everything else in the full schema is deferred until the feature that
needs it exists: `suites`/`tasks`/`configs` (no content-hashing or caching built),
`noise_profiles` (`calibrate` doesn't exist), `canary_points` (`canary` doesn't exist).

## Schema

Two tables instead of the spec's `runs`/`trials`/`steps`/`scores`/`verdicts` five:

- **`runs`**: one row per `Orchestrator.run_comparison` call — `run_id`, `kind`, `project`,
  `suite_name`, `suite_version`, `seed`, `margin_pp`, `alpha`, `started_at`, `ended_at`, and the
  `Verdict`'s four fields flattened in (`verdict_label`, `verdict_effect_pp`,
  `verdict_ci_low_pp`, `verdict_ci_high_pp`). One run, one verdict, no slices yet — the spec's
  `verdicts` table supports per-slice/per-task verdicts, which don't exist until attribution and
  gate slicing are built.
- **`trials`**: one row per `TrialRecord` — `run_id`, `task_id`, `arm_name`, `trial_index`,
  `seed`, `outcome`, `passed`, `final_message`, `model_reported`, the three `Usage` fields, and
  two JSON columns: `trajectory_json` (the `Step` sequence) and `scores_json` (the `ScoreResult`
  sequence). The spec's `steps` and `scores` tables are collapsed into these two JSON columns —
  normalizing them into their own tables only pays off once something needs to query *across*
  trials by step name or scorer id, which nothing does yet. `PRAGMA journal_mode=WAL` on connect,
  per the spec's storage line.

## Interface

```python
@dataclass(frozen=True)
class StoredRun:
    run_id: str
    kind: str
    project: str
    suite_name: str
    suite_version: int
    seed: int
    margin_pp: float
    alpha: float
    started_at: datetime
    ended_at: datetime
    verdict: Verdict
    trials: Sequence[TrialRecord]  # reuses the Orchestrator's own type


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    kind: str
    project: str
    suite_name: str
    started_at: datetime
    verdict_label: str
    verdict_effect_pp: float


class Store:
    def __init__(self, path: str | Path) -> None: ...

    def save_run(
        self, *, kind: str, project: str, suite_name: str, suite_version: int, seed: int,
        alpha: float, started_at: datetime, ended_at: datetime, result: ComparisonResult,
    ) -> str: ...  # returns a new run_id

    def get_run(self, run_id: str) -> StoredRun | None: ...
    def list_runs(self) -> Sequence[RunSummary]: ...
    def close(self) -> None: ...
```

`save_run` takes the Orchestrator's `ComparisonResult` directly rather than asking the caller to
flatten it first — the CLI's job is "run the comparison, then save it," not "run the comparison,
reshape the result, then save it."

## Trade-offs

High leverage: `save_run(result=orchestrator.run_comparison(...))` is the entire write path for
every future command that produces a Run (`run`, `check`, `canary`, `stress`, `bisect` per
`CONTEXT.md`'s Run definition) — none of them need to know the schema. Thin spot, deliberately:
no artifact files under `.jerald/artifacts/` (trajectories live inline as JSON in `trials`,
fine at today's scale — a single suite's worth of trials, not a fleet); no retention/redaction
(both need real content flowing through the store first before there's anything to retain or
redact); no `suites`/`configs` tables, so there's no cross-run dedup or content-hash lookup yet —
each `save_run` call is self-contained and knows nothing about other runs beyond `list_runs`'
summary view.
