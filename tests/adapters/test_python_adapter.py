from jerald.adapters.base import TaskSpec
from jerald.adapters.python_adapter import PythonAdapter


class _EchoAUT:
    def run(self, task, config, seed):
        return {"final_message": f"echo:{task.task_id}:{seed}", "model_reported": "echo-model"}


def _task(timeout_s: float = 5.0, max_steps: int = 10) -> TaskSpec:
    return TaskSpec(task_id="t1", messages=[{"role": "user", "content": "hi"}],
                     timeout_s=timeout_s, max_steps=max_steps)


def test_python_adapter_returns_completed_result_on_success() -> None:
    adapter = PythonAdapter(_EchoAUT())
    result = adapter.run_trial(_task(), trial_id="trial-1", seed=7, overrides={})
    assert result.outcome == "completed"
    assert result.final_message == "echo:t1:7"
    assert result.model_reported == "echo-model"


class _BrokenAUT:
    def run(self, task, config, seed):
        raise RuntimeError("tool exploded")


def test_python_adapter_converts_aut_exception_to_agent_error_outcome() -> None:
    adapter = PythonAdapter(_BrokenAUT())
    result = adapter.run_trial(_task(), trial_id="trial-2", seed=1, overrides={})
    assert result.outcome == "agent_error"
    assert result.final_message is None


class _SlowAUT:
    def run(self, task, config, seed):
        import time

        time.sleep(1.0)
        return {"final_message": "too late"}


def test_python_adapter_returns_timeout_outcome_when_aut_exceeds_timeout_s() -> None:
    adapter = PythonAdapter(_SlowAUT())
    result = adapter.run_trial(_task(timeout_s=0.05), trial_id="trial-3", seed=1, overrides={})
    assert result.outcome == "timeout"
    assert result.final_message is None


class _SometimesSlowAUT:
    def run(self, task, config, seed):
        if seed == 1:
            import time

            time.sleep(1.0)
        return {"final_message": f"seed={seed}"}


def test_python_adapter_is_not_blocked_by_a_prior_timed_out_call() -> None:
    import time

    adapter = PythonAdapter(_SometimesSlowAUT())
    adapter.run_trial(_task(timeout_s=0.05), trial_id="trial-4", seed=1, overrides={})

    started = time.monotonic()
    result = adapter.run_trial(_task(timeout_s=5.0), trial_id="trial-5", seed=2, overrides={})
    elapsed = time.monotonic() - started

    assert result.outcome == "completed"
    assert result.final_message == "seed=2"
    assert elapsed < 0.5, f"second call should not wait on the first's lingering thread, took {elapsed:.2f}s"


class _VerboseAUT:
    def run(self, task, config, seed):
        step = {"type": "tool_call", "name": "noop", "args": {}, "result": None,
                "error": None, "t_start": 0.0, "t_end": 0.1}
        return {"final_message": "done", "trajectory": [step, step, step]}


def test_python_adapter_returns_max_steps_exceeded_when_trajectory_exceeds_budget() -> None:
    adapter = PythonAdapter(_VerboseAUT())
    result = adapter.run_trial(_task(max_steps=2), trial_id="trial-6", seed=1, overrides={})
    assert result.outcome == "max_steps_exceeded"
    assert len(result.trajectory) == 3
