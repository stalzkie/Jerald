from datetime import UTC, datetime
from pathlib import Path

from jerald.adapters.base import Step, TrialResult, Usage
from jerald.analysis.compare import Verdict
from jerald.orchestrator.core import TrialRecord
from jerald.scorers.base import ScoreResult
from jerald.store.store import Store


def _trial_record(arm_name: str = "baseline") -> TrialRecord:
    step = Step(type="tool_call", name="lookup", args={"id": 1}, result={"ok": True},
                error=None, t_start=0.0, t_end=0.1)
    trial = TrialResult(
        trial_id=f"task_0:{arm_name}:0", task_id="task_0", outcome="completed",
        final_message="ok", trajectory=[step],
        usage=Usage(input_tokens=10, output_tokens=5, cost_usd=0.01),
        model_reported="example-model",
    )
    score = ScoreResult(scorer_id="exact", passed=True, value=1.0, evidence="matched")
    return TrialRecord(
        task_id="task_0", arm_name=arm_name, trial_index=0, seed=42,
        trial=trial, scores=[score], passed=True,
    )


def _verdict() -> Verdict:
    return Verdict(label="NO_REGRESSION", effect_pp=0.0, ci_low_pp=-1.0, ci_high_pp=1.0,
                    margin_pp=3.0)


def test_save_and_get_run_round_trips_verdict_and_trial_records(tmp_path: Path) -> None:
    store = Store(tmp_path / "jerald.db")
    started = datetime(2026, 10, 6, 12, 0, 0, tzinfo=UTC)
    ended = datetime(2026, 10, 6, 12, 5, 0, tzinfo=UTC)

    run_id = store.save_run(
        kind="compare", project="demo", suite_name="demo-suite", suite_version=1, seed=0,
        alpha=0.05, started_at=started, ended_at=ended,
        trials=[_trial_record()], verdict=_verdict(),
    )

    stored = store.get_run(run_id)
    assert stored is not None
    assert stored.run_id == run_id
    assert stored.kind == "compare"
    assert stored.project == "demo"
    assert stored.suite_name == "demo-suite"
    assert stored.suite_version == 1
    assert stored.seed == 0
    assert stored.alpha == 0.05
    assert stored.started_at == started
    assert stored.ended_at == ended
    assert stored.verdict == _verdict()

    assert len(stored.trials) == 1
    record = stored.trials[0]
    assert record.task_id == "task_0"
    assert record.arm_name == "baseline"
    assert record.trial_index == 0
    assert record.seed == 42
    assert record.passed is True
    assert record.trial.final_message == "ok"
    assert record.trial.outcome == "completed"
    assert record.trial.usage == Usage(input_tokens=10, output_tokens=5, cost_usd=0.01)
    assert record.trial.model_reported == "example-model"
    assert list(record.trial.trajectory) == [
        Step(type="tool_call", name="lookup", args={"id": 1}, result={"ok": True},
             error=None, t_start=0.0, t_end=0.1)
    ]
    assert list(record.scores) == [
        ScoreResult(scorer_id="exact", passed=True, value=1.0, evidence="matched")
    ]
    store.close()


def test_save_run_with_no_verdict_round_trips_as_none(tmp_path: Path) -> None:
    store = Store(tmp_path / "jerald.db")
    started = datetime(2026, 10, 6, tzinfo=UTC)

    run_id = store.save_run(
        kind="run", project="demo", suite_name="demo-suite", suite_version=1, seed=0,
        alpha=0.05, started_at=started, ended_at=started,
        trials=[_trial_record()], verdict=None,
    )

    stored = store.get_run(run_id)
    assert stored is not None
    assert stored.kind == "run"
    assert stored.verdict is None
    assert len(stored.trials) == 1
    store.close()


def test_get_run_returns_none_for_unknown_run_id(tmp_path: Path) -> None:
    store = Store(tmp_path / "jerald.db")
    assert store.get_run("does-not-exist") is None
    store.close()


