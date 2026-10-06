import json
from pathlib import Path

from click.testing import CliRunner

from jerald.cli import main


def test_version() -> None:
    result = CliRunner().invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "jerald" in result.output


_SUITE_YAML = """
suite: demo-suite
version: 1
defaults:
  timeout_s: 5
  max_steps: 10
  trials: 5
tasks:
  - id: task-1
    input:
      messages:
        - role: user
          content: hi
    scorers:
      - type: exact
        expected: ok
  - id: task-2
    input:
      messages:
        - role: user
          content: hi
    scorers:
      - type: exact
        expected: ok
"""


def _config_yaml(candidate_model: str) -> str:
    return f"""
project: demo
adapter:
  type: python
  target: tests._cli_fixture_agent:agent
configs:
  baseline:
    model: baseline-model
  candidate:
    model: {candidate_model}
"""


def _write_suite_and_config(tmp_path: Path, candidate_model: str) -> tuple[Path, Path]:
    suite_path = tmp_path / "suite.yaml"
    suite_path.write_text(_SUITE_YAML)
    config_path = tmp_path / "jerald.yaml"
    config_path.write_text(_config_yaml(candidate_model))
    return suite_path, config_path


def test_compare_exits_1_and_reports_regression_when_candidate_always_fails(tmp_path: Path) -> None:
    suite_path, config_path = _write_suite_and_config(tmp_path, candidate_model="candidate-model")

    result = CliRunner().invoke(
        main, ["compare", "--config", str(config_path), "--suite", str(suite_path), "--seed", "0"]
    )

    assert result.exit_code == 1
    assert "REGRESSION" in result.output


def test_compare_exits_0_when_arms_are_identical(tmp_path: Path) -> None:
    suite_path, config_path = _write_suite_and_config(tmp_path, candidate_model="baseline-model")

    result = CliRunner().invoke(
        main, ["compare", "--config", str(config_path), "--suite", str(suite_path), "--seed", "0"]
    )

    assert result.exit_code == 0
    assert "NO_REGRESSION" in result.output


def test_compare_writes_verdict_json_to_out_path(tmp_path: Path) -> None:
    suite_path, config_path = _write_suite_and_config(tmp_path, candidate_model="candidate-model")
    out_path = tmp_path / "verdict.json"

    CliRunner().invoke(
        main,
        ["compare", "--config", str(config_path), "--suite", str(suite_path),
         "--seed", "0", "--out", str(out_path)],
    )

    written = json.loads(out_path.read_text())
    assert written["label"] == "REGRESSION"
    assert written["margin_pp"] == 3.0


def test_compare_dry_run_prints_plan_without_running_trials(tmp_path: Path) -> None:
    suite_path, config_path = _write_suite_and_config(tmp_path, candidate_model="candidate-model")

    result = CliRunner().invoke(
        main,
        ["compare", "--config", str(config_path), "--suite", str(suite_path), "--dry-run"],
    )

    assert result.exit_code == 0
    assert "demo-suite" in result.output
    assert "tasks: 2" in result.output
    assert "REGRESSION" not in result.output


def test_compare_requires_suite_flag(tmp_path: Path) -> None:
    _, config_path = _write_suite_and_config(tmp_path, candidate_model="candidate-model")

    result = CliRunner().invoke(main, ["compare", "--config", str(config_path)])

    assert result.exit_code == 3
    assert "--suite" in result.output


def test_compare_exits_3_on_missing_config_file(tmp_path: Path) -> None:
    suite_path, _ = _write_suite_and_config(tmp_path, candidate_model="candidate-model")

    result = CliRunner().invoke(
        main,
        ["compare", "--config", str(tmp_path / "missing.yaml"), "--suite", str(suite_path)],
    )

    assert result.exit_code == 3


def test_compare_margin_pp_override_takes_precedence_over_config(tmp_path: Path) -> None:
    suite_path, config_path = _write_suite_and_config(tmp_path, candidate_model="candidate-model")

    result = CliRunner().invoke(
        main,
        ["compare", "--config", str(config_path), "--suite", str(suite_path),
         "--margin-pp", "200"],
    )

    assert "margin=200.0pp" in result.output
    assert "NO_REGRESSION" in result.output  # -100pp effect is within a 200pp margin
    assert result.exit_code == 0
