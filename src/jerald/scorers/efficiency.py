from __future__ import annotations

from collections.abc import Sequence

from jerald.adapters.base import Step, TrialResult
from jerald.scorers.base import ScoreResult


def _latency_s(steps: Sequence[Step]) -> float:
    if not steps:
        return 0.0
    return max(s.t_end for s in steps) - min(s.t_start for s in steps)


def efficiency(
    *,
    max_steps: int | None = None,
    max_cost_usd: float | None = None,
    max_latency_s: float | None = None,
    required: bool = True,
):
    if max_steps is None and max_cost_usd is None and max_latency_s is None:
        raise ValueError(
            "efficiency scorer needs at least one of max_steps, max_cost_usd, max_latency_s"
        )

    class _Efficiency:
        def score(self, trial: TrialResult) -> ScoreResult:
            failures: list[str] = []

            actual_steps = len(trial.trajectory)
            if max_steps is not None and actual_steps > max_steps:
                failures.append(f"{actual_steps} steps exceeds max_steps={max_steps}")

            if max_cost_usd is not None and trial.usage.cost_usd > max_cost_usd:
                failures.append(
                    f"cost_usd={trial.usage.cost_usd} exceeds max_cost_usd={max_cost_usd}"
                )

            if max_latency_s is not None:
                latency = _latency_s(trial.trajectory)
                if latency > max_latency_s:
                    failures.append(f"latency_s={latency} exceeds max_latency_s={max_latency_s}")

            passed = not failures
            evidence = "within limits" if passed else "; ".join(failures)
            return ScoreResult(
                scorer_id="efficiency",
                passed=passed,
                value=1.0 if passed else 0.0,
                evidence=evidence,
                required=required,
            )

    return _Efficiency()