def test_list_runs_returns_summaries_most_recent_first(tmp_path: Path) -> None:
    store = Store(tmp_path / "jerald.db")
    first = store.save_run(
        kind="compare", project="demo", suite_name="suite-a", suite_version=1, seed=0,
        alpha=0.05, started_at=datetime(2026, 10, 1, tzinfo=UTC),
        ended_at=datetime(2026, 10, 1, 0, 1, tzinfo=UTC),
        trials=[_trial_record()], verdict=_verdict(),
    )
    second = store.save_run(
        kind="compare", project="demo", suite_name="suite-b", suite_version=2, seed=1,
        alpha=0.05, started_at=datetime(2026, 10, 2, tzinfo=UTC),
        ended_at=datetime(2026, 10, 2, 0, 1, tzinfo=UTC),
        trials=[_trial_record()], verdict=_verdict(),
    )

    summaries = store.list_runs()

    assert [s.run_id for s in summaries] == [second, first]
    assert summaries[0].suite_name == "suite-b"
    assert summaries[0].verdict_label == "NO_REGRESSION"
    store.close()


def test_store_persists_across_reopening_the_same_file(tmp_path: Path) -> None:
    path = tmp_path / "jerald.db"
    store = Store(path)
    run_id = store.save_run(
        kind="compare", project="demo", suite_name="demo-suite", suite_version=1, seed=0,
        alpha=0.05, started_at=datetime(2026, 10, 6, tzinfo=UTC),
        ended_at=datetime(2026, 10, 6, tzinfo=UTC),
        trials=[_trial_record()], verdict=_verdict(),
    )
    store.close()

    reopened = Store(path)
    stored = reopened.get_run(run_id)
    assert stored is not None
    assert stored.suite_name == "demo-suite"
    reopened.close()


def test_store_enables_wal_journal_mode(tmp_path: Path) -> None:
    store = Store(tmp_path / "jerald.db")
    assert store.journal_mode() == "wal"
    store.close()


def _save_sample_run(store: Store, *, project: str = "demo", suite_name: str = "demo-suite") -> str:
    return store.save_run(
        kind="baseline", project=project, suite_name=suite_name, suite_version=1, seed=0,
        alpha=0.05, started_at=datetime(2026, 10, 6, tzinfo=UTC),
        ended_at=datetime(2026, 10, 6, tzinfo=UTC),
        trials=[_trial_record()], verdict=None,
    )


def test_save_baseline_and_get_baseline_round_trips_the_named_run(tmp_path: Path) -> None:
    store = Store(tmp_path / "jerald.db")
    run_id = _save_sample_run(store)

    store.save_baseline(name="main", run_id=run_id, saved_at=datetime(2026, 10, 6, tzinfo=UTC))

    stored = store.get_baseline("main")
    assert stored is not None
    assert stored.run_id == run_id
    assert stored.kind == "baseline"
    store.close()


def test_get_baseline_returns_none_for_unknown_name(tmp_path: Path) -> None:
    store = Store(tmp_path / "jerald.db")
    assert store.get_baseline("does-not-exist") is None
    store.close()


def test_save_baseline_with_the_same_name_replaces_the_previous_run(tmp_path: Path) -> None:
    store = Store(tmp_path / "jerald.db")
    first_run_id = _save_sample_run(store)
    second_run_id = _save_sample_run(store)

    store.save_baseline(name="main", run_id=first_run_id, saved_at=datetime(2026, 10, 1, tzinfo=UTC))
    store.save_baseline(name="main", run_id=second_run_id, saved_at=datetime(2026, 10, 2, tzinfo=UTC))

    stored = store.get_baseline("main")
    assert stored is not None
    assert stored.run_id == second_run_id
    assert len(store.list_baselines()) == 1
    store.close()


def test_list_baselines_returns_summaries_most_recently_saved_first(tmp_path: Path) -> None:
    store = Store(tmp_path / "jerald.db")
    run_a = _save_sample_run(store, suite_name="suite-a")
    run_b = _save_sample_run(store, suite_name="suite-b")
    store.save_baseline(name="old", run_id=run_a, saved_at=datetime(2026, 10, 1, tzinfo=UTC))
    store.save_baseline(name="new", run_id=run_b, saved_at=datetime(2026, 10, 2, tzinfo=UTC))

    summaries = store.list_baselines()

    assert [s.name for s in summaries] == ["new", "old"]
    assert summaries[0].run_id == run_b
    assert summaries[0].suite_name == "suite-b"
    store.close()
