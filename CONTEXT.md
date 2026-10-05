# Jerald

Jerald decides whether an AI agent got worse after a change, and names which change caused it, by running a task suite many times against a baseline and a candidate and returning a statistical verdict.

## Language

### Comparison model

**Suite**:
A versioned set of Tasks with their Scorers, tags, and optional fault plans.
_Avoid_: Benchmark, test set — a Suite belongs to one project and isn't meant for cross-agent leaderboards.

**Task**:
One scenario within a Suite: an input, an environment seed, its Scorers, and tags.
_Avoid_: Test case, scenario alone.

**Agent under test (AUT)**:
The agent system being evaluated, reached through an Adapter.
_Avoid_: Agent (too generic — "agent" is used for AI agents in general; AUT is specifically the one being tested), SUT.

**Configuration**:
A complete description of one version of the AUT, fixing a value for every Factor: model, prompt, tools, retrieval, parameters, and code revision.
_Avoid_: Version, build, release.

**Factor**:
One of the six dimensions a Configuration fixes and Jerald can vary and attribute: model, prompt, tools, retrieval, parameters, code revision.
_Avoid_: Parameter — "parameters" is itself one specific Factor, so "parameter" cannot be used loosely to mean "factor" without ambiguity.

**Arm**:
One Configuration under test within a comparison. The simplest comparison has exactly two arms — baseline and candidate — but factorial Attribution runs use four to eight.
_Avoid_: Variant, treatment, side.

**Run**:
One invocation of a Jerald command (`run`, `compare`, `check`, `canary`, `stress`, `bisect`), stored with its own policy, budget, and manifest, and containing every Trial it spent.
_Avoid_: Using "run" loosely to mean a single Trial — a Run contains many Trials across one or more Arms.

**Trial**:
One execution of one Task by one Arm, with its own seed and recorded Trajectory.
_Avoid_: Attempt, test run.

**Trajectory**:
The ordered record of messages, tool calls, results, errors, tokens, and timing produced by a single Trial.
_Avoid_: Transcript, log.

### Scoring

**Scorer**:
A named check (outcome, trajectory, efficiency, or judge) configured on a Task that evaluates a Trial and produces a Score.
_Avoid_: Check, validator — reserve those for general programming use.

**Score**:
A Scorer's output for a Trial: pass or fail, or a value from 0 to 1, with evidence such as the matching Trajectory step.
_Avoid_: Result, outcome.

### Statistics

**Effect (Δ)**:
Candidate minus baseline mean pass rate, averaged over Tasks, in percentage points.
_Avoid_: Delta alone (fine in prose, but the glossary term is "Effect").

**Margin (δ)**:
The smallest drop in Effect that counts as a real regression; 3 pp by default.
_Avoid_: Threshold, tolerance.

**MDE**:
Minimum detectable effect — the smallest Effect the trials planned for a Run can detect at the chosen statistical power.
_Avoid_: Sensitivity.

**Verdict**:
The Run's conclusion about Effect: REGRESSION, IMPROVEMENT, NO REGRESSION, or INCONCLUSIVE.
_Avoid_: Result (too generic — Score is also a kind of result).

**Noise profile**:
The measured run-to-run variability for a Suite and Configuration, produced by calibration.
_Avoid_: Variance alone — Noise profile is the named, stored artifact; variance is the statistic inside it.

### Operations

**Budget**:
A hard cap on USD, Trials, or wall time enforced during one Run.
_Avoid_: Limit alone.

**Canary**:
A small, programmatically scored Suite run on a schedule against one pinned Configuration, to detect provider-side drift.
_Avoid_: Monitor, health check.

**Behavioral fingerprint**:
The vector recorded per Canary run — pass rate per category, format-validity rate, refusal rate, output-length quantiles, tool-call-order frequencies, and latency quantiles — compared across runs to detect drift.
_Avoid_: Signature, profile (Noise profile is a different, unrelated artifact).
