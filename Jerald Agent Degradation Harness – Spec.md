# Jerald: Agent Degradation Harness – Spec

Oct 5, 2026 · @Grimdark Fantasy

## Overview and positioning

Jerald is an open-source harness that tells you, with measured confidence, whether an AI agent got worse after a change, and which change caused it.

**The problem.** Agent quality shifts without a code change: a provider updates the model behind a stable name, a tool schema drifts, a prompt gets edited. Agent runs are stochastic, so one run per test cannot separate a real drop from noise.

**What Jerald does.** It runs the same task suite many times against a baseline and a candidate, interleaved and seeded, then returns one of four verdicts with an effect size and a confidence interval. It spends extra trials only on tasks where the answer is still unclear.

**What sets it apart from snapshot-and-diff tools:**

- Statistics first: task-clustered paired comparisons and a measured noise floor, building on published ideas such as three-valued verdicts and sequential testing (see Statistical engine).
- Attribution: it names the changed factor (model, prompt, tools, retrieval, parameters, code) behind a drop.
- Cost-aware: sequential stopping and a hard USD budget on every run.
- Stress testing: seeded fault injection measures robustness, not only correctness.

**Form.** A Python package and CLI named `jerald`, Apache-2.0, local-first, no account needed.

## Users and use cases

Jerald serves people who must know whether an agent got worse and cannot afford a human re-reading transcripts to find out.

**Primary users**

- Developers shipping an agent product who change prompts, tools, or models weekly.
- Small AI teams with no evaluation infrastructure and a monthly API bill they watch.
- Engineers who maintain agents they did not write, such as consultants on a maintenance retainer.

| Use case | Trigger | Command | Output |
| --- | --- | --- | --- |
| PR gate | A prompt, tool, or code change opens a pull request | `jerald check` | Verdict, PR comment, CI exit code |
| Model swap | Moving to a new model or provider | `jerald compare` | Verdict, per-slice effects, cost delta |
| Provider-update canary | A weekly or daily schedule | `jerald canary` | Alert when behavior shifts, with a fingerprint |
| Post-incident search | Quality dropped, cause unknown | `jerald attribute`, `jerald bisect` | Factor effects or the first bad revision |
| Robustness review | Before a release | `jerald stress` | Breaking point and robustness score per fault |

## Scope and non-goals

Version 1 tests agents by running them on tasks Jerald controls, and makes no claim about live production traffic.

**In scope**

- Tool-using, multi-step agents reached over HTTP, CLI, Python, or MCP.
- Statistical verdicts on suites you define, with attribution and canaries.
- Seeded fault injection in sandboxes and mocked tools.
- Local-first operation: SQLite store, no hosted service, no account.

**Non-goals**

- No production telemetry ingestion, tracing UI, or monitoring of live user traffic.
- No predictive or learned failure models. All inference is classical statistics.
- No hosted multi-tenant service in v1.
- No prompt authoring, auto-repair, or optimization of agents.
- No public leaderboard or general benchmark of models.

**Independence.** Jerald shares no code, data schema, brand, or roadmap with Cascaid or any other product. It has its own repository, its own users, and its own success measures.

## Core concepts

Fifteen terms carry the whole design; every command, report, and table in this spec uses them with these meanings.

| Term | Meaning |
| --- | --- |
| Suite | A versioned set of tasks with scorers, tags, and optional fault plans |
| Task | One scenario: input, environment seed, scorers, tags |
| Agent under test (AUT) | The system being tested, reached through an adapter |
| Configuration | A complete description of one AUT version: model, prompt, tools, retrieval, parameters, code revision |
| Arm | One configuration inside a comparison; the baseline arm and the candidate arm |
| Trial | One execution of one task by one arm, with its own seed and recorded trajectory |
| Trajectory | The ordered record of messages, tool calls, results, errors, tokens, and timing for a trial |
| Score | A scorer's output for a trial: pass or fail, or a value from 0 to 1, with evidence |
| Effect (Δ) | Candidate minus baseline mean pass rate, averaged over tasks, in percentage points (pp) |
| Margin (δ) | The smallest drop you care about; default 3 pp |
| MDE | Minimum detectable effect: the smallest effect the planned trials can detect at the chosen power |
| Verdict | REGRESSION, IMPROVEMENT, NO REGRESSION, or INCONCLUSIVE |
| Noise profile | Measured run-to-run variability for a suite and configuration, from calibration |
| Budget | A hard cap on USD, trials, or wall time for one run |
| Canary | A small, programmatically scored suite run on a schedule against a pinned configuration |

