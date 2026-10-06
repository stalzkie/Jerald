import sys

import pytest

from jerald.adapters.base import AdapterInfrastructureError, TaskSpec
from jerald.adapters.cli_adapter import CliAdapter


def _task(timeout_s: float = 5.0, max_steps: int = 10) -> TaskSpec:
    return TaskSpec(task_id="t1", messages=[{"role": "user", "content": "hi"}],
                     timeout_s=timeout_s, max_steps=max_steps)


_ECHO_SCRIPT = (
    "import json, sys\n"
    "req = json.loads(sys.stdin.read())\n"
    "print(json.dumps({'final_message': 'echo:' + req['task_id'] + ':' + str(req['seed']), "
    "'model_reported': 'echo-model'}))\n"
)


def test_cli_adapter_returns_completed_result_on_success() -> None:
    adapter = CliAdapter([sys.executable, "-c", _ECHO_SCRIPT])
    result = adapter.run_trial(_task(), trial_id="trial-1", seed=7, overrides={})
    assert result.outcome == "completed"
    assert result.final_message == "echo:t1:7"
    assert result.model_reported == "echo-model"


_IN_BAND_ERROR_SCRIPT = (
    "import json, sys\n"
    "sys.stdin.read()\n"
    "print(json.dumps({'error': 'tool exploded'}))\n"
)


def test_cli_adapter_converts_in_band_error_field_to_agent_error_outcome() -> None:
    adapter = CliAdapter([sys.executable, "-c", _IN_BAND_ERROR_SCRIPT])
    result = adapter.run_trial(_task(), trial_id="trial-2", seed=1, overrides={})
    assert result.outcome == "agent_error"
    assert result.final_message is None


_CRASH_SCRIPT = (
    "import sys\n"
    "sys.stdin.read()\n"
    "sys.stderr.write('boom')\n"
    "sys.exit(1)\n"
)


def test_cli_adapter_raises_infrastructure_error_on_nonzero_exit() -> None:
    adapter = CliAdapter([sys.executable, "-c", _CRASH_SCRIPT])
    with pytest.raises(AdapterInfrastructureError) as excinfo:
        adapter.run_trial(_task(), trial_id="trial-3", seed=1, overrides={})
    assert excinfo.value.retryable is True


_GARBAGE_SCRIPT = (
    "import sys\n"
    "sys.stdin.read()\n"
    "print('not json')\n"
)


def test_cli_adapter_raises_infrastructure_error_on_malformed_stdout() -> None:
    adapter = CliAdapter([sys.executable, "-c", _GARBAGE_SCRIPT])
    with pytest.raises(AdapterInfrastructureError) as excinfo:
        adapter.run_trial(_task(), trial_id="trial-4", seed=1, overrides={})
    assert excinfo.value.retryable is False


_SLOW_SCRIPT = (
    "import sys, time\n"
    "sys.stdin.read()\n"
    "time.sleep(5)\n"
    "print('{}')\n"
)


def test_cli_adapter_returns_timeout_outcome_when_process_exceeds_timeout_s() -> None:
    adapter = CliAdapter([sys.executable, "-c", _SLOW_SCRIPT], kill_grace_s=0.2)
    result = adapter.run_trial(_task(timeout_s=0.2), trial_id="trial-5", seed=1, overrides={})
    assert result.outcome == "timeout"
    assert result.final_message is None


_VERBOSE_SCRIPT = (
    "import json, sys\n"
    "sys.stdin.read()\n"
    "step = {'type': 'tool_call', 'name': 'noop', 'args': {}, 'result': None, "
    "'error': None, 't_start': 0.0, 't_end': 0.1}\n"
    "print(json.dumps({'final_message': 'done', 'trajectory': [step, step, step]}))\n"
)


def test_cli_adapter_returns_max_steps_exceeded_when_trajectory_exceeds_budget() -> None:
    adapter = CliAdapter([sys.executable, "-c", _VERBOSE_SCRIPT])
    result = adapter.run_trial(_task(max_steps=2), trial_id="trial-6", seed=1, overrides={})
    assert result.outcome == "max_steps_exceeded"
    assert len(result.trajectory) == 3


_IGNORE_SIGTERM_SCRIPT = (
    "import signal, sys, time\n"
    "signal.signal(signal.SIGTERM, lambda *_: None)\n"
    "sys.stdin.read()\n"
    "time.sleep(5)\n"
)


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows has no catchable SIGTERM, so the escalation path can't be observed",
)
def test_cli_adapter_escalates_to_sigkill_when_process_ignores_sigterm() -> None:
    adapter = CliAdapter([sys.executable, "-c", _IGNORE_SIGTERM_SCRIPT], kill_grace_s=0.2)
    result = adapter.run_trial(_task(timeout_s=0.2), trial_id="trial-7", seed=1, overrides={})
    assert result.outcome == "timeout"
