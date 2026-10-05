from jerald.adapters.base import TrialResult, Usage
from jerald.scorers.outcome import exact


def _trial(final_message: str | None) -> TrialResult:
    return TrialResult(
        trial_id="t1",
        task_id="task1",
        outcome="completed",
        final_message=final_message,
        trajectory=[],
        usage=Usage(input_tokens=0, output_tokens=0, cost_usd=0.0),
        model_reported=None,
    )


def test_exact_passes_when_final_message_matches() -> None:
    scorer = exact("Your order was refunded.")
    result = scorer.score(_trial("Your order was refunded."))
    assert result.passed is True
    assert result.value == 1.0


def test_exact_fails_when_final_message_differs() -> None:
    scorer = exact("Your order was refunded.")
    result = scorer.score(_trial("Sorry, I can't help with that."))
    assert result.passed is False
    assert result.value == 0.0


def test_regex_passes_when_pattern_matches_anywhere_in_final_message() -> None:
    from jerald.scorers.outcome import regex

    scorer = regex(r"refund(ed)?")
    result = scorer.score(_trial("Your order was refunded."))
    assert result.passed is True
    assert result.value == 1.0


def test_regex_fails_when_pattern_does_not_match() -> None:
    from jerald.scorers.outcome import regex

    scorer = regex(r"refund(ed)?")
    result = scorer.score(_trial("I've cancelled your subscription."))
    assert result.passed is False
    assert result.value == 0.0


def test_regex_raises_at_construction_time_for_invalid_pattern() -> None:
    import re

    import pytest

    from jerald.scorers.outcome import regex

    with pytest.raises(re.error):
        regex("[invalid(")


def test_json_schema_passes_when_final_message_matches_schema() -> None:
    from jerald.scorers.outcome import json_schema

    scorer = json_schema({
        "type": "object",
        "properties": {"order_id": {"type": "integer"}},
        "required": ["order_id"],
    })
    result = scorer.score(_trial('{"order_id": 4412}'))
    assert result.passed is True
    assert result.value == 1.0


def test_json_schema_fails_when_final_message_violates_schema() -> None:
    from jerald.scorers.outcome import json_schema

    scorer = json_schema({
        "type": "object",
        "properties": {"order_id": {"type": "integer"}},
        "required": ["order_id"],
    })
    result = scorer.score(_trial('{"order_id": "not-a-number"}'))
    assert result.passed is False
    assert result.value == 0.0


def test_json_schema_fails_without_raising_when_final_message_is_not_json() -> None:
    from jerald.scorers.outcome import json_schema

    scorer = json_schema({"type": "object"})
    result = scorer.score(_trial("not json at all"))
    assert result.passed is False
    assert result.value == 0.0