## Architecture

Jerald is a pipeline of six layers: inputs, an orchestrator, isolated trial execution, recording and scoring, analysis, and reporting.

&#91;embedded content: architecture · 6 layers, 14 components\]

The statistics engine, highlighted, issues every verdict; after each round the orchestrator asks it whether to spend more trials.

### Execution model

- Trials run in parallel workers with per-provider concurrency caps. Infrastructure errors are retried; agent failures are never retried, because they are the data.
- Arms are interleaved so time of day and provider load affect both equally.
- Each trial's seed derives from the run id, task id, and trial index. Environment seeds are shared across arms.
- Tool responses for hermetic tasks can be recorded once and replayed to cut cost. Model calls are never cached in comparisons, because the model is what is being tested.
- Python 3.11 or later, and Docker for sandboxes, with a local-subprocess fallback that is clearly marked unsafe.

## Suite and config formats

A suite is one YAML file of tasks, a configuration is a short YAML description of one agent version, and the adapter is the only code you write.

### Suite file

```yaml
# suites/support-agent.yaml
suite: support-agent
version: 3
defaults:
  timeout_s: 120
  max_steps: 25
  trials: 3
tasks:
  - id: refund-within-policy
    tags: [refunds, critical]
    input:
      messages:
        - role: user
          content: 'I was charged twice on order 4412. Please refund the duplicate.'
      env:
        seed: 1001
        fixtures: fixtures/orders.sqlite
    scorers:
      - type: state
        check: sql
        query: SELECT COUNT(*) FROM refunds WHERE order_id = 4412
        expect: 1
      - type: trajectory
        tool_called: issue_refund
        args_match: {order_id: 4412}
        tool_not_called: close_account
      - type: efficiency
        max_steps: 12
        max_cost_usd: 0.05
        required: false
  - id: ambiguous-request
    tags: [clarification]
    input:
      messages:
        - role: user
          content: 'Cancel it.'
    scorers:
      - type: trajectory
        asked_clarification: true
```

### Configuration file

Each configuration lists the factors Jerald can vary and attribute. A factor left out is held constant.

```yaml
# jerald.yaml
project: support-agent
adapter:
  type: http
  url: http://localhost:8000/invoke
policy:
  alpha: 0.05
  margin_pp: 3
  min_trials: 3
  max_trials: 30
  budget_usd: 25
  gate:
    critical_slices: [critical]
configs:
  baseline:
    label: main@a1b2c3
    model: example-model-2026-09
    prompt: prompts/system.md
    tools: tools/v12.json
    params: {temperature: 0.2}
    code: git:a1b2c3
  candidate:
    label: pr-481
    model: example-model-2026-09
    prompt: prompts/system.md@pr-481
    tools: tools/v13.json
    params: {temperature: 0.2}
    code: git:HEAD
```

### Adapter contract

The adapter receives one trial and returns one trajectory.

| Direction | Field | Meaning |
| --- | --- | --- |
| Request | `task_id`, `trial_id` | Identifiers for the task and this trial |
| Request | `messages`, `env.seed` | Task input and the environment seed |
| Request | `overrides` | Factors to vary for this arm, such as `model` |
| Response | `final_message` | The agent's last message |
| Response | `trajectory[]` | Steps with `type`, `name`, `args`, `result`, `error`, `t_start`, `t_end` |
| Response | `usage` | `input_tokens`, `output_tokens`, `cost_usd` |
| Response | `model_reported` | The model id the provider says served the call |

Model and tool calls must go through two environment URLs so Jerald can count cost and inject faults. Agents that cannot do this still support outcome-only testing.

