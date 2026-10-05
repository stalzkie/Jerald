# Jerald Spec — External Claims Verification

**Date checked:** 2026-10-05
**Source document:** `D:\Jerald\Jerald Agent Degradation Harness – Spec.md`

## Summary

Of the claims the spec explicitly flagged as unverified, two check out cleanly against primary sources (EvalView on PyPI, AgentAssay on arXiv, and the Bjarnason et al. statistics paper — all CONFIRMED in detail, including the specific numbers), and the PyPI 404 for `jerald` still holds as of this check. The one place the spec's citations need correction is the three-tool summary row for DeepEval, Promptfoo, and Inspect AI: each one-phrase label (metric library / YAML CI gating / agent evaluation framework) undersells or narrows what the current project actually is — the spec's own caveat ("verify the rest... before relying on them") was warranted and the row should be revised. No arXiv ID in the spec is fabricated or points to an unrelated paper — both 2603.02601 (AgentAssay) and 2602.07150 (Bjarnason et al.) resolve to real, matching papers. Overall the spec's external citations are unusually trustworthy for a forward-dated document; the only fix needed is the Landscape table's third row.

---

## 1. EvalView (PyPI package)

**Claim as stated:** "Golden-baseline diffs of agent trajectories, PR comments, pass@k runs, canaries, record and replay; Apache-2.0, version 0.8.1 (July 2026)"

**Verdict:** CONFIRMED

**Primary source checked:** https://pypi.org/project/evalview/

**Finding:** The PyPI page shows EvalView as Apache-2.0 licensed, current version 0.8.1 released July 26, 2026. It is described as a snapshot-testing framework for AI agents: golden-baseline diffing of tool-call trajectories, PR comments in CI/CD showing diffs/cost/latency, pass@k-style multi-variant baseline testing, cassette-based record-and-replay, and canary/model-drift monitoring with Slack alerts. Every element the spec attributes to EvalView is present on the actual package page; the spec's description is accurate.

## 2. AgentAssay (arXiv paper)

**Claim as stated:** "AgentAssay proposes PASS, FAIL, and INCONCLUSIVE verdicts, sequential testing that cut trials by 78% in its experiments, and behavioral fingerprints (Bhardwaj, 2026)." Repeated consistently in the Landscape table ("three-valued verdicts, sequential testing, behavioral fingerprints, adaptive budgets").

**Verdict:** CONFIRMED

**Primary source checked:** https://arxiv.org/abs/2603.02601

**Finding:** The paper is real: "AgentAssay: Token-Efficient Regression Testing for Non-Deterministic AI Agent Workflows," by Varun Pratap Bhardwaj — matching the spec's "Bhardwaj, 2026" citation. The abstract explicitly describes "stochastic three-valued verdicts (PASS/FAIL/INCONCLUSIVE) grounded in hypothesis testing," reports that its sequential test (SPRT) "reduces trials by 78%," and describes "behavioral fingerprinting that maps execution traces to compact vectors, enabling multivariate regression detection." All three claimed elements are present verbatim in spirit. The two places this claim appears in the spec (Statistical engine → Prior art, and the Landscape table) are consistent with each other and with the source. Note: the task brief also mentioned "Core concepts" and "Validation plan" sections repeating this claim — on inspection, those sections only reuse generic terms Jerald itself defines (e.g., the INCONCLUSIVE verdict, "published error rates") without re-citing AgentAssay's specific numbers, so there is no inconsistency to flag there.

## 3. DeepEval, Promptfoo, Inspect AI (Landscape table, row 3)

**Claim as stated:** "Metric libraries, YAML CI gating, and an agent evaluation framework" (respectively).

**Verdict:** PARTIALLY CONFIRMED — each label is too narrow for what the tool currently is.

**Primary sources checked:** https://github.com/confident-ai/deepeval , https://github.com/promptfoo/promptfoo , https://github.com/UKGovernmentBEIS/inspect_ai

**Finding:**
- **DeepEval** is not simply a "metric library." Its own README calls it "a simple-to-use, open-source LLM evaluation framework... similar to Pytest but specialized for unit testing LLM apps," with CI/CD integration, agentic metrics (task completion, tool correctness, step efficiency), synthetic dataset generation, and full-trajectory tracing. Metrics are one component of a broader test framework, not the whole product.
- **Promptfoo** is not accurately summarized as "YAML CI gating." Its README positions it as an LLM evaluation *and* red-teaming/security-scanning platform ("Test your prompts, agents, and RAGs" plus "red teaming/pentesting/vulnerability scanning for AI"); CI/CD automation is one supported feature among several, not its defining characteristic, and the security/red-team half is omitted entirely from the spec's label.
- **Inspect AI** is not precisely "an agent evaluation framework." Per its README it is a general framework for LLM evaluations (prompt engineering, tool usage, multi-turn dialog, model-graded evaluation) built by the UK AI Security Institute; agent evaluation is one supported use case, not the framework's defining scope.

