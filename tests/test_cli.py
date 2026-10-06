import json
from pathlib import Path

from click.testing import CliRunner

from jerald.cli import main
from jerald.store.store import Store


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


def test_compare_with_store_option_persists_the_run(tmp_path: Path) -> None:
    suite_path, config_path = _write_suite_and_config(tmp_path, candidate_model="candidate-model")
    store_path = tmp_path / "jerald.db"

    result = CliRunner().invoke(
        main,
        ["compare", "--config", str(config_path), "--suite", str(suite_path),
         "--seed", "0", "--store", str(store_path)],
    )

    assert result.exit_code == 1
    assert "run_id:" in result.output
    run_id = next(
        line.split("run_id:")[1].strip() for line in result.output.splitlines() if "run_id:" in line
    )

    store = Store(store_path)
    stored = store.get_run(run_id)
    assert stored is not None
    assert stored.project == "demo"
    assert stored.suite_name == "demo-suite"
    assert stored.verdict.label == "REGRESSION"
    assert len(stored.trials) == 2 * 2 * 5  # 2 arms x 2 tasks x 5 trials
    store.close()


def test_compare_without_store_option_does_not_persist_anything(tmp_path: Path) -> None:
    suite_path, config_path = _write_suite_and_config(tmp_path, candidate_model="candidate-model")

    result = CliRunner().invoke(
        main, ["compare", "--config", str(config_path), "--suite", str(suite_path), "--seed", "0"]
    )

    assert "run_id:" not in result.output
    assert not (tmp_path / "jerald.db").exists()


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


def test_run_persists_the_baseline_arm_by_default(tmp_path: Path) -> None:
    suite_path, config_path = _write_suite_and_config(tmp_path, candidate_model="candidate-model")
    store_path = tmp_path / "jerald.db"

    result = CliRunner().invoke(
        main,
        ["run", "--config", str(config_path), "--suite", str(suite_path),
         "--seed", "0", "--store", str(store_path)],
    )

    assert result.exit_code == 0
    run_id = next(
        line.split("run_id:")[1].strip() for line in result.output.splitlines() if "run_id:" in line
    )

    store = Store(store_path)
    stored = store.get_run(run_id)
    assert stored is not None
    assert stored.kind == "run"
    assert stored.verdict is None
    assert len(stored.trials) == 2 * 5  # 2 tasks x 5 trials (suite default)
    assert all(r.passed for r in stored.trials)  # baseline-model always matches "ok"
    store.close()


def test_run_with_arm_candidate_runs_the_candidate_configuration(tmp_path: Path) -> None:
    suite_path, config_path = _write_suite_and_config(tmp_path, candidate_model="candidate-model")
    store_path = tmp_path / "jerald.db"

    result = CliRunner().invoke(
        main,
        ["run", "--config", str(config_path), "--suite", str(suite_path), "--arm", "candidate",
         "--seed", "0", "--store", str(store_path)],
    )

    assert result.exit_code == 0
    run_id = next(
        line.split("run_id:")[1].strip() for line in result.output.splitlines() if "run_id:" in line
    )
    store = Store(store_path)
    stored = store.get_run(run_id)
    assert stored is not None
    assert all(not r.passed for r in stored.trials)  # candidate-model never matches "ok"
    store.close()


def test_run_trials_option_overrides_the_suite_default(tmp_path: Path) -> None:
    suite_path, config_path = _write_suite_and_config(tmp_path, candidate_model="candidate-model")
    store_path = tmp_path / "jerald.db"

    result = CliRunner().invoke(
        main,
        ["run", "--config", str(config_path), "--suite", str(suite_path), "--trials", "2",
         "--seed", "0", "--store", str(store_path)],
    )

    run_id = next(
        line.split("run_id:")[1].strip() for line in result.output.splitlines() if "run_id:" in line
    )
    store = Store(store_path)
    stored = store.get_run(run_id)
    assert stored is not None
    assert len(stored.trials) == 2 * 2  # 2 tasks x 2 trials (overridden)
    store.close()


def test_run_requires_suite_flag(tmp_path: Path) -> None:
    _, config_path = _write_suite_and_config(tmp_path, candidate_model="candidate-model")

    result = CliRunner().invoke(main, ["run", "--config", str(config_path)])

    assert result.exit_code == 3
    assert "--suite" in result.output


def test_run_requires_store_flag(tmp_path: Path) -> None:
    suite_path, config_path = _write_suite_and_config(tmp_path, candidate_model="candidate-model")

    result = CliRunner().invoke(
        main, ["run", "--config", str(config_path), "--suite", str(suite_path)]
    )

    assert result.exit_code == 3
    assert "--store" in result.output