- `JERALD_MODEL_BASE_URL`: an OpenAI- or Anthropic-compatible proxy that records usage and applies model faults.
- `JERALD_TOOL_BASE_URL`: a proxy for HTTP and MCP tools that applies tool faults.
- Other adapter types: `cli` (JSON on stdin and stdout), `python` (a class with `run(task, config, seed)`), and `mcp`.

## Scorers

Programmatic scorers decide the gate by default, because a judge model that drifts cannot be used to measure drift.

A task passes when every scorer marked `required` (the default) passes. Each scorer returns pass or fail, a value from 0 to 1, and evidence such as the matching trajectory step.

| Family | Scorer | What it checks |
| --- | --- | --- |
| Outcome | `exact`, `regex`, `json_schema` | The final message matches a string, pattern, or schema |
| Outcome | `python`, `shell` | A function or command run against the result returns success |
| Outcome | `state` | Sandbox state after the run: a SQL query, a file's content, or the mock HTTP call log |
| Trajectory | `tool_called`, `tool_not_called` | A tool was or was not used |
| Trajectory | `tool_order` | Partial-order constraints between tool calls |
| Trajectory | `args_match` | A JSONPath predicate holds on a call's arguments |
| Trajectory | `no_loops` | The same tool and arguments do not repeat more than k times |
| Trajectory | `forbidden_effects` | No writes outside allowed paths and no calls to unlisted hosts |
| Trajectory | `asked_clarification` | The agent asked a question when the request was ambiguous |
| Efficiency | `max_steps`, `max_cost_usd`, `max_latency_s` | Resource limits per trial; reported, and gated only if marked `required` |
| Judge | `rubric` | A pinned judge model scores a rubric; kept off the gate unless calibrated |

**Judge rules.** Pin the judge to a dated model snapshot at temperature 0. Calibrate it on at least 50 human-labeled trials and store the agreement rate. A judge scorer may join the gate only when `calibrated: true` and agreement is at least 0.9; otherwise it appears in reports as a secondary metric.

## Statistical engine

Jerald decides with a paired, task-clustered comparison and stops as soon as the evidence is sufficient; if the budget runs out first, it says INCONCLUSIVE instead of guessing.

### Why one run per task is not enough

