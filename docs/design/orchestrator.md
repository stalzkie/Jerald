# Orchestrator — deep module design

Designed directly, like `compare()` and `Scorer` in `docs/design/scorer-and-statistics.md`: this
module's shape is dictated by wiring already-designed pieces together (`Adapter.run_trial` →
`Scorer.score` → `compare()`), not an open interface choice with real alternatives to compare.
Scoped to the narrow-MVP slice named in `PROGRESS.md`'s Q5 answer: fixed-n, two arms, no rounds.

## Why `Task` and `Arm` are new types here, not reused from elsewhere

`TaskSpec` (`adapters/base.py`) is deliberately Adapter-facing only — loop-invariant fields the
Adapter needs, nothing about Scorers (see its docstring: "the Adapter never looks at suite config
itself"). But the Orchestrator *does* need to know which Scorers grade each Task's Trials — that's
its whole job. Rather than widen `TaskSpec` and leak Scorer-awareness into the Adapter port,
`Task` wraps a `TaskSpec` with its Scorers at the Orchestrator layer, matching CONTEXT.md's
definition exactly ("Task: ... an input, an environment seed, its Scorers, and tags").

`Arm` is CONTEXT.md's Arm term verbatim: one Configuration under test, represented here as the
`Adapter` instance that reaches it plus the `overrides` to send on every call.

## Interface

```python
@dataclass(frozen=True)
class Task:
    spec: TaskSpec
    scorers: Sequence[Scorer]


@dataclass(frozen=True)
class Arm:
    name: str
    adapter: Adapter
    overrides: Mapping[str, Any]


@dataclass(frozen=True)
class TrialRecord:
    task_id: str
    arm_name: str
    trial_index: int
    seed: int
    trial: TrialResult
    scores: Sequence[ScoreResult]
    passed: bool


@dataclass(frozen=True)
class ComparisonResult:
    verdict: Verdict
    baseline_scores: Mapping[str, Sequence[bool]]
    candidate_scores: Mapping[str, Sequence[bool]]
    trials: Sequence[TrialRecord]


class Orchestrator:
    def __init__(
        self,
        *,
        max_concurrency: int = 4,
        max_retries: int = 3,
        backoff: Callable[[int], None] | None = None,
    ) -> None: ...

    def run_comparison(
        self,
        tasks: Sequence[Task],
        baseline: Arm,
        candidate: Arm,
        trials_per_task: int,
        seed: int = 0,
        margin_pp: float = 3.0,
        alpha: float = 0.05,
    ) -> ComparisonResult: ...
```

## Behaviour

- **Pairing.** For a given `(task, trial_index)`, baseline and candidate get the *same*
  environment seed — CONTEXT.md's "shared environment seeds" and the spec's task-clustered
  *paired* statistics depend on this; it's what makes `compare()`'s paired bootstrap valid.
  Seeds are derived once from the top-level `seed` via one `random.Random`, in a fixed
  `(task, trial_index)` iteration order, so a re-run with the same `seed` reproduces identical
  per-trial seeds regardless of execution order.
- **Interleaving.** The flat list of `(task, arm, trial_index)` jobs is shuffled (same
  `random.Random`, after seed generation) before submission, per the spec's "Arms are
  interleaved so time of day and provider load affect both equally."
- **Concurrency.** Jobs run on a `ThreadPoolExecutor(max_workers=max_concurrency)`. One cap for
  both arms combined — *not* yet the spec's per-provider cap, which needs suite config this
  project hasn't built (`jerald.yaml` loading is still unstarted per `PROGRESS.md`). Noted as a
  gap, not silently assumed away.
- **Retry.** Each job runs through the exact retry loop documented as the Adapter contract's
  usage example (`docs/design/adapter-contract.md`): `AdapterInfrastructureError` is retried
  while `retryable` and attempts remain, then re-raised; any other outcome (including every
  agent-side failure, which is a `TrialResult` with `outcome != "completed"`, not an exception)
  is accepted immediately and never retried. `backoff` is injectable so tests don't sleep —
  mirrors `FakeAdapter`'s "no sleeping" test philosophy.
- **Scoring.** A Trial passes its Task when every `required` Scorer passes it — the exact rule
  from `docs/design/scorer-and-statistics.md`'s usage example, applied per Trial here instead of
  written out at each call site.
- **Output.** `ComparisonResult` carries the per-task-per-arm pass/fail matrices (what
  `compare()` needs) *and* a sorted `Sequence[TrialRecord]` — one per job, each holding the full
  `TrialResult`, every `ScoreResult`, and the env seed used — so a future store/report layer has
  what it needs without re-deriving it. `baseline_scores`/`candidate_scores` are a lossy
  projection of `trials` kept because `compare()`'s signature wants exactly that shape; `trials`
  is the record persistence actually consumes. Sorted by `(task_id, arm_name, trial_index)`
  before returning so the result is deterministic regardless of which thread finished first. The
  Orchestrator itself still does no I/O or persistence — it only shapes the data a store would
  need.

## What's deliberately out of scope here

Sequential rounds and alpha-spending (`plan`'s job, not built), `budget_usd` enforcement (not
relevant until a run can cost real money against a real provider — Q6 territory), per-provider
(as opposed to global) concurrency caps, and persisting results (no store yet). Extending to any
of these should not require changing `run_comparison`'s signature — rounds would call it
repeatedly with a growing `trials_per_task`; budget enforcement would wrap it; persistence would
consume `ComparisonResult` — so none of this is a seam this design needs to pre-build.
