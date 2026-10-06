import pytest

from jerald.adapters.base import AdapterInfrastructureError, TaskSpec, TrialResult, Usage
from jerald.adapters.fake_adapter import FakeAdapter


def _task(task_id: str = "t1") -> TaskSpec:
    return TaskSpec(task_id=task_id, messages=[{"role": "user", "content": "hi"}],
                     timeout_s=5.0, max_steps=10)


def _result(trial_id: str, task_id: str) -> TrialResult:
    return TrialResult(
        trial_id=trial_id,
        task_id=task_id,
        outcome="completed",
        final_message="scripted",
        trajectory=[],
        usage=Usage(input_tokens=0, output_tokens=0, cost_usd=0.0),
        model_reported=None,
    )


def test_fake_adapter_returns_scripted_result_keyed_by_task_and_trial_id() -> None:
    expected = _result("trial-1", "t1")
    adapter = FakeAdapter({("t1", "trial-1"): expected})
    result = adapter.run_trial(_task("t1"), trial_id="trial-1", seed=1, overrides={})
    assert result is expected


def test_fake_adapter_returns_result_from_callable() -> None:
    def responder(task: TaskSpec, trial_id: str, seed: int, overrides) -> TrialResult:
        return _result(trial_id, task.task_id)

    adapter = FakeAdapter(responder)
    result = adapter.run_trial(_task("t2"), trial_id="trial-2", seed=1, overrides={})
    assert result.task_id == "t2"
    assert result.trial_id == "trial-2"


def test_fake_adapter_raises_scripted_error_only_on_the_configured_call_number() -> None:
    expected = _result("trial-1", "t1")
    adapter = FakeAdapter({("t1", "trial-1"): expected}, fail_calls=[1])

    first = adapter.run_trial(_task(), trial_id="trial-1", seed=1, overrides={})
    assert first is expected

    with pytest.raises(AdapterInfrastructureError):
        adapter.run_trial(_task(), trial_id="trial-1", seed=1, overrides={})

    third = adapter.run_trial(_task(), trial_id="trial-1", seed=1, overrides={})
    assert third is expected


def test_fake_adapter_raises_the_given_error_instance() -> None:
    boom = AdapterInfrastructureError("custom outage", retryable=False)
    adapter = FakeAdapter({}, fail_calls=[0], error=boom)

    with pytest.raises(AdapterInfrastructureError) as excinfo:
        adapter.run_trial(_task(), trial_id="trial-1", seed=1, overrides={})
    assert excinfo.value is boom
    assert excinfo.value.retryable is False


def test_fake_adapter_close_is_a_no_op() -> None:
    adapter = FakeAdapter({})
    adapter.close()
