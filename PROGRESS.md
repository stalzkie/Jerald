# Jerald — progress log

Status snapshot for picking this back up. Last updated 2026-10-06, after 14 commits on `main`
(pushed to [github.com/stalzkie/Jerald](https://github.com/stalzkie/Jerald), CI green on
Python 3.11/3.12/3.13 throughout).

## How we got here

Working through the `mattpocock-skills` plugin in the order that fit a greenfield project
(spec existed, no code):

1. **grilling** — stress-tested the spec's open questions (Q1–Q8: license, default margin,
   judge-scorer gating, first adapter, MVP starting point, validation rigor, pace, name). The
   user redirected to scaffolding before formally answering; everything built since has used
   my recommended answers as working defaults. **These are not locked in** — see "Open
   decisions" below.
2. **research** — verified every externally-cited claim the spec flagged as unchecked
   (`research/spec-claims-verification.md`). One correction landed in the spec: the
   DeepEval/Promptfoo/Inspect AI landscape row undersold all three tools. The "Name" open
   question was resolved clean (no GitHub/npm/trademark conflict).
3. **domain-modeling** — `CONTEXT.md`: the spec's 15 core terms plus four load-bearing ones it
   used without defining (Run vs. Trial, Scorer vs. Score, Factor, Behavioral fingerprint).
4. **codebase-design** — three independently-designed Adapter interfaces compared side by
   side (minimal / maximally flexible / optimized for the common caller), then a hybrid
   chosen. Caught two real issues this way: fault injection and cancellation don't belong on
   the Adapter port at all (fault injection runs through proxy env vars per the spec's own
   architecture; budget enforcement is pre-trial, not reactive) — recorded as
   `docs/adr/0001-no-fault-injection-or-cancellation-in-adapter.md`. Scorer and the statistics
   engine were designed directly (pure in-process, no seam to compare alternatives on) —
   `docs/design/scorer-and-statistics.md` and `docs/design/adapter-contract.md`.
5. **tdd** — building the narrow MVP slice against those designs (see below).

The narrow-MVP framing (fixed-n `compare` before the full sequential/bootstrap engine; outcome
Scorers before trajectory/efficiency/judge families; `python` Adapter before `http`/`cli`) was
my Q5 recommendation during grilling, used as the working plan since it was never formally
confirmed or overridden.

## What's built (all test-first, all green in CI)

