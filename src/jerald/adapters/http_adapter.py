from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import httpx

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


class HttpAdapter:
    def __init__(self, url: str, *, client: httpx.Client | None = None) -> None:
        self.url = url
        self._client = client if client is not None else httpx.Client()
        self._owns_client = client is None

    def run_trial(
        self,
        task: TaskSpec,
        trial_id: str,
        seed: int,
        overrides: Mapping[str, Any],
    ) -> TrialResult:
        request = {
            "task_id": task.task_id,
            "trial_id": trial_id,
            "messages": list(task.messages),
            "env": {"seed": seed},
            "overrides": dict(overrides),
        }
        try:
            response = self._client.post(self.url, json=request, timeout=task.timeout_s)
        except httpx.TimeoutException:
            return _empty_result(trial_id, task.task_id, "timeout")
        except httpx.HTTPError as e:
            raise AdapterInfrastructureError(
                f"http adapter request failed: {e}", retryable=True, cause=e
            ) from e

        if response.status_code >= 400:
            retryable = response.status_code == 429 or response.status_code >= 500
            raise AdapterInfrastructureError(
                f"http adapter received {response.status_code}: {response.text}",
                retryable=retryable,
            )

        try:
            body = json.loads(response.content)
        except json.JSONDecodeError as e:
            raise AdapterInfrastructureError(
                f"http adapter returned invalid JSON body: {e}",
                retryable=False,
                cause=e,
            ) from e

        if body.get("error"):
            return _empty_result(trial_id, task.task_id, "agent_error")

        trajectory = [Step(**step) for step in body.get("trajectory", [])]
        outcome = "max_steps_exceeded" if len(trajectory) > task.max_steps else "completed"
        return TrialResult(
            trial_id=trial_id,
            task_id=task.task_id,
            outcome=outcome,  # type: ignore[arg-type]
            final_message=body.get("final_message"),
            trajectory=trajectory,
            usage=Usage(input_tokens=0, output_tokens=0, cost_usd=0.0),
            model_reported=body.get("model_reported"),
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()
