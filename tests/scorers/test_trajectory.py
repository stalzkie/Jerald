import pytest

from jerald.adapters.base import Step, TrialResult, Usage
from jerald.scorers.trajectory import trajectory


def _trial(steps: list[Step]) -> TrialResult:
    return TrialResult(
        trial_id="t1", task_id="task1", outcome="completed", final_message="done",
        trajectory=steps, usage=Usage(input_tokens=0, output_tokens=0, cost_usd=0.0),
        model_reported=None,
    )


def _tool_call(name: str, args: dict | None = None) -> Step:
    return Step(type="tool_call", name=name, args=args, result=None, error=None,
                t_start=0.0, t_end=0.1)


def test_trajectory_passes_when_tool_called_tool_was_called() -> None:
    scorer = trajectory(tool_called="issue_refund")
    result = scorer.score(_trial([_tool_call("issue_refund")]))
    assert result.passed is True


def test_trajectory_fails_when_tool_called_tool_was_never_called() -> None:
    scorer = trajectory(tool_called="issue_refund")
    result = scorer.score(_trial([_tool_call("lookup_order")]))
    assert result.passed is False
    assert "issue_refund" in result.evidence


def test_trajectory_passes_when_tool_not_called_tool_is_absent() -> None:
    scorer = trajectory(tool_not_called="close_account")
    result = scorer.score(_trial([_tool_call("issue_refund")]))
    assert result.passed is True


def test_trajectory_fails_when_tool_not_called_tool_was_called() -> None:
    scorer = trajectory(tool_not_called="close_account")
    result = scorer.score(_trial([_tool_call("close_account")]))
    assert result.passed is False
    assert "close_account" in result.evidence


def test_trajectory_passes_when_args_match_matches_the_called_tools_args() -> None:
    scorer = trajectory(tool_called="issue_refund", args_match={"order_id": 4412})
    result = scorer.score(_trial([_tool_call("issue_refund", {"order_id": 4412, "amount": 10})]))
    assert result.passed is True


def test_trajectory_fails_when_args_match_does_not_match() -> None:
    scorer = trajectory(tool_called="issue_refund", args_match={"order_id": 4412})
    result = scorer.score(_trial([_tool_call("issue_refund", {"order_id": 9999})]))
    assert result.passed is False


def test_trajectory_combines_all_conditions_with_and() -> None:
    scorer = trajectory(
        tool_called="issue_refund", args_match={"order_id": 4412}, tool_not_called="close_account",
    )
    steps = [_tool_call("issue_refund", {"order_id": 4412}), _tool_call("close_account")]
    result = scorer.score(_trial(steps))
    assert result.passed is False  # close_account was called, even though the other two hold


def test_trajectory_passes_when_every_combined_condition_holds() -> None:
    scorer = trajectory(
        tool_called="issue_refund", args_match={"order_id": 4412}, tool_not_called="close_account",
    )
    result = scorer.score(_trial([_tool_call("issue_refund", {"order_id": 4412})]))
    assert result.passed is True


def test_trajectory_raises_at_construction_when_no_conditions_given() -> None:
    with pytest.raises(ValueError, match="at least one"):
        trajectory()


def test_trajectory_carries_through_a_non_default_required_flag() -> None:
    scorer = trajectory(tool_called="issue_refund", required=False)
    result = scorer.score(_trial([]))
    assert result.required is False
