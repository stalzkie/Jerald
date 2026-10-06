from pathlib import Path

import pytest

from jerald.adapters.base import Step, TrialResult, Usage
from jerald.suite.loader import SuiteLoadError, load_suite


def _trial(final_message: str | None) -> TrialResult:
    return TrialResult(
        trial_id="t1", task_id="task1", outcome="completed", final_message=final_message,
        trajectory=[], usage=Usage(input_tokens=0, output_tokens=0, cost_usd=0.0),
        model_reported=None,
    )


def _trial_with_trajectory(steps: list[Step]) -> TrialResult:
    return TrialResult(
        trial_id="t1", task_id="task1", outcome="completed", final_message="done",
        trajectory=steps, usage=Usage(input_tokens=0, output_tokens=0, cost_usd=0.0),
        model_reported=None,
    )


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "suite.yaml"
    path.write_text(text)
    return path


_WELL_FORMED = """
suite: support-agent
version: 3
defaults:
  timeout_s: 120
  max_steps: 25
  trials: 3
tasks:
  - id: refund-within-policy
    input:
      messages:
        - role: user
          content: 'Please refund order 4412.'
    scorers:
      - type: exact
        expected: 'Refunded order 4412.'
  - id: ambiguous-request
    input:
      messages:
        - role: user
          content: 'Cancel it.'
    scorers:
      - type: regex
        pattern: 'clarif(y|ication)'
"""


def test_load_suite_parses_name_version_trials_and_tasks(tmp_path: Path) -> None:
    suite = load_suite(_write(tmp_path, _WELL_FORMED))

    assert suite.name == "support-agent"
    assert suite.version == 3
    assert suite.trials_per_task == 3
    assert [t.spec.task_id for t in suite.tasks] == ["refund-within-policy", "ambiguous-request"]

    first = suite.tasks[0]
    assert first.spec.timeout_s == 120.0
    assert first.spec.max_steps == 25
    assert first.spec.messages == [{"role": "user", "content": "Please refund order 4412."}]

    result = first.scorers[0].score(_trial("Refunded order 4412."))
    assert result.passed is True


def test_load_suite_applies_per_task_timeout_and_max_steps_override(tmp_path: Path) -> None:
    text = _WELL_FORMED.replace(
        "  - id: refund-within-policy\n",
        "  - id: refund-within-policy\n    timeout_s: 30\n    max_steps: 5\n",
    )
    suite = load_suite(_write(tmp_path, text))

    overridden, default = suite.tasks
    assert overridden.spec.timeout_s == 30.0
    assert overridden.spec.max_steps == 5
    assert default.spec.timeout_s == 120.0
    assert default.spec.max_steps == 25


def test_load_suite_raises_when_defaults_field_missing(tmp_path: Path) -> None:
    text = _WELL_FORMED.replace("  trials: 3\n", "")
    with pytest.raises(SuiteLoadError, match="trials"):
        load_suite(_write(tmp_path, text))


def test_load_suite_raises_when_task_has_no_scorers(tmp_path: Path) -> None:
    text = _WELL_FORMED.replace(
        "    scorers:\n      - type: exact\n        expected: 'Refunded order 4412.'\n", ""
    )
    with pytest.raises(SuiteLoadError, match="scorer"):
        load_suite(_write(tmp_path, text))


def test_load_suite_raises_for_unsupported_scorer_type(tmp_path: Path) -> None:
    text = _WELL_FORMED.replace(
        "      - type: exact\n        expected: 'Refunded order 4412.'\n",
        "      - type: state\n        check: sql\n",
    )
    with pytest.raises(SuiteLoadError, match="state"):
        load_suite(_write(tmp_path, text))


def test_load_suite_builds_a_working_trajectory_scorer(tmp_path: Path) -> None:
    text = _WELL_FORMED.replace(
        "      - type: exact\n        expected: 'Refunded order 4412.'\n",
        "      - type: trajectory\n        tool_called: issue_refund\n"
        "        args_match: {order_id: 4412}\n        tool_not_called: close_account\n",
    )
    suite = load_suite(_write(tmp_path, text))

    scorer = suite.tasks[0].scorers[0]
    step = Step(type="tool_call", name="issue_refund", args={"order_id": 4412},
                result=None, error=None, t_start=0.0, t_end=0.1)
    result = scorer.score(_trial_with_trajectory([step]))
    assert result.passed is True


def test_load_suite_raises_when_trajectory_scorer_has_no_conditions(tmp_path: Path) -> None:
    text = _WELL_FORMED.replace(
        "      - type: exact\n        expected: 'Refunded order 4412.'\n",
        "      - type: trajectory\n",
    )
    with pytest.raises(SuiteLoadError, match="at least one"):
        load_suite(_write(tmp_path, text))


def test_load_suite_builds_a_working_efficiency_scorer(tmp_path: Path) -> None:
    text = _WELL_FORMED.replace(
        "      - type: exact\n        expected: 'Refunded order 4412.'\n",
        "      - type: efficiency\n        max_steps: 1\n        required: false\n",
    )
    suite = load_suite(_write(tmp_path, text))

    scorer = suite.tasks[0].scorers[0]
    step = Step(type="tool_call", name="noop", args=None, result=None, error=None,
                t_start=0.0, t_end=0.1)
    result = scorer.score(_trial_with_trajectory([step, step]))
    assert result.passed is False
    assert result.required is False


def test_load_suite_raises_when_efficiency_scorer_has_no_conditions(tmp_path: Path) -> None:
    text = _WELL_FORMED.replace(
        "      - type: exact\n        expected: 'Refunded order 4412.'\n",
        "      - type: efficiency\n",
    )
    with pytest.raises(SuiteLoadError, match="at least one"):
        load_suite(_write(tmp_path, text))


def test_load_suite_raises_on_invalid_yaml_syntax(tmp_path: Path) -> None:
    with pytest.raises(SuiteLoadError):
        load_suite(_write(tmp_path, "suite: [unterminated"))


def test_load_suite_raises_when_file_does_not_exist(tmp_path: Path) -> None:
    with pytest.raises(SuiteLoadError):
        load_suite(tmp_path / "does-not-exist.yaml")


def test_load_suite_raises_when_messages_missing(tmp_path: Path) -> None:
    text = _WELL_FORMED.replace(
        "    input:\n      messages:\n        - role: user\n          "
        "content: 'Please refund order 4412.'\n",
        "    input: {}\n",
    )
    with pytest.raises(SuiteLoadError, match="messages"):
        load_suite(_write(tmp_path, text))


def test_load_suite_builds_a_json_schema_scorer_with_required_false(tmp_path: Path) -> None:
    text = _WELL_FORMED.replace(
        "      - type: regex\n        pattern: 'clarif(y|ication)'\n",
        "      - type: json_schema\n        required: false\n        schema:\n"
        "          type: object\n          required: [order_id]\n",
    )
    suite = load_suite(_write(tmp_path, text))

    scorer = suite.tasks[1].scorers[0]
    result = scorer.score(_trial("not json"))
    assert result.passed is False
    assert result.required is False
