# Jerald — progress log

Status snapshot for picking this back up. Last updated 2026-10-06, after 7 commits on `main`
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

**19 tests total, all passing.** `ruff check .` clean.

## Open decisions (never formally confirmed — currently running on my recommendations)

From the grilling round, still awaiting your answer or override:

- **Q1 License**: Apache-2.0 (in LICENSE/pyproject.toml already)
- **Q2 Default margin**: 3pp fixed default (implemented as `compare()`'s default)
- **Q3 Judge scorers on the gate**: kept the spec's conditional rule (calibrated + ≥0.9 agreement) — not yet implemented, just not contradicted
- **Q4 First adapter**: Python adapter built first ✅ — CLI/HTTP next, per this recommendation
- **Q5 MVP starting point**: narrow slice (fixed-n compare, outcome scorers, python adapter) before the sequential engine — this is the plan everything below assumes
- **Q6 Validation rigor**: not yet relevant — no public claims have been made
- **Q7 Pace/resourcing**: assumed solo + illustrative timeline — unconfirmed
- **Q8 Name/org handle**: "Jerald" kept, `jerald-cli` suggested as the GitHub handle (repo is currently `stalzkie/Jerald`, under your personal account, not a dedicated org — fine for now, just noting it diverges from the Q8 suggestion)

None of these block current work, but they're worth closing out before anything public (a
release, a README, a announcement) happens.

## What's next

In rough dependency order:

1. **`CliAdapter`** — JSON on stdin/stdout of a subprocess. Needs: subprocess spawn/teardown,
   SIGTERM→SIGKILL escalation on timeout (mirrors the per-call-thread fix just made for
   Python), exit-code-vs-in-band-error-field disambiguation (non-zero exit = infra failure;
   zero exit with an `error` field in the JSON = agent failure).
2. **`HttpAdapter`** — needs an HTTP client dependency decision first (`httpx` vs `requests`;
   `httpx` has native timeout and async-readiness going for it). Needs a mock transport for
   tests (`httpx`'s `MockTransport` or `responses`) rather than a real server.
3. **`FakeAdapter`** — the test double named in `docs/design/adapter-contract.md`, needed once
   the Orchestrator (next item) has tests of its own.
4. **Orchestrator** — wires `Adapter.run_trial` → `Scorer.score` → `compare()` into the actual
   `jerald run` / `jerald compare` command loop. This is where retry-on-infra-error,
   interleaving, and per-provider concurrency caps (all named in the spec's Execution model)
   get built — none of that exists yet.
5. **CLI commands** — `jerald run`, `jerald compare` wired to real logic (currently only
   `--version`/`--help` exist). `jerald init`, `doctor`, `baseline`, `calibrate`, `plan`,
   `check`, `attribute`, `bisect`, `canary`, `stress`, `report`, `capture`, `replay`, `purge`
   are all unbuilt — intentionally deferred past the narrow MVP slice.
6. **Suite/config loading** — nothing parses `suites/*.yaml` or `jerald.yaml` yet; `TaskSpec`
   is currently always hand-constructed in tests.
7. **SQLite store** — `src/jerald/store/` is an empty package; nothing is persisted yet.

Not started at all: trajectory/efficiency/judge Scorer families, the sequential
rounds/alpha-spending engine, fault injection, canaries, attribution, bisect, the sandbox/proxy
layer, reporting formats.

## Where things live

- Spec: `Jerald Agent Degradation Harness – Spec.md` (corrected once, see commit `1d77342`)
- Domain glossary: `CONTEXT.md`
- Design docs: `docs/design/adapter-contract.md`, `docs/design/scorer-and-statistics.md`
- Decision record: `docs/adr/0001-no-fault-injection-or-cancellation-in-adapter.md`
- Fact-check notes: `research/spec-claims-verification.md`
- This file: update it at the end of each work session, don't let it drift
