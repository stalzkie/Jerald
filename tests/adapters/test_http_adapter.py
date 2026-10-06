import json

import httpx
import pytest

from jerald.adapters.base import AdapterInfrastructureError, TaskSpec
from jerald.adapters.http_adapter import HttpAdapter


def _task(timeout_s: float = 5.0, max_steps: int = 10) -> TaskSpec:
    return TaskSpec(task_id="t1", messages=[{"role": "user", "content": "hi"}],
                     timeout_s=timeout_s, max_steps=max_steps)


def _adapter(handler) -> HttpAdapter:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return HttpAdapter("http://agent.example/invoke", client=client)


def test_http_adapter_returns_completed_result_on_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(200, json={
            "final_message": f"echo:{body['task_id']}:{body['env']['seed']}",
            "model_reported": "echo-model",
        })

    adapter = _adapter(handler)
    result = adapter.run_trial(_task(), trial_id="trial-1", seed=7, overrides={})
    assert result.outcome == "completed"
    assert result.final_message == "echo:t1:7"
    assert result.model_reported == "echo-model"


def test_http_adapter_sends_task_trial_messages_seed_and_overrides() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"final_message": "ok"})

    adapter = _adapter(handler)
    adapter.run_trial(_task(), trial_id="trial-9", seed=3, overrides={"model": "candidate"})
    assert captured["task_id"] == "t1"
    assert captured["trial_id"] == "trial-9"
    assert captured["messages"] == [{"role": "user", "content": "hi"}]
    assert captured["env"] == {"seed": 3}
    assert captured["overrides"] == {"model": "candidate"}


def test_http_adapter_converts_in_band_error_field_to_agent_error_outcome() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": "tool exploded"})

    adapter = _adapter(handler)
    result = adapter.run_trial(_task(), trial_id="trial-2", seed=1, overrides={})
    assert result.outcome == "agent_error"
    assert result.final_message is None


def test_http_adapter_raises_retryable_infrastructure_error_on_5xx() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="service unavailable")

    adapter = _adapter(handler)
    with pytest.raises(AdapterInfrastructureError) as excinfo:
        adapter.run_trial(_task(), trial_id="trial-3", seed=1, overrides={})
    assert excinfo.value.retryable is True


def test_http_adapter_raises_non_retryable_infrastructure_error_on_4xx() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad request")

    adapter = _adapter(handler)
    with pytest.raises(AdapterInfrastructureError) as excinfo:
        adapter.run_trial(_task(), trial_id="trial-4", seed=1, overrides={})
    assert excinfo.value.retryable is False


def test_http_adapter_treats_429_as_retryable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="rate limited")

    adapter = _adapter(handler)
    with pytest.raises(AdapterInfrastructureError) as excinfo:
        adapter.run_trial(_task(), trial_id="trial-5", seed=1, overrides={})
    assert excinfo.value.retryable is True


def test_http_adapter_raises_non_retryable_infrastructure_error_on_malformed_json_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json")

    adapter = _adapter(handler)
    with pytest.raises(AdapterInfrastructureError) as excinfo:
        adapter.run_trial(_task(), trial_id="trial-6", seed=1, overrides={})
    assert excinfo.value.retryable is False


def test_http_adapter_raises_retryable_infrastructure_error_on_connection_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    adapter = _adapter(handler)
    with pytest.raises(AdapterInfrastructureError) as excinfo:
        adapter.run_trial(_task(), trial_id="trial-7", seed=1, overrides={})
    assert excinfo.value.retryable is True


def test_http_adapter_returns_timeout_outcome_when_request_exceeds_timeout_s() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("took too long")

    adapter = _adapter(handler)
    result = adapter.run_trial(_task(timeout_s=0.2), trial_id="trial-8", seed=1, overrides={})
    assert result.outcome == "timeout"
    assert result.final_message is None


def test_http_adapter_returns_max_steps_exceeded_when_trajectory_exceeds_budget() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        step = {"type": "tool_call", "name": "noop", "args": {}, "result": None,
                "error": None, "t_start": 0.0, "t_end": 0.1}
        return httpx.Response(200, json={"final_message": "done", "trajectory": [step, step, step]})

    adapter = _adapter(handler)
    result = adapter.run_trial(_task(max_steps=2), trial_id="trial-10", seed=1, overrides={})
    assert result.outcome == "max_steps_exceeded"
    assert len(result.trajectory) == 3
