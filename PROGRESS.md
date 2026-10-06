# Jerald — progress log

Status snapshot for picking this back up. Last updated 2026-10-06, after 11 commits on `main`
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

**46 tests total (1 skipped on win32), all passing.** `ruff check .` clean.

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

1. **CLI commands** — `jerald run`, `jerald compare` wired to the Orchestrator (currently only
   `--version`/`--help` exist). `jerald init`, `doctor`, `baseline`, `calibrate`, `plan`,
   `check`, `attribute`, `bisect`, `canary`, `stress`, `report`, `capture`, `replay`, `purge`
   are all unbuilt — intentionally deferred past the narrow MVP slice.
2. **Suite/config loading** — nothing parses `suites/*.yaml` or `jerald.yaml` yet; `TaskSpec`
   and the Orchestrator's `Task`/`Arm` are currently always hand-constructed in tests. This is
   the real blocker on wiring up `jerald compare` for real: the CLI needs something to build
   `Task`/`Arm` lists from before it can call `Orchestrator.run_comparison`.
3. **SQLite store** — `src/jerald/store/` is an empty package; nothing is persisted yet.
   `ComparisonResult` carries what a store would need (the verdict plus both score matrices).
4. **Per-provider concurrency caps** — the Orchestrator currently takes one global
   `max_concurrency`; splitting it per-provider needs the suite config (item 2) to know which
   provider each Arm's Adapter talks to.
5. **`McpAdapter`** — the fourth production adapter named in the spec and in
   `docs/design/adapter-contract.md`'s registry note; not started, no design work done on it
   yet (what MCP client library, what transport, how `JERALD_TOOL_BASE_URL` fault injection
   applies to MCP tool calls specifically).

Not started at all: trajectory/efficiency/judge Scorer families, the sequential
rounds/alpha-spending engine, fault injection, canaries, attribution, bisect, the sandbox/proxy
layer, reporting formats.

## Where things live

- Spec: `Jerald Agent Degradation Harness – Spec.md` (corrected once, see commit `1d77342`)
- Domain glossary: `CONTEXT.md`
- Design docs: `docs/design/adapter-contract.md`, `docs/design/scorer-and-statistics.md`,
  `docs/design/orchestrator.md`
- Decision record: `docs/adr/0001-no-fault-injection-or-cancellation-in-adapter.md`
- Fact-check notes: `research/spec-claims-verification.md`
- This file: update it at the end of each work session, don't let it drift
