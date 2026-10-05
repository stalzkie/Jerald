import pytest

from jerald.analysis.compare import compare


def test_compare_raises_when_task_sets_differ() -> None:
    baseline = {"task_a": [True, True], "task_b": [True, False]}
    candidate = {"task_a": [True, False]}
    with pytest.raises(ValueError):
        compare(baseline, candidate)


def _all_tasks(value: bool, n_tasks: int = 10, n_trials: int = 5) -> dict[str, list[bool]]:
    return {f"task_{i}": [value] * n_trials for i in range(n_tasks)}


def test_compare_reports_improvement_when_every_task_flips_to_passing() -> None:
    verdict = compare(
        baseline_scores=_all_tasks(False),
        candidate_scores=_all_tasks(True),
        margin_pp=3.0,
        n_bootstrap=200,
        seed=0,
    )
    assert verdict.label == "IMPROVEMENT"
    assert verdict.effect_pp == 100.0
    assert verdict.ci_low_pp == 100.0
    assert verdict.ci_high_pp == 100.0


def test_compare_reports_regression_when_every_task_flips_to_failing() -> None:
    verdict = compare(
        baseline_scores=_all_tasks(True),
        candidate_scores=_all_tasks(False),
        margin_pp=3.0,
        n_bootstrap=200,
        seed=0,
    )
    assert verdict.label == "REGRESSION"
    assert verdict.effect_pp == -100.0
    assert verdict.ci_low_pp == -100.0
    assert verdict.ci_high_pp == -100.0


def test_compare_reports_no_regression_when_arms_are_identical() -> None:
    verdict = compare(
        baseline_scores=_all_tasks(True),
        candidate_scores=_all_tasks(True),
        margin_pp=3.0,
        n_bootstrap=200,
        seed=0,
    )
    assert verdict.label == "NO_REGRESSION"
    assert verdict.effect_pp == 0.0
    assert verdict.ci_low_pp == 0.0
    assert verdict.ci_high_pp == 0.0


def test_compare_is_deterministic_for_a_given_seed() -> None:
    import random

    gen = random.Random(123)
    baseline = {f"task_{i}": [gen.random() < 0.5 for _ in range(10)] for i in range(20)}
    candidate = {f"task_{i}": [gen.random() < 0.6 for _ in range(10)] for i in range(20)}

    first = compare(baseline, candidate, margin_pp=3.0, n_bootstrap=500, seed=42)
    second = compare(baseline, candidate, margin_pp=3.0, n_bootstrap=500, seed=42)

    assert first == second