def test_run_dry_run_prints_plan_without_requiring_store(tmp_path: Path) -> None:
    suite_path, config_path = _write_suite_and_config(tmp_path, candidate_model="candidate-model")

    result = CliRunner().invoke(
        main,
        ["run", "--config", str(config_path), "--suite", str(suite_path), "--dry-run"],
    )

    assert result.exit_code == 0
    assert "demo-suite" in result.output
    assert "arm: baseline" in result.output
    assert "run_id:" not in result.output


def test_run_exits_3_on_missing_config_file(tmp_path: Path) -> None:
    suite_path, _ = _write_suite_and_config(tmp_path, candidate_model="candidate-model")

    result = CliRunner().invoke(
        main,
        ["run", "--config", str(tmp_path / "missing.yaml"), "--suite", str(suite_path),
         "--store", str(tmp_path / "jerald.db")],
    )

    assert result.exit_code == 3


def test_baseline_save_persists_and_names_a_run(tmp_path: Path) -> None:
    suite_path, config_path = _write_suite_and_config(tmp_path, candidate_model="candidate-model")
    store_path = tmp_path / "jerald.db"

    result = CliRunner().invoke(
        main,
        ["baseline", "save", "main", "--config", str(config_path), "--suite", str(suite_path),
         "--store", str(store_path), "--seed", "0"],
    )

    assert result.exit_code == 0
    assert "main" in result.output

    store = Store(store_path)
    stored = store.get_baseline("main")
    assert stored is not None
    assert stored.kind == "baseline"
    assert len(stored.trials) == 2 * 5  # 2 tasks x 5 trials (suite default)
    assert all(r.passed for r in stored.trials)  # baseline-model always matches "ok"
    store.close()


def test_baseline_save_with_same_name_replaces_the_previous_run(tmp_path: Path) -> None:
    suite_path, config_path = _write_suite_and_config(tmp_path, candidate_model="candidate-model")
    store_path = tmp_path / "jerald.db"
    common_args = ["--config", str(config_path), "--suite", str(suite_path),
                   "--store", str(store_path)]

    CliRunner().invoke(main, ["baseline", "save", "main", *common_args, "--seed", "0"])
    CliRunner().invoke(main, ["baseline", "save", "main", *common_args, "--seed", "1"])

    store = Store(store_path)
    assert len(store.list_baselines()) == 1
    store.close()


def test_baseline_list_prints_saved_baselines(tmp_path: Path) -> None:
    suite_path, config_path = _write_suite_and_config(tmp_path, candidate_model="candidate-model")
    store_path = tmp_path / "jerald.db"
    common_args = ["--config", str(config_path), "--suite", str(suite_path),
                   "--store", str(store_path)]

    CliRunner().invoke(main, ["baseline", "save", "main", *common_args])
    CliRunner().invoke(main, ["baseline", "save", "release-1", *common_args])

    result = CliRunner().invoke(main, ["baseline", "list", "--store", str(store_path)])

    assert result.exit_code == 0
    assert "main" in result.output
    assert "release-1" in result.output


def test_baseline_list_with_no_baselines_prints_a_helpful_message(tmp_path: Path) -> None:
    store_path = tmp_path / "jerald.db"
    Store(store_path).close()

    result = CliRunner().invoke(main, ["baseline", "list", "--store", str(store_path)])

    assert result.exit_code == 0
    assert "no baselines" in result.output.lower()


def test_baseline_show_prints_per_task_pass_counts(tmp_path: Path) -> None:
    suite_path, config_path = _write_suite_and_config(tmp_path, candidate_model="candidate-model")
    store_path = tmp_path / "jerald.db"

    CliRunner().invoke(
        main,
        ["baseline", "save", "main", "--config", str(config_path), "--suite", str(suite_path),
         "--store", str(store_path)],
    )
    result = CliRunner().invoke(main, ["baseline", "show", "main", "--store", str(store_path)])

    assert result.exit_code == 0
    assert "task-1" in result.output
    assert "5/5" in result.output


def test_baseline_show_unknown_name_exits_3(tmp_path: Path) -> None:
    store_path = tmp_path / "jerald.db"
    Store(store_path).close()

    result = CliRunner().invoke(main, ["baseline", "show", "missing", "--store", str(store_path)])

    assert result.exit_code == 3
    assert "missing" in result.output


def test_baseline_save_requires_suite_flag(tmp_path: Path) -> None:
    _, config_path = _write_suite_and_config(tmp_path, candidate_model="candidate-model")

    result = CliRunner().invoke(
        main,
        ["baseline", "save", "main", "--config", str(config_path),
         "--store", str(tmp_path / "jerald.db")],
    )

    assert result.exit_code == 3
    assert "--suite" in result.output


def test_baseline_save_requires_store_flag(tmp_path: Path) -> None:
    suite_path, config_path = _write_suite_and_config(tmp_path, candidate_model="candidate-model")

    result = CliRunner().invoke(
        main,
        ["baseline", "save", "main", "--config", str(config_path), "--suite", str(suite_path)],
    )

    assert result.exit_code == 3
    assert "--store" in result.output
