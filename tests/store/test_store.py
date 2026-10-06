from datetime import UTC, datetime
from pathlib import Path

from jerald.adapters.base import Step, TrialResult, Usage
from jerald.analysis.compare import Verdict
from jerald.orchestrator.core import ComparisonResult, TrialRecord
from jerald.scorers.base import ScoreResult
from jerald.store.store import Store


def _comparison_result() -> ComparisonResult:
    step = Step(type="tool_call", name="lookup", args={"id": 1}, result={"ok": True},
                error=None, t_start=0.0, t_end=0.1)
    trial = TrialResult(
        trial_id="task_0:baseline:0", task_id="task_0", outcome="completed",
        final_message="ok", trajectory=[step],
        usage=Usage(input_tokens=10, output_tokens=5, cost_usd=0.01),
        model_reported="example-model",
    )
    score = ScoreResult(scorer_id="exact", passed=True, value=1.0, evidence="matched")
    record = TrialRecord(
        task_id="task_0", arm_name="baseline", trial_index=0, seed=42,
        trial=trial, scores=[score], passed=True,
    )
    verdict = Verdict(label="NO_REGRESSION", effect_pp=0.0, ci_low_pp=-1.0, ci_high_pp=1.0,
                       margin_pp=3.0)
    return ComparisonResult(
        verdict=verdict,
        baseline_scores={"task_0": [True]},
        candidate_scores={"task_0": [True]},
        trials=[record],
    )


def test_save_and_get_run_round_trips_verdict_and_trial_records(tmp_path: Path) -> None:
    store = Store(tmp_path / "jerald.db")
    started = datetime(2026, 10, 6, 12, 0, 0, tzinfo=UTC)
    ended = datetime(2026, 10, 6, 12, 5, 0, tzinfo=UTC)

    run_id = store.save_run(
        kind="compare", project="demo", suite_name="demo-suite", suite_version=1, seed=0,
        alpha=0.05, started_at=started, ended_at=ended, result=_comparison_result(),
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
    assert stored.verdict == Verdict(
        label="NO_REGRESSION", effect_pp=0.0, ci_low_pp=-1.0, ci_high_pp=1.0, margin_pp=3.0
    )

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
        result=_comparison_result(),
    )
    second = store.save_run(
        kind="compare", project="demo", suite_name="suite-b", suite_version=2, seed=1,
        alpha=0.05, started_at=datetime(2026, 10, 2, tzinfo=UTC),
        ended_at=datetime(2026, 10, 2, 0, 1, tzinfo=UTC),
        result=_comparison_result(),
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
        result=_comparison_result(),
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
