from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np

VerdictLabel = Literal["REGRESSION", "IMPROVEMENT", "NO_REGRESSION", "INCONCLUSIVE"]


@dataclass(frozen=True)
class Verdict:
    label: VerdictLabel
    effect_pp: float
    ci_low_pp: float
    ci_high_pp: float
    margin_pp: float


def compare(
    baseline_scores: Mapping[str, Sequence[bool]],
    candidate_scores: Mapping[str, Sequence[bool]],
    margin_pp: float = 3.0,
    alpha: float = 0.05,
    n_bootstrap: int = 10_000,
    seed: int = 0,
) -> Verdict:
    if baseline_scores.keys() != candidate_scores.keys():
        raise ValueError("baseline_scores and candidate_scores must cover the same tasks")

    task_ids = list(baseline_scores.keys())
    baseline_trials = [np.asarray(baseline_scores[t], dtype=float) for t in task_ids]
    candidate_trials = [np.asarray(candidate_scores[t], dtype=float) for t in task_ids]
    n_tasks = len(task_ids)

    baseline_rates = np.array([trials.mean() for trials in baseline_trials])
    candidate_rates = np.array([trials.mean() for trials in candidate_trials])
    effect_pp = float(np.mean(candidate_rates - baseline_rates)) * 100.0

    rng = np.random.default_rng(seed)
    bootstrap_deltas = np.empty(n_bootstrap)
    for b in range(n_bootstrap):
        task_idx = rng.integers(0, n_tasks, size=n_tasks)
        per_task_delta = np.empty(n_tasks)
        for i, ti in enumerate(task_idx):
            b_resample = rng.choice(baseline_trials[ti], size=baseline_trials[ti].size, replace=True)
            c_resample = rng.choice(candidate_trials[ti], size=candidate_trials[ti].size, replace=True)
            per_task_delta[i] = c_resample.mean() - b_resample.mean()
        bootstrap_deltas[b] = per_task_delta.mean()
    bootstrap_deltas_pp = bootstrap_deltas * 100.0

    ci_low_pp, ci_high_pp = np.percentile(
        bootstrap_deltas_pp, [100 * alpha / 2, 100 * (1 - alpha / 2)]
    )
    ci_low_pp, ci_high_pp = float(ci_low_pp), float(ci_high_pp)

    if ci_high_pp < -margin_pp:
        label: VerdictLabel = "REGRESSION"
    elif ci_low_pp > margin_pp:
        label = "IMPROVEMENT"
    elif ci_low_pp > -margin_pp:
        label = "NO_REGRESSION"
    else:
        label = "INCONCLUSIVE"

    return Verdict(
        label=label,
        effect_pp=effect_pp,
        ci_low_pp=ci_low_pp,
        ci_high_pp=ci_high_pp,
        margin_pp=margin_pp,
    )