| Module | File | Tests | Notes |
|---|---|---|---|
| Package scaffold | `pyproject.toml`, `src/jerald/cli.py` | 1 | `click`-based CLI, installs, `--version`/`--help` work |
| CI | `.github/workflows/ci.yml` | — | lint (`ruff`) + test (`pytest`) matrix, Python 3.11/3.12/3.13 |
| Adapter data types | `src/jerald/adapters/base.py` | — | `TaskSpec`, `Step`, `Usage`, `TrialResult`, `AdapterInfrastructureError`, `Adapter` protocol. Structural only, no behavior to test. |
| Scorer base | `src/jerald/scorers/base.py` | — | `ScoreResult`, `Scorer` protocol |
| Outcome Scorers | `src/jerald/scorers/outcome.py` | 9 | `exact`, `regex`, `json_schema`; covers pass/fail + the no-raise-on-malformed-input invariant |
| Statistics engine | `src/jerald/analysis/compare.py` | 5 | Fixed-n two-level paired bootstrap; task-set invariant, all three verdict outcomes, seed-determinism |
| PythonAdapter | `src/jerald/adapters/python_adapter.py` | 5 | Wraps a plain `run(task, config, seed)` call: success, AUT exceptions → `agent_error` (never propagated), `timeout_s` enforcement, `max_steps_exceeded` detection. **Found and fixed a real bug**: a shared single-worker thread pool let a timed-out call's lingering thread block every later call on the same adapter instance — pinned with a timing assertion, fixed by giving each call its own disposable worker. |
| CliAdapter | `src/jerald/adapters/cli_adapter.py` | 6 (+1 skipped on Windows) | JSON on stdin/stdout of a subprocess, per `docs/design/adapter-contract.md`. Non-zero exit → `AdapterInfrastructureError(retryable=True)` (process crash, might be transient); malformed JSON on stdout with exit 0 → `AdapterInfrastructureError(retryable=False)` (wire-schema bug, retrying won't help); exit 0 with an in-band `"error"` field → `agent_error` outcome, never an exception. Timeout escalates `terminate()` (SIGTERM on POSIX) → wait `kill_grace_s` → `kill()` (SIGKILL) if still alive. The SIGTERM-ignored escalation test is `skipif(win32)`: Windows has no catchable SIGTERM — `Popen.terminate()` is an unconditional `TerminateProcess` there, so the escalation path can only be observed on the Linux CI matrix, not on a Windows dev machine. |
| HttpAdapter | `src/jerald/adapters/http_adapter.py` | 10 | POSTs the spec's exact wire shape (`task_id`, `trial_id`, `messages`, `env.seed`, `overrides`) and parses `final_message`/`trajectory`/`model_reported`/in-band `error`. Added `httpx>=0.27` as a real dependency (decided over `requests`: native per-request timeout, no separate `responses`-style mocking library needed — tests use `httpx.MockTransport` injected via a `client` constructor param, no real server). 5xx and 429 → `AdapterInfrastructureError(retryable=True)` (429 called out because the spec's own fault-injection table (§Tool, transient error) names 429/503 as the transient pair); other 4xx → `retryable=False`; connection failure → `retryable=True`; malformed JSON body → `retryable=False`; `httpx.TimeoutException` → `outcome="timeout"` (data, not an exception, matching the Adapter contract's timeout rule). |

| FakeAdapter | `src/jerald/adapters/fake_adapter.py` | 5 | The test double named in `docs/design/adapter-contract.md`: a dict keyed by `(task_id, trial_id)` or a callable, either returning the scripted `TrialResult`. `fail_calls` scripts which 0-indexed call numbers raise an `AdapterInfrastructureError` (a default one, or one passed in via `error=`) instead, so the Orchestrator's retry loop can be tested deterministically — no network, no subprocess, no sleeping. |

| Orchestrator | `src/jerald/orchestrator/core.py` | 6 | Wires `Adapter.run_trial` → `Scorer.score` → `compare()` for the fixed-n, two-arm slice (design doc: `docs/design/orchestrator.md`). New `Task` (TaskSpec + its Scorers) and `Arm` (name + Adapter + overrides) types live here, not on the Adapter port, since the Adapter is deliberately Scorer-blind. Pairs baseline/candidate with the *same* env seed per `(task, trial_index)` — required for `compare()`'s paired bootstrap to mean anything — then shuffles submission order for interleaving. Runs jobs on a `ThreadPoolExecutor` (one global `max_concurrency`, not yet per-provider — no suite config to drive that split exists yet). Retry loop is the Adapter contract's documented usage example verbatim: retryable infra errors retry up to `max_retries` with an injectable `backoff`; agent-side failures (a `TrialResult`, not an exception) are never retried. `FakeAdapter.call_count` was made public (was `_call_count`) so these tests can assert exact retry counts. |

| Outcome Scorers (`required`) | `src/jerald/scorers/outcome.py` | +3 | Small extension needed by the suite loader: `exact`/`regex`/`json_schema` now take `required: bool = True` and carry it through to `ScoreResult.required`, which the field's own docstring already said was "carried through for the gate" but nothing threaded it until now. |
| Suite loader | `src/jerald/suite/loader.py` | 8 | Parses a suite YAML file (`docs/design/suite-loading.md`) into `Suite(name, version, tasks, trials_per_task)`, where `tasks` is ready to hand straight to `Orchestrator.run_comparison`. Only parses what's already built: `exact`/`regex`/`json_schema` scorers (any other `type:` — `trajectory`, `efficiency`, `state`, `python`, `shell`, judge — raises `SuiteLoadError` naming it as not implemented yet, rather than silently skipping); per-task `timeout_s`/`max_steps` override the suite's `defaults`. A scorer-less task is rejected at load time (it would vacuously pass every Trial). Deliberately *not* parsed, since nothing consumes them: `tags` (no gate/`critical_slices` logic exists), `input.env.seed`/`fixtures` (the Orchestrator already derives its own per-trial seed; fixtures need the sandbox layer, which doesn't exist). Added `pyyaml` as a dependency. |

| Config loader | `src/jerald/config/loader.py` | 8 | Parses `jerald.yaml` (`docs/design/config-loading.md`) into `ProjectConfig(project, adapter, baseline, candidate, margin_pp, alpha)` — the Arm side, pairing with the suite loader's Task side. Builds **one** Adapter from the `adapter:` block (same AUT serves both arms; `overrides` is what tells it which Configuration to behave as) and wraps it in two `Arm`s from `configs.baseline`/`configs.candidate`. `label` is popped out of each config's entries before they become `overrides`, since it's display metadata, not one of the six Factors the Adapter contract's `overrides` field actually carries. Supports `type: http` (`url`), `type: cli` (`command: [...]`), and `type: python` (`target: "module:attr"`, an import-string convention the spec doesn't specify a shape for — chosen by analogy to Gunicorn/Celery/entry-points since nothing else suggests one); `type: mcp` raises `ConfigLoadError` naming it not implemented yet. `policy.margin_pp`/`alpha` are optional, defaulting to 3.0/0.05 (the Q2 default); `min_trials`/`max_trials`/`budget_usd`/`gate.critical_slices` are deliberately not parsed — no sequential engine, cost tracking, or tag/slice support exists yet to consume them. Also made `HttpAdapter.url`, `CliAdapter.command`, and `PythonAdapter.aut` public (were `_url`/`_command`/`_aut`) since they're an adapter's configuration, not secret state, and the config loader's tests need to assert on them. |

| `jerald compare` | `src/jerald/cli.py` | 8 | The first real, end-to-end CLI command: loads both YAML files, builds the Orchestrator, prints the `Verdict`, and maps its label to the spec's CLI reference exit codes (0 no-regression/improvement, 1 regression, 2 inconclusive). `--suite` is required but deliberately *not* `required=True` at the Click level — Click's own missing-option exit code is 2, which collides with the spec's domain meaning for 2 ("Inconclusive"); it's checked manually so a usage error reliably exits 3. `ConfigLoadError`/`SuiteLoadError` → exit 3; `AdapterInfrastructureError` → exit 4. `--dry-run` prints the resolved plan (suite, task count, trials, margin/alpha, both arms' overrides) without running anything. `--out` writes the verdict as JSON. **Not implemented**, named explicitly in the docstring rather than silently absent: `--max-trials`/`--fixed-n` (no sequential engine exists to need an escape hatch from), `--budget-usd` (no cost tracking). `jerald run` is still unbuilt — its whole point is storing trials, and the SQLite store doesn't exist yet, so building it now would be half-finished. Also fixed both loaders to wrap a missing file in `SuiteLoadError`/`ConfigLoadError` instead of letting `FileNotFoundError` escape as a raw traceback. |

**74 tests total (1 skipped on win32), all passing.** `ruff check .` clean.

## Open decisions (never formally confirmed — currently running on my recommendations)

From the grilling round, still awaiting your answer or override:

- **Q1 License**: Apache-2.0 (in LICENSE/pyproject.toml already)
- **Q2 Default margin**: 3pp fixed default (implemented as `compare()`'s default)
- **Q3 Judge scorers on the gate**: kept the spec's conditional rule (calibrated + ≥0.9 agreement) — not yet implemented, just not contradicted
- **Q4 First adapter**: Python adapter built first ✅, CliAdapter second ✅, HttpAdapter third ✅ — `mcp` is the only production adapter left unbuilt
- **Q5 MVP starting point**: narrow slice (fixed-n compare, outcome scorers, python adapter) before the sequential engine — this is the plan everything below assumes
- **Q6 Validation rigor**: not yet relevant — no public claims have been made
- **Q7 Pace/resourcing**: assumed solo + illustrative timeline — unconfirmed
- **Q8 Name/org handle**: "Jerald" kept, `jerald-cli` suggested as the GitHub handle (repo is currently `stalzkie/Jerald`, under your personal account, not a dedicated org — fine for now, just noting it diverges from the Q8 suggestion)

None of these block current work, but they're worth closing out before anything public (a
release, a README, a announcement) happens.

## What's next

In rough dependency order:

1. **SQLite store** — `src/jerald/store/` is an empty package; nothing is persisted yet.
   `ComparisonResult` carries what a store would need (the verdict plus both score matrices).
   This unblocks `jerald run` (its whole point is storing trials) and `jerald baseline`/
   `check`/`report`/`replay`/`purge`, all of which need a stored Run to act on.
2. **`jerald run`** — needs the store (item 1). Until then `jerald compare` is the only
   working command.
3. **Per-provider concurrency caps** — the Orchestrator currently takes one global
   `max_concurrency`; splitting it per-provider needs the config loader to carry which
   provider each Arm's Adapter talks to, which it doesn't today (one Adapter, shared by both
   Arms — there's only ever one provider per comparison in this slice).
4. **`McpAdapter`** — the fourth production adapter named in the spec and in
   `docs/design/adapter-contract.md`'s registry note; not started, no design work done on it
   yet (what MCP client library, what transport, how `JERALD_TOOL_BASE_URL` fault injection
   applies to MCP tool calls specifically). Both loaders already raise a clear "not implemented
   yet" error for `type: mcp`, so adding it is additive once designed.
5. **Trajectory/efficiency/state/judge Scorer families** — the suite loader already raises a
   clear "not implemented yet" error for these `type:` values, so adding one is additive: a new
   entry in the loader's scorer factory registry plus the Scorer implementation itself.
6. **The rest of the CLI surface** — `jerald init`, `doctor`, `baseline`, `calibrate`, `plan`,
   `check`, `attribute`, `bisect`, `canary`, `stress`, `report`, `capture`, `replay`, `purge`,
   plus `compare`'s own deferred flags (`--max-trials`/`--fixed-n`, needing the sequential
   engine; `--budget-usd`, needing cost tracking) — all intentionally deferred past the narrow
   MVP slice, all unblocked by different future items on this list, not by each other.

Not started at all: trajectory/efficiency/judge Scorer families, the sequential
rounds/alpha-spending engine, fault injection, canaries, attribution, bisect, the sandbox/proxy
layer, reporting formats.

## Where things live

- Spec: `Jerald Agent Degradation Harness – Spec.md` (corrected once, see commit `1d77342`)
- Domain glossary: `CONTEXT.md`
- Design docs: `docs/design/adapter-contract.md`, `docs/design/scorer-and-statistics.md`,
  `docs/design/orchestrator.md`, `docs/design/suite-loading.md`, `docs/design/config-loading.md`
- Decision record: `docs/adr/0001-no-fault-injection-or-cancellation-in-adapter.md`
- Fact-check notes: `research/spec-claims-verification.md`
- This file: update it at the end of each work session, don't let it drift
