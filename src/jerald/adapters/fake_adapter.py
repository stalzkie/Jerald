from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from jerald.adapters.base import AdapterInfrastructureError, TaskSpec, TrialResult

Responder = Callable[[TaskSpec, str, int, Mapping[str, Any]], TrialResult]


class FakeAdapter:
    """Test double for Adapter: no network, no subprocess, no sleeping.

    `responses` is either a dict keyed by (task_id, trial_id) or a callable
    computing the TrialResult on demand. `fail_calls` scripts which 0-indexed
    call numbers raise `error` instead of returning a result, so retry logic
    can be exercised deterministically.
    """

    def __init__(
        self,
        responses: Mapping[tuple[str, str], TrialResult] | Responder,
        *,
        fail_calls: Sequence[int] = (),
        error: AdapterInfrastructureError | None = None,
    ) -> None:
        self._responses = responses
        self._fail_calls = set(fail_calls)
        self._error = error if error is not None else AdapterInfrastructureError("scripted failure")
        self._call_count = 0

    def run_trial(
        self,
        task: TaskSpec,
        trial_id: str,
        seed: int,
        overrides: Mapping[str, Any],
    ) -> TrialResult:
        call_number = self._call_count
        self._call_count += 1
        if call_number in self._fail_calls:
            raise self._error
        if callable(self._responses):
            return self._responses(task, trial_id, seed, overrides)
        return self._responses[(task.task_id, trial_id)]

    def close(self) -> None:
        pass
