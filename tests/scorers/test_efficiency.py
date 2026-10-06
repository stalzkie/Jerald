import pytest

from jerald.adapters.base import Step, TrialResult, Usage
from jerald.scorers.efficiency import efficiency


def _trial(steps: list[Step] | None = None, cost_usd: float = 0.0) -> TrialResult:
    return TrialResult(
        trial_id="t1", task_id="task1", outcome="completed", final_message="done",
        trajectory=steps or [], usage=Usage(input_tokens=0, output_tokens=0, cost_usd=cost_usd),
        model_reported=None,
    )


def _step(t_start: float, t_end: float) -> Step:
    return Step(type="tool_call", name="noop", args=None, result=None, error=None,
                t_start=t_start, t_end=t_end)


def test_efficiency_passes_when_step_count_is_within_max_steps() -> None:
    scorer = efficiency(max_steps=3)
    result = scorer.score(_trial([_step(0, 1)] * 2))
    assert result.passed is True


def test_efficiency_fails_when_step_count_exceeds_max_steps() -> None:
    scorer = efficiency(max_steps=1)
    result = scorer.score(_trial([_step(0, 1)] * 2))
    assert result.passed is False
    assert "max_steps" in result.evidence


def test_efficiency_passes_when_cost_is_within_max_cost_usd() -> None:
    scorer = efficiency(max_cost_usd=0.05)
    result = scorer.score(_trial(cost_usd=0.01))
    assert result.passed is True


def test_efficiency_fails_when_cost_exceeds_max_cost_usd() -> None:
    scorer = efficiency(max_cost_usd=0.05)
    result = scorer.score(_trial(cost_usd=0.10))
    assert result.passed is False
    assert "max_cost_usd" in result.evidence


def test_efficiency_passes_when_latency_is_within_max_latency_s() -> None:
    scorer = efficiency(max_latency_s=10.0)
    result = scorer.score(_trial([_step(0.0, 5.0)]))
    assert result.passed is True


def test_efficiency_fails_when_latency_exceeds_max_latency_s() -> None:
    scorer = efficiency(max_latency_s=1.0)
    result = scorer.score(_trial([_step(0.0, 2.0), _step(2.0, 5.0)]))
    assert result.passed is False
    assert "max_latency_s" in result.evidence


def test_efficiency_combines_conditions_with_and() -> None:
    scorer = efficiency(max_steps=5, max_cost_usd=0.05)
    result = scorer.score(_trial([_step(0, 1)] * 2, cost_usd=0.10))
    assert result.passed is False  # cost exceeds, even though step count is fine


def test_efficiency_passes_when_every_combined_condition_holds() -> None:
    scorer = efficiency(max_steps=5, max_cost_usd=0.05)
    result = scorer.score(_trial([_step(0, 1)] * 2, cost_usd=0.01))
    assert result.passed is True


def test_efficiency_raises_at_construction_when_no_conditions_given() -> None:
    with pytest.raises(ValueError, match="at least one"):
        efficiency()


def test_efficiency_carries_through_a_non_default_required_flag() -> None:
    scorer = efficiency(max_steps=1, required=False)
    result = scorer.score(_trial([_step(0, 1)] * 2))
    assert result.required is False
