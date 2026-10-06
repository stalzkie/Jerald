from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping, Sequence
from typing import Any

from jerald.adapters.base import AdapterInfrastructureError, Step, TaskSpec, TrialResult, Usage


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


class CliAdapter:
    def __init__(self, command: Sequence[str], *, kill_grace_s: float = 5.0) -> None:
        self.command = list(command)
        self._kill_grace_s = kill_grace_s

    def run_trial(
        self,
        task: TaskSpec,
        trial_id: str,
        seed: int,
        overrides: Mapping[str, Any],
    ) -> TrialResult:
        request = json.dumps({
            "task_id": task.task_id,
            "messages": list(task.messages),
            "seed": seed,
            "overrides": dict(overrides),
        })
        proc = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            stdout, stderr = proc.communicate(input=request, timeout=task.timeout_s)
        except subprocess.TimeoutExpired:
            # SIGTERM first so a well-behaved AUT can shut down cleanly; only
            # escalate to SIGKILL if it's still alive after the grace period.
            proc.terminate()
            try:
                proc.communicate(timeout=self._kill_grace_s)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
            return _empty_result(trial_id, task.task_id, "timeout")

        if proc.returncode != 0:
            raise AdapterInfrastructureError(
                f"cli adapter exited with code {proc.returncode}: {stderr.strip()}",
                retryable=True,
            )

        try:
            response = json.loads(stdout)
        except json.JSONDecodeError as e:
            raise AdapterInfrastructureError(
                f"cli adapter returned invalid JSON on stdout: {e}",
                retryable=False,
                cause=e,
            ) from e

        if response.get("error"):
            return _empty_result(trial_id, task.task_id, "agent_error")

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
