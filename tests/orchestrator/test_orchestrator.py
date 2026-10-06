from jerald.adapters.base import AdapterInfrastructureError, TaskSpec, TrialResult, Usage
from jerald.adapters.fake_adapter import FakeAdapter
from jerald.orchestrator.core import Arm, Orchestrator, Task
from jerald.scorers.outcome import exact


def _task(task_id: str) -> Task:
    spec = TaskSpec(task_id=task_id, messages=[{"role": "user", "content": "hi"}],
                     timeout_s=5.0, max_steps=10)
    return Task(spec=spec, scorers=[exact("ok")])


def _responder(final_message: str):
    def respond(task: TaskSpec, trial_id: str, seed: int, overrides) -> TrialResult:
        return TrialResult(
            trial_id=trial_id,
            task_id=task.task_id,
            outcome="completed",
            final_message=final_message,
            trajectory=[],
            usage=Usage(input_tokens=0, output_tokens=0, cost_usd=0.0),
            model_reported=None,
        )

    return respond


def test_orchestrator_reports_regression_when_candidate_always_fails() -> None:
    orchestrator = Orchestrator(max_concurrency=4, backoff=lambda attempt: None)
    tasks = [_task(f"task_{i}") for i in range(3)]
    baseline = Arm(name="baseline", adapter=FakeAdapter(_responder("ok")), overrides={})
    candidate = Arm(name="candidate", adapter=FakeAdapter(_responder("bad")), overrides={})

    result = orchestrator.run_comparison(
        tasks, baseline, candidate, trials_per_task=5, seed=0, n_bootstrap=200
    )

    assert result.verdict.label == "REGRESSION"
    assert result.verdict.effect_pp == -100.0
    for task in tasks:
        assert result.baseline_scores[task.spec.task_id] == [True] * 5
        assert result.candidate_scores[task.spec.task_id] == [False] * 5


def test_orchestrator_shares_the_env_seed_between_arms_for_the_same_trial_index() -> None:
    seen_baseline: dict[int, int] = {}
    seen_candidate: dict[int, int] = {}

    def make_recorder(sink: dict[int, int]):
        def respond(task: TaskSpec, trial_id: str, seed: int, overrides) -> TrialResult:
            trial_index = int(trial_id.rsplit(":", 1)[-1])
            sink[trial_index] = seed
            return TrialResult(
                trial_id=trial_id, task_id=task.task_id, outcome="completed",
                final_message="ok", trajectory=[],
                usage=Usage(input_tokens=0, output_tokens=0, cost_usd=0.0), model_reported=None,
            )

        return respond

    orchestrator = Orchestrator(max_concurrency=1, backoff=lambda attempt: None)
    baseline = Arm(name="baseline", adapter=FakeAdapter(make_recorder(seen_baseline)), overrides={})
    candidate = Arm(name="candidate", adapter=FakeAdapter(make_recorder(seen_candidate)), overrides={})

    orchestrator.run_comparison(
        [_task("task_0")], baseline, candidate, trials_per_task=4, seed=0, n_bootstrap=50
    )

    assert seen_baseline == seen_candidate
    assert len(seen_baseline) == 4


def test_orchestrator_retries_a_retryable_infrastructure_error_and_recovers() -> None:
    orchestrator = Orchestrator(max_concurrency=1, max_retries=3, backoff=lambda attempt: None)
    flaky = FakeAdapter(_responder("ok"), fail_calls=[0],
                         error=AdapterInfrastructureError("transient", retryable=True))
    baseline = Arm(name="baseline", adapter=flaky, overrides={})
    candidate = Arm(name="candidate", adapter=FakeAdapter(_responder("ok")), overrides={})

    result = orchestrator.run_comparison(
        [_task("task_0")], baseline, candidate, trials_per_task=3, seed=0, n_bootstrap=50
    )

    assert result.baseline_scores["task_0"] == [True, True, True]
    assert flaky.call_count == 4  # 3 trials + 1 retried failure


def test_orchestrator_does_not_retry_agent_side_failures() -> None:
    def respond(task: TaskSpec, trial_id: str, seed: int, overrides) -> TrialResult:
        return TrialResult(
            trial_id=trial_id, task_id=task.task_id, outcome="agent_error",
            final_message=None, trajectory=[],
            usage=Usage(input_tokens=0, output_tokens=0, cost_usd=0.0), model_reported=None,
        )

    orchestrator = Orchestrator(max_concurrency=1, backoff=lambda attempt: None)
    flaky = FakeAdapter(respond)
    baseline = Arm(name="baseline", adapter=flaky, overrides={})
    candidate = Arm(name="candidate", adapter=FakeAdapter(_responder("ok")), overrides={})

    result = orchestrator.run_comparison(
        [_task("task_0")], baseline, candidate, trials_per_task=3, seed=0, n_bootstrap=50
    )

    assert result.baseline_scores["task_0"] == [False, False, False]
    assert flaky.call_count == 3


def test_orchestrator_raises_when_a_non_retryable_infrastructure_error_occurs() -> None:
    import pytest

    orchestrator = Orchestrator(max_concurrency=1, backoff=lambda attempt: None)
    broken = FakeAdapter(_responder("ok"), fail_calls=[0],
                          error=AdapterInfrastructureError("bad request", retryable=False))
    baseline = Arm(name="baseline", adapter=broken, overrides={})
    candidate = Arm(name="candidate", adapter=FakeAdapter(_responder("ok")), overrides={})

    with pytest.raises(AdapterInfrastructureError) as excinfo:
        orchestrator.run_comparison(
            [_task("task_0")], baseline, candidate, trials_per_task=1, seed=0, n_bootstrap=50
        )
    assert excinfo.value.retryable is False
    assert broken.call_count == 1


def test_orchestrator_raises_after_exhausting_retries() -> None:
    import pytest

    orchestrator = Orchestrator(max_concurrency=1, max_retries=2, backoff=lambda attempt: None)
    always_broken = FakeAdapter(_responder("ok"), fail_calls=[0, 1],
                                 error=AdapterInfrastructureError("down", retryable=True))
    baseline = Arm(name="baseline", adapter=always_broken, overrides={})
    candidate = Arm(name="candidate", adapter=FakeAdapter(_responder("ok")), overrides={})

    with pytest.raises(AdapterInfrastructureError):
        orchestrator.run_comparison(
            [_task("task_0")], baseline, candidate, trials_per_task=1, seed=0, n_bootstrap=50
        )
    assert always_broken.call_count == 2