A study of 60,000 agent trajectories on SWE-Bench-Verified found that single-run pass@1 varied by 2.2 to 6.0 percentage points depending on which run was picked, with standard deviations above 1.5 points even at temperature 0 ([Bjarnason et al., 2026](https://arxiv.org/abs/2602.07150)). Its power analysis puts the need at about 9 runs per agent to detect a 2-point improvement and about 36 to detect 1 point, at the paper's median variance, 80% power, and p < 0.05. Those runs were whole 500-task benchmark passes, so a smaller suite is noisier.

### Prior art

AgentAssay proposes PASS, FAIL, and INCONCLUSIVE verdicts, sequential testing that cut trials by 78% in its experiments, and behavioral fingerprints ([Bhardwaj, 2026](https://arxiv.org/abs/2603.02601)). Jerald adopts these ideas openly. Its additions are task-clustered paired inference, a measured noise profile per suite, factor attribution, and fault-injection curves, each with published error rates (see Validation plan).

### Estimand

```latex
\Delta = \frac{1}{N}\sum_{i=1}^{N}\left(\hat{p}_i^{C} - \hat{p}_i^{B}\right)
```

Here p-hat is a task's pass rate across its trials, B is the baseline arm, C is the candidate arm, and N is the number of tasks. Tasks are the unit of replication; more trials per task only reduce within-task noise.

### Procedure

1. **Calibrate** once per suite and configuration. Run 2n trials of the baseline, split them at random many times into two pseudo-arms, and record the null distribution of Δ. This gives the noise standard deviation and an empirical false-positive rate. A temporal A/A, the same configuration rerun a week later, adds provider drift to the noise profile.
2. **Plan.** Simulate from pilot per-task pass rates to find the trials needed for a target MDE at 80% power, or the MDE a given budget buys.
3. **Run in rounds.** Round 0 gives every task 3 trials per arm, interleaved in random order with shared environment seeds. Later rounds add trials where variance is highest. Tasks that fail in every trial of both arms are frozen and reported as dead; tasks that always pass get few trials until a failure appears.
4. **Estimate.** After each round, compute a confidence interval (CI) for Δ with a two-level paired bootstrap: resample tasks, then trials within each task and arm, 10,000 times. Spend alpha across a planned number of looks (default 5) with a Lan-DeMets O'Brien-Fleming-type function.
5. **Decide** with the verdict rule below, and stop on a decisive verdict, the budget, or the trial cap.

### Verdict rule

With CI \[L, U\] for Δ and margin δ:

| Verdict | Condition | Exit code | Meaning |
| --- | --- | --- | --- |
| REGRESSION | U < −δ | 1 | The candidate is worse by more than the margin |
| IMPROVEMENT | L > +δ | 0 | The candidate is better by more than the margin |
| NO REGRESSION | L > −δ, and not IMPROVEMENT | 0 | A drop larger than the margin is ruled out |
| INCONCLUSIVE | None of the above when the budget ends | 2 | More trials or a larger margin are needed; the report states the MDE achieved |

### Secondary results

- **Reliability.** Per task, pass^k is estimated without bias from c passes in n trials, and pass@k as 1 − C(n−c, k) / C(n, k). Reports show pass@1, pass^3, and worst-of-n.
- **Cost, tokens, steps, latency.** Paired log-ratio bootstrap. An efficiency flag is raised when the lower bound of the median cost ratio exceeds 1.15 (configurable).
- **Slices.** Per-tag effects use Holm correction across slices. Any slice listed in `critical_slices` that shows REGRESSION fails the whole check.

```latex
\widehat{\mathrm{pass}^{k}}_i = \binom{c_i}{k} \Big/ \binom{n_i}{k}
```

### Known limits

- The bootstrap undercovers with fewer than about 30 tasks; below that Jerald switches to a sign-flip permutation test and warns.
- Trials are assumed independent given their seeds. Provider load changes break this; interleaving and the temporal A/A reduce it, and the noise profile reports what remains.
- Alpha spending with bootstrap intervals is validated by simulation, not proven; the false-positive experiment in the validation plan is the check.

## Attribution

Jerald names the cause of a change by swapping one factor at a time between baseline and candidate and judging each swap with the same verdict engine.

**Factors.** A configuration has six factors: model, prompt, tools, retrieval, parameters, and code revision. A provider-side change to the model behind a stable name is not visible as a changed factor, so canaries handle it separately.

| Situation | Method | Arms | Output |
| --- | --- | --- | --- |
| One factor changed | None needed | 2 | Direct verdict |
| Two or three factors changed | Full factorial | 4 to 8 | Main effects and interactions, each with a CI |
| Four or more factors changed (k) | One-factor swaps plus all-but-one swaps | 2k + 2 | Main effects; an interaction warning when the swaps do not add up to the total effect |
| Ordered history of commits or configs | Bisect | about log2(n) steps | The first bad revision, with confidence |

### Bisect

`jerald bisect <good> <bad>` binary-searches an ordered list of revisions. At each step it runs the verdict engine against the known-good revision: REGRESSION marks the step bad, NO REGRESSION marks it good, and INCONCLUSIVE adds trials up to a per-step cap (default 2 times the planned trials). A step still unresolved after the cap is marked uncertain and its two neighbors are tested. The search assumes one regression and monotone degradation, and it warns when a later revision looks better than an earlier bad one.

### Provider drift and canaries

When no factor changed but behavior did, the cause is likely on the provider side. Jerald records the model id the provider reports, response headers, and any system fingerprint, and runs a small canary suite on a schedule against a pinned configuration.

- **Behavioral fingerprint.** A vector per canary run: pass rate per category, format-validity rate, refusal rate, output-length quantiles, tool-call-order frequencies, and latency quantiles.
- **Comparison.** The same verdict engine per category, plus a permutation test on the energy distance between the current fingerprint window and a reference window of the previous four runs.
- **Slow drift.** A CUSUM on the aggregate pass rate, with control limits taken from the noise profile.
- **Alerting.** An alert needs two consecutive flagged runs, or one flagged run confirmed by an automatic rerun within six hours.
- **Evidence.** The alert reports a date window for the change, not a single instant, because canaries only bracket when it happened.

## Fault injection and stress testing

Jerald measures robustness by degrading an agent's tools, model calls, retrieval, and environment on a fixed schedule and recording where the pass rate breaks.

Faults act only inside the sandbox, through the model and tool proxies or through mocked tools. Every fault is seeded per trial, logged in the trajectory, and repeatable. Severity runs from 0 (no fault) to 3; the values below are tunable defaults, not measured thresholds.

| Layer | Fault | Severity 1 | Severity 2 | Severity 3 |
| --- | --- | --- | --- | --- |
| Tool | Added latency | +1 s | +5 s | +20 s |
| Tool | Transient error (HTTP 429 or 503) | 10% of calls | 30% | 60% |
| Tool | Timeout | 5% of calls | 15% | 40% |
| Tool | Malformed payload (truncated JSON) | 5% of calls | 15% | 30% |
| Tool | Schema drift (renamed field or changed type) | 1 field | 3 fields | Every field of one tool |
| Tool | Partial results (items dropped) | 20% dropped | 50% | 80% |
| Model | Provider errors (429, 529) | 5% of calls | 20% | 50% |
| Model | Context limit reduced | 75% of normal | 50% | 25% |
| Model | Output token cap | 75% of normal | 50% | 25% |
| Model | Substitution (positive control) | One tier smaller | Two tiers | Smallest available |
| Retrieval | Distractor documents | 1 irrelevant in the top results | Half irrelevant | None relevant |
| Retrieval | Stale documents | 10% outdated | 30% | 60% |
| Environment | Missing configuration | One optional variable | One required variable | Several required |

### Metrics

- **Robustness curve.** Pass rate against severity 0 to 3, with CIs from the verdict engine.
- **Breaking point.** The lowest severity at which the effect against severity 0 is a REGRESSION.
- **Robustness score.** Area under the normalized curve, from 0 to 1.
- **Retry amplification.** Extra model calls and cost per injected fault.
- **Recovery rate.** The share of trials that still finish after a transient fault.

### Extending

A fault is a small Python plugin with `apply(request, rng, severity)`. Tools that are not reachable through the proxy can expose fault points with a decorator. Model substitution and temperature increases double as positive controls: known degradations the validation plan uses to measure detection power.

### Safety rule

The fault proxy refuses to forward to hosts outside the task's allowlist, so injected failures never reach live third-party services.

## CLI reference

`jerald check` is the command most people run; every other command exists to make its verdict trustworthy.

| Command | Purpose | Key flags |
| --- | --- | --- |
| `jerald init` | Scaffold `jerald.yaml`, a starter suite, and the local store | `--adapter <type>` |
| `jerald doctor` | Verify Docker, API keys, adapter reachability, proxy routing, and rate limits | `--verbose` |
| `jerald baseline` | Save, list, or show a named baseline (a configuration plus its per-task results) | `save`, `list`, `show` |
| `jerald calibrate` | Measure the noise profile with split-half and temporal A/A | `--suite`, `--config`, `--trials` |
| `jerald plan` | Estimate trials and cost for a target MDE, or the MDE a budget buys | `--mde-pp`, `--power`, `--alpha`, `--budget-usd` |
| `jerald run` | Run one configuration and store its trials | `--config`, `--trials`, `--seed` |
| `jerald compare` | Compare two arms with the sequential verdict engine | `--margin-pp`, `--alpha`, `--max-trials`, `--budget-usd`, `--fixed-n` |
| `jerald check` | CI wrapper: compare the working tree with a named baseline and set the exit code | `--baseline`, `--budget-usd`, `--format` |
| `jerald attribute` | Run factorial or one-factor swaps between two configurations | `--factors`, `--budget-usd` |
| `jerald bisect` | Find the first bad revision in an ordered range | `--range`, `--per-step-cap` |
| `jerald canary` | Run the canary suite, update its time series, and evaluate alerts | `--suite`, `--alert-webhook` |
| `jerald stress` | Run fault plans across severities and draw robustness curves | `--plan`, `--severities` |
| `jerald report` | Render a stored run as Markdown, JSON, JUnit XML, or HTML | `--run-id`, `--format` |
| `jerald capture` | Turn conversations you supply into draft tasks for human review; never edits a suite on its own | `--from` |
| `jerald replay` | Re-execute a stored run from its manifest | `--run-id` |
| `jerald purge` | Delete a run and its artifacts | `--run-id` |

**Global flags:** `--config`, `--out`, `--seed`, `--parallel`, `--dry-run` (print the plan and cost range without spending), and `--yes`.

### Exit codes

| Code | Meaning |
| --- | --- |
| 0 | No regression, or improvement |
| 1 | Regression |
| 2 | Inconclusive |
| 3 | Configuration or usage error |
| 4 | Infrastructure failure, including a budget guard that stops the run before any valid result |

### A typical first session

```bash
jerald init --adapter http
jerald calibrate --suite support-agent --trials 20
jerald plan --mde-pp 5 --power 0.8 --budget-usd 25
jerald baseline save main
jerald check --baseline main --budget-usd 15
jerald attribute main pr-481
```

## Data model and reproducibility

Every verdict can be traced to its trials, and every run can be replayed from a manifest.

Storage is a local SQLite database (WAL mode) for metadata and scores, content-addressed files under `.jerald/artifacts/` for full trajectories and tool payloads, and Parquet exports for analysis.

| Table | Holds |
| --- | --- |
| `suites`, `tasks` | Suite versions with content hashes; task specs and tags |
| `configs` | Factor values, a configuration hash, a label, and every `model_reported` string seen |
| `runs` | Kind (run, compare, check, canary, stress, bisect), start and end time, policy, budget, and manifest |
| `trials` | Run, task, arm, seed, order index, status, cost, tokens, latency, error |
| `steps` | Trial, index, type, name, arguments, result reference, error, timing, tokens |
| `scores` | Trial, scorer, pass flag, value, evidence |
| `verdicts` | Run, scope (overall, slice, task, metric), Δ, CI bounds, verdict, details |
| `noise_profiles` | Suite and configuration hashes, noise standard deviation, false-positive rate at alpha, date |
| `canary_points` | Series, run, time, fingerprint, aggregate pass rate |

### Reproducibility manifest

Each run writes a manifest with the Jerald version, suite hash, configuration hashes, container image digest, dependency lock hash, seeds, the model ids the provider reported, start and end times, and the policy in force. `jerald replay` reruns with the same seeds. Environment behavior replays exactly; model sampling may differ, and the report says so.

### Retention and redaction

Redaction patterns run before anything is stored. Retention is set per project (default 90 days for trajectories, indefinite for scores and verdicts), and `jerald purge` removes a run and its artifacts.

## Reports and CI integration

Every report leads with the verdict and the effect size, then shows what flipped and why, and ends with the noise profile and a replay command.

**Formats:** terminal summary, Markdown for PR comments, JSON, JUnit XML (one test case per slice), and a self-contained HTML report.

### Example PR comment (illustrative numbers)

```markdown
### Jerald: REGRESSION (pr-481 vs main@a1b2c3)

Pass rate 84.2% to 77.9%. Effect -6.3 pp, 95% CI -9.8 to -3.4, margin 3 pp.
Trials 1,140 of 1,800 budgeted. Cost $11.42 of $25.00. Stopped early: yes.

| Slice | Baseline | Candidate | Effect (pp) | Verdict |
| --- | --- | --- | --- | --- |
| refunds (critical) | 91.7% | 80.0% | -11.7 | REGRESSION |
| clarification | 70.0% | 71.7% | +1.7 | No regression |

Flipped tasks: refund-within-policy (100% to 53%).
First divergence: step 3. Baseline calls lookup_order; candidate calls issue_refund.
Efficiency: median cost +18% (CI +9% to +27%), flagged.
Attribution (prompt and tools changed): prompt -5.9 pp, tools -0.6 pp.
Noise profile: suite SD 1.4 pp; false-positive rate 4.6% at alpha 0.05 (calibrated 2026-10-02).
Replay: jerald replay --run-id run_01J...
```

### GitHub Action (planned)

```yaml
name: agent-regression
on: pull_request
jobs:
  jerald:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install jerald
      - run: jerald check --baseline main --budget-usd 15 --format md > jerald.md
        env:
          MODEL_API_KEY: ${{ secrets.MODEL_API_KEY }}
      - uses: jerald/comment-action@v1
        with:
          file: jerald.md
```

The action posts the Markdown as a PR comment and maps exit code 2 to a warning unless `fail-on-inconclusive` is set.

### Alerts

Canary and check failures can post to a Slack or generic webhook with a JSON body holding the verdict, effect, CI, flagged slices, date window, and report link.

## Security, privacy, and cost controls

Jerald runs untrusted agent code and handles transcripts that may contain personal data, so isolation, redaction, and spending limits are defaults, not options.

- **Secrets.** Read from environment variables only. They are never written to the store, reports, or trajectories, and known key patterns are redacted from captured payloads.
- **Sandbox.** Each trial runs in its own container with no network except the proxy allowlist. Fixture files mount read-only unless the task declares writes.
- **Privacy.** Local-first with no telemetry. Trajectories can contain personal data, so redact before storing and set retention. If trials process personal data of people in the Philippines, follow the Data Privacy Act (purpose, consent, retention, security) and confirm the details with counsel.
- **Provider terms.** Canaries and large comparison runs are automated usage. Respect each provider's usage policies and rate limits, cap concurrency per provider, and read the terms before publishing any public tracker.
- **Cost controls.** A hard `budget_usd` is enforced before every trial using a cost estimate from earlier trials. Runs record why they stopped. `--dry-run` shows the plan and a cost range, and per-provider monthly caps live in `jerald.yaml`.
- **Fault safety.** Faults apply only to sandboxed or mocked tools, and the proxy refuses hosts outside the allowlist.
- **Supply chain.** Pinned and hash-locked dependencies, signed releases, and a software bill of materials from the first public release.

## Validation plan

Jerald is only credible if its own error rates are measured and published, so the validation plan is part of the product.

**Reference agents** (3 to 5, built in-house with 40 to 80 tasks each, using public data where licenses allow):

- A tool-using support agent over SQLite fixtures.
- A coding agent that patches a small repository, scored by unit tests.
- A retrieval agent answering questions over local documents.
- A multi-step data agent that turns CSV files into answers.

**Comparison baselines:** a naive threshold on the difference of single-run scores, a fixed-n paired bootstrap, and Jerald's sequential engine.

| Experiment | Method | Target (a hypothesis to test) |
| --- | --- | --- |
| E1 False positives | 1,000 simulated and 20 live A/A comparisons per agent | False-positive rate no higher than alpha plus 1 pp at alpha 0.05 |
| E2 Power curve | Injected degradations of known size at five severities: smaller model, higher temperature, truncated context, broken tool schema, prompt edits | At least 80% detection at the planned MDE; publish the full curve |
| E3 Sequential efficiency | Trials to a decision for each baseline at equal power | At least 30% fewer trials than fixed-n |
| E4 Attribution | Two or three factors changed with a known culprit | Correct culprit in at least 90% of cases |
| E5 Bisect | A seeded regression at a known commit in 32-commit histories | Exact commit in at least 90% of cases |
| E6 Canary sensitivity | A silent model swap behind a local proxy at a random date | Detected within 2 runs in at least 90% of cases |
| E7 Fault monotonicity | Pass rate against severity for each fault type | Non-increasing for at least 95% of fault types |
| E8 Reproducibility | Replay from manifests | Environment outputs identical; model variance reported |

Targets are goals set before the experiments, not claims. A target that fails is reported as failed, and the related feature is cut or relabeled. Results, raw trials, and scripts are published in the repository under `/validation`.

## Roadmap

Fifteen weeks take Jerald from a single-agent runner to a validated v0.1, and no milestone starts until the previous gate has passed.

&#91;embedded content: roadmap · 7 milestones, 15 weeks\]

Milestone M1, highlighted, is the statistical core; if its gate fails, the kill criteria apply and the project changes method or stops.

## Distribution and business hypotheses

Jerald earns trust through published validation and a one-command CI gate; revenue is a later question, and everything about it below is untested.

**Positioning line:** the statistical regression gate for AI agents.

### Landscape

| Tool | What it does | What Jerald adds |
| --- | --- | --- |
| [EvalView](https://pypi.org/project/evalview/) | Golden-baseline diffs of agent trajectories, PR comments, pass@k runs, canaries, record and replay; Apache-2.0, version 0.8.1 (July 2026) | Task-clustered paired statistics, a measured noise profile, factor attribution, fault-injection curves |
| [AgentAssay](https://arxiv.org/abs/2603.02601) | Research framework with three-valued verdicts, sequential testing, behavioral fingerprints, adaptive budgets | Published error rates on reference agents, bisect and factorial attribution, a simple adoption path |
| DeepEval, Promptfoo, Inspect AI | Metric libraries, YAML CI gating, and an agent evaluation framework | A degradation-first workflow built around baselines, noise, and verdicts |

Only the EvalView and AgentAssay entries were checked against their primary pages; verify the rest, and the "What Jerald adds" column, against current documentation before relying on them.

### Distribution

- Open source under Apache-2.0, with the local-first CLI and a GitHub Action as the main channel.
- A public canary tracker: a small public suite scored weekly across providers, with confidence intervals and raw data. Hypothesis: it earns citations and links. Risk: provider terms and recurring cost.
- First users: small AI teams and agent maintainers, offered free pilots in exchange for a case study with numbers.

### Revenue hypotheses

- A hosted scheduler with alert history and team views.
- Private canary suites run on a schedule.
- Services: suite design, calibration, and maintenance retainers.

No prices are set; pricing follows pilot conversations.

## Risks, kill criteria, and open questions

The largest risk is that the basic layer already exists, so Jerald must win on measured rigor and attribution, and it should stop if its own validation says it does not.

| Risk | Mitigation |
| --- | --- |
| Existing tools add statistics and attribution | Publish validation early so claims are checkable; keep the attribution and fault-curve work as the differentiator |
| Repeated trials cost too much for small teams | Sequential stopping, programmatic scorers, cheap canary tiers, and `plan` showing cost before any spend |
| Provider load and nondeterminism exceed what interleaving absorbs | Temporal A/A in calibration, randomized interleaving, and a noise profile in every report |
| Suites rot as the agent changes | `capture` drafts tasks for review, and a suite health report flags dead and saturated tasks |
| Agents that cannot route calls through the proxies | An outcome-only mode, documented adapters, and examples for common frameworks |
| Misuse: loose margins or peeking at results | Safe defaults, built-in sequential design, and INCONCLUSIVE as a first-class verdict |
| Provider terms limit automated testing or a public tracker | Read terms before launch, cap rates, and start private |

### Kill criteria

Decide these now, so the project does not talk itself into continuing:

- If E1 cannot hold the false-positive rate within target on three reference agents by the end of milestone M1, stop and revisit the method.
- If E3 shows no efficiency gain over fixed-n by M2, drop the sequential claim and keep fixed-n mode.
- If fewer than three outside teams run Jerald on real agents by the end of M5, treat it as a personal and services tool, not a product.
- If a competitor ships paired testing plus attribution before M3, narrow to canaries and fault curves, or stop.

### Open questions

- **Name.** PyPI returned 404 for `jerald` on 2026-10-05, and a web search found no agent tool with that name. GitHub, npm, and trademark were not checked.
- **Default margin.** Keep 3 pp, or derive it from each suite's noise profile?
- **Judge scores.** Should a calibrated judge ever be allowed to gate?
- **First adapters.** Which agent frameworks come first after HTTP and CLI?
- **Public tracker.** Needs a provider-terms review and a cost estimate before commitment.
- **License.** Apache-2.0, as EvalView uses, or MIT?
