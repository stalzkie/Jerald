from __future__ import annotations

from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any

from jerald.adapters.base import Step, TaskSpec, TrialResult, Usage


def _empty_result(trial_id: str, task_id: str, outcome: str) -> TrialResult:
    return TrialResult(
        trial_id=trial_id,
        task_id=task_id,
        outcome=outcome,  # type: ignore[arg-type]
        final_message=None,
        trajectory=[],
        usage=Usage(input_tokens=0, output_tokens=0, cost_usd=0.0),
        model_reported=None,
    )


class PythonAdapter:
    def __init__(self, aut: Any) -> None:
        self.aut = aut

    def run_trial(
        self,
        task: TaskSpec,
        trial_id: str,
        seed: int,
        overrides: Mapping[str, Any],
    ) -> TrialResult:
        # A fresh single-use executor per call: a call that times out leaves its
        # thread running (Python cannot kill a thread), but that must never block
        # later calls on this same adapter, so each call gets its own worker.
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(self.aut.run, task, overrides, seed)
        try:
            response = future.result(timeout=task.timeout_s)
        except FutureTimeoutError:
            executor.shutdown(wait=False)
            return _empty_result(trial_id, task.task_id, "timeout")
        except Exception:  # noqa: BLE001 - AUT-side failure must become data, never propagate
            executor.shutdown(wait=False)
            return _empty_result(trial_id, task.task_id, "agent_error")
        executor.shutdown(wait=False)

        trajectory = [Step(**step) for step in response.get("trajectory", [])]
        outcome = "max_steps_exceeded" if len(trajectory) > task.max_steps else "completed"
        return TrialResult(
            trial_id=trial_id,
            task_id=task.task_id,
            outcome=outcome,  # type: ignore[arg-type]
            final_message=response.get("final_message"),
            trajectory=trajectory,
            usage=Usage(input_tokens=0, output_tokens=0, cost_usd=0.0),
            model_reported=response.get("model_reported"),
        )

    def close(self) -> None:
        pass