This is exactly the row the spec flagged as unchecked ("verify the rest... against current documentation before relying on them"), and the flag was warranted — all three one-phrase labels should be broadened or corrected before the spec is relied upon.

## 4. Bjarnason et al., 2026 — statistics paper (Statistical engine → "Why one run per task is not enough")

**Claim as stated:** A study of 60,000 agent trajectories on SWE-Bench-Verified found single-run pass@1 varied by 2.2 to 6.0 pp depending on which run was picked, with SDs above 1.5 points even at temperature 0; its power analysis implies ~9 runs per agent to detect a 2-point improvement and ~36 runs to detect 1 point, at 80% power and p < 0.05.

**Verdict:** CONFIRMED (all four specific numbers)

**Primary sources checked:** https://arxiv.org/abs/2602.07150 , https://arxiv.org/html/2602.07150 , https://arxiv.org/pdf/2602.07150

**Finding:** The paper is real: "On Randomness in Agentic Evals," by Bjarni Haukur Bjarnason, André Silva, and Martin Monperrus — matching the "Bjarnason et al., 2026" citation. The abstract confirms "60,000 agentic trajectories on SWE-Bench-Verified," "single-run pass@1 estimates vary by 2.2 to 6.0 percentage points depending on which run is selected," and "standard deviations exceeding 1.5 percentage points even at temperature 0." The full text's power-analysis section states "Detecting a 2% improvement at p<0.05 with 80% power requires approximately 9 runs per agent under test" and "detecting a 1% improvement requires 36 runs," at the paper's median variance (σ≈1.5%) — matching the spec's "~9 runs... ~36 runs... at the paper's median variance, 80% power, and p < 0.05" exactly. Every specific figure in this claim checks out against the primary text, not just a secondary summary.

## 5. PyPI name check for `jerald`

**Claim as stated:** "PyPI returned 404 for `jerald` on 2026-10-05."

**Verdict:** CONFIRMED (re-checked live on 2026-10-05)

**Primary source checked:** https://pypi.org/pypi/jerald/json (PyPI's JSON API; the HTML page at https://pypi.org/project/jerald/ returned a bot-protection "Client Challenge" interstitial rather than a clean rendered 404, so the JSON API was used as the unambiguous check)

**Finding:** The JSON API returned HTTP 404 Not Found for `jerald`, confirming no package of that name currently exists on PyPI. The spec's claim still holds as of today. (Minor process note: the human-facing PyPI project page did not render a clean "404" visual for the fetch tool — it served a bot-detection challenge page instead — but the authoritative JSON endpoint is unambiguous and matches the spec's claim.)

## 6. Other checkable claims scanned for

The rest of the spec's factual content is either (a) Jerald's own design decisions (not external claims), (b) illustrative/placeholder data explicitly marked as such ("illustrative numbers," "(planned)" GitHub Action), or (c) generic, well-established statistical/legal references rather than specific citations needing primary-source lookup:

- **Lan-DeMets O'Brien-Fleming-type alpha-spending function** (Statistical engine → Procedure, step 4): a real, standard group-sequential-testing method (Lan & DeMets, 1983); the spec uses it correctly as a generic technique, not as a specific unverified citation.
- **pass^k unbiased estimator formula** `C(c,k)/C(n,k)` and pass@k as `1 − C(n−c,k)/C(n,k)` (Secondary results): this matches the well-known unbiased pass@k estimator from Chen et al. ("Evaluating Large Language Models Trained on Code," 2021); correctly stated.
- **Philippines Data Privacy Act** (Security, privacy, and cost controls): Republic Act No. 10173 is a real law whose core principles (purpose, consent, retention, security) match the spec's gloss; the spec correctly caveats "confirm the details with counsel" rather than asserting detailed compliance claims, so no correction is needed.
- No other specific version numbers, dates, or quantitative statistics tied to an external source were found elsewhere in the document. The GitHub Action YAML block and `jerald/comment-action@v1` are explicitly marked "(planned)" and are Jerald's own hypothetical future artifacts, not third-party claims.
