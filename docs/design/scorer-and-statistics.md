# Scorer and statistics engine — deep module design

Companion to the Adapter contract design (see chat / forthcoming ADR). These two
modules are **in-process** (pure computation, no I/O), so there's no seam to
compare adapters across — one direct design each, reasoned through the same
depth/leverage/locality lens.

## Scorer (outcome family)

### Interface

```python
@dataclass(frozen=True)
class ScoreResult:
    scorer_id: str
    passed: bool
    value: float          # 0.0-1.0; pass/fail scorers report 1.0/0.0
    evidence: str          # human-readable: what matched or why it didn't
    required: bool = True  # mirrors the Scorer config; carried through for the gate


class Scorer(Protocol):
    def score(self, trial: TrialResult) -> ScoreResult: ...
```

A `Scorer` is a pure function of a `TrialResult` (the Adapter's response: `final_message`,
`trajectory`, `usage`) to one `ScoreResult`. No network, no filesystem, no clock reads beyond
what `TrialResult` already carries.

Three outcome scorers for the MVP slice, each a small `Scorer` implementation:

```python
def exact(expected: str) -> Scorer: ...
def regex(pattern: str) -> Scorer: ...
def json_schema(schema: dict) -> Scorer: ...
```

Each is a factory returning a closure/callable satisfying `Scorer` — not a class hierarchy.
There is nothing to override or extend; a new outcome check is a new factory function, not a
subclass.

**Invariants:**
- `score()` never raises for a malformed `final_message` (e.g. invalid JSON against
  `json_schema`) — that's a failed match, not an error. It only raises for a programmer error
  (e.g. an invalid regex pattern), and that happens at factory-construction time, not at
  `score()` time, so suite-loading fails fast before any Trial runs.
- `score()` is deterministic: same `TrialResult` in, same `ScoreResult` out, always.

### Usage example

```python
scorers = [exact("ok"), regex(r"refund(ed)?"), json_schema(REFUND_SCHEMA)]
results = [s.score(trial) for s in scorers]
task_passed = all(r.passed for r in results if r.required)
```

### What the implementation hides

String comparison, regex compilation and matching, JSON parsing and schema validation
(likely via `jsonschema`), and turning a raw match/mismatch into evidence text a report can
show verbatim. Callers never see library choice (`re`, `jsonschema`) or how evidence strings
are formatted.

### Dependency strategy

None needed — no adapter, no port. `jsonschema` is a vendored implementation detail, not a
seam; nothing varies across it in this project (one JSON Schema validator, always).

### Trade-offs

High leverage: three scorer types collapse to the same one-method interface, so the
Orchestrator's scoring loop (`[s.score(trial) for s in scorers]`) never changes shape as more
scorer types are added later (trajectory, efficiency, judge families reuse the identical
`Scorer` protocol). Thin spot: `Scorer` says nothing about *which* trajectory step evidence
came from — fine for the outcome family (it only ever looks at `final_message`), but the
trajectory family (`tool_called`, `args_match`, etc.) will need evidence that points at a
specific step. That's deliberately deferred: this interface is sized for the outcome family
only, and the trajectory family gets designed when it's actually built, not speculatively now.

---

## Statistics engine (fixed-n paired comparison)

### Interface

```python
@dataclass(frozen=True)
class Verdict:
    label: Literal["REGRESSION", "IMPROVEMENT", "NO_REGRESSION", "INCONCLUSIVE"]
    effect_pp: float       # Δ, candidate minus baseline, percentage points
    ci_low_pp: float
    ci_high_pp: float
    margin_pp: float


def compare(
    baseline_scores: Mapping[TaskId, Sequence[bool]],
    candidate_scores: Mapping[TaskId, Sequence[bool]],
    margin_pp: float = 3.0,
    alpha: float = 0.05,
    n_bootstrap: int = 10_000,
    seed: int = 0,
) -> Verdict: ...
```

One function. Inputs are already-scored pass/fail outcomes per task per arm (not raw
Trials — scoring happens upstream via `Scorer`); output is one `Verdict`. This is the fixed-n
slice of the full sequential engine (spec's "Procedure" steps 3-5 minus rounds and
alpha-spending): every task gets the same number of trials, one bootstrap pass, one decision,
no stopping rule.

**Invariants:**
- `baseline_scores` and `candidate_scores` must have the same key set (same tasks) — raises
  `ValueError` otherwise; silently dropping a mismatched task would silently change what Δ
  means.
- Deterministic given `seed`: same inputs and seed produce the same `Verdict`, so a report's
  "replay" claim is actually true for the statistics step.
- Matches the spec's verdict rule exactly: `REGRESSION` iff `ci_high_pp < -margin_pp`,
  `IMPROVEMENT` iff `ci_low_pp > margin_pp`, `NO_REGRESSION` iff `ci_low_pp > -margin_pp` and
  not `IMPROVEMENT`, else `INCONCLUSIVE`.

### Usage example

```python
verdict = compare(baseline_scores=baseline, candidate_scores=candidate, margin_pp=3.0)
if verdict.label == "REGRESSION":
    sys.exit(1)
```

### What the implementation hides

The two-level paired bootstrap (resample tasks, then trials within each task/arm, 10,000
times), the Δ estimator (mean of per-task candidate-minus-baseline pass rate), and the
margin-based verdict rule. Callers never see the resampling loop, the RNG, or the CI
construction.

### Dependency strategy

None — `numpy`'s RNG is an implementation detail (vendored, not a seam), same reasoning as
`jsonschema` above: there's exactly one bootstrap implementation in this project, nothing
varies across it.

### Trade-offs

High leverage: one function call replaces "compute per-task pass rates, resample twice,
build a CI, apply the verdict rule" at every caller (`compare`, `check`, `attribute`,
`bisect` all need exactly this). High locality: if the bootstrap method or the verdict
thresholds ever change (e.g. switching to the sign-flip permutation test below 30 tasks, per
the spec's "Known limits"), it changes in one place and every command gets the fix for free.
Deliberately out of scope here — and left for a later deepening pass, not stubbed: sequential
rounds/alpha-spending (`plan`'s job), the sign-flip fallback for small suites, and per-slice
Holm correction. Bolting those onto `compare()` later should extend it (new optional
parameters or a second function for the sequential case), not break this fixed-n seam, since
`check`/`compare --fixed-n` should keep working unchanged.
