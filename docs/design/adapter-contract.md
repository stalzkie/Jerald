# Adapter contract — deep module design

Decided by comparing three independently-designed interfaces (minimal, maximally flexible,
optimized for the common caller) under the codebase-design skill's "design it twice" process.
See chat history for the full three designs; this records the hybrid that was chosen and why.

## Interface

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Literal, Mapping, Protocol, Sequence


@dataclass(frozen=True)
class TaskSpec:
    """Loop-invariant per Task: built once when the suite loads, passed by
    reference into every Trial of that Task. timeout_s/max_steps are already
    resolved from the suite's `defaults` merged with the task's own override —
    the Adapter never looks at suite config itself."""
    task_id: str
    messages: Sequence[Mapping[str, Any]]
    timeout_s: float
    max_steps: int


@dataclass(frozen=True)
class Step:
    type: Literal["message", "tool_call", "tool_result", "error"]
    name: str | None
    args: Mapping[str, Any] | None
    result: Any
    error: str | None
    t_start: float
    t_end: float
    # Invariant: steps are returned ordered by t_start ascending; t_end >= t_start.


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int
    cost_usd: float


TrialOutcome = Literal["completed", "agent_error", "timeout", "max_steps_exceeded"]


@dataclass(frozen=True)
class TrialResult:
    """Everything running one Trial produced. `trajectory` is the CONTEXT.md
    Trajectory term exactly — the ordered step record — nested inside this
    response, not a name for the response itself."""
    trial_id: str
    task_id: str
    outcome: TrialOutcome
    final_message: str | None
    trajectory: Sequence[Step]
    usage: Usage
    model_reported: str | None


class AdapterInfrastructureError(Exception):
    """The ONLY exception run_trial raises. Transport/infra failed before or
    during the call in a way that is not the AUT's behaviour: connection
    refused, process crashed, a response that fails the wire schema. Always
    retryable-or-not per `retryable` — never raised for AUT-side failure,
    which is always a TrialResult with outcome != "completed", not an
    exception."""
    def __init__(self, reason: str, *, retryable: bool = True, cause: BaseException | None = None):
        super().__init__(reason)
        self.reason = reason
        self.retryable = retryable
        self.__cause__ = cause


class Adapter(Protocol):
    def run_trial(
        self,
        task: TaskSpec,
        trial_id: str,
        seed: int,
        overrides: Mapping[str, Any],
    ) -> TrialResult:
        """
        Run exactly one Trial of `task` and return its TrialResult.

        MUST NOT raise for any AUT-side failure (tool error, max_steps
        exceeded, timeout_s exceeded, garbage output) — encode it as
        `outcome` plus an "error" Step instead. This is the data; the
        Orchestrator never retries it.

        MUST raise AdapterInfrastructureError for transport failures. This
        path is retried by the Orchestrator according to `retryable`.

        MUST enforce task.timeout_s and task.max_steps itself (or trust a
        subprocess/remote call that does).

        MUST be safe to call concurrently (one Adapter instance is shared
        across workers to respect per-provider concurrency caps).
        """
        ...

    def close(self) -> None:
        """Release pooled connections / subprocess workers. Idempotent.
        Required on every adapter, even if a no-op, for lifecycle symmetry —
        the Orchestrator always calls it once when a Run ends."""
        ...
```

## Usage example

```python
def execute_trial(adapter: Adapter, task: TaskSpec, trial_id: str, seed: int,
                   overrides: Mapping[str, Any], max_retries: int = 3) -> TrialResult:
    for attempt in range(max_retries):
        try:
            return adapter.run_trial(task, trial_id, seed, overrides)   # agent-side failure already lives in the result
        except AdapterInfrastructureError as e:
            if not e.retryable or attempt == max_retries - 1:
                raise
            backoff_sleep(attempt)
    raise AssertionError("unreachable")

# Orchestrator call site — task_spec built once per Task, reused across every Arm/Trial:
result = execute_trial(adapters[arm.config.adapter_type], task_spec, trial_id, seed, arm.config.overrides)
store.record(result)   # outcome="agent_error"/"timeout"/"max_steps_exceeded" all stored as-is, never retried
```

## What the implementation hides

- **http**: request/response translation, auth, connection pooling, classifying a response as infra-failure vs. agent-error, enforcing `timeout_s` via request timeout.
- **cli**: subprocess spawn/teardown, stdin/stdout JSON framing, SIGTERM→SIGKILL escalation on timeout, exit-code interpretation, stderr capture.
- **python**: thread/executor wrapper so a blocking `run(task, config, seed)` call can be bounded by `timeout_s`, converting any exception raised inside the AUT's own code into `outcome="agent_error"` rather than letting it propagate as an `AdapterInfrastructureError`.

## Dependency strategy and adapters

`Adapter` is the port. `HttpAdapter`, `CliAdapter`, `PythonAdapter` are production adapters selected by a small registry keyed on `Configuration.adapter_type`; adding `mcp` later is a fourth registry entry, no port change. `FakeAdapter` for tests holds a dict or callable mapping `(task_id, trial_id) -> TrialResult`, and can be scripted to raise `AdapterInfrastructureError` on the Nth call to exercise retry logic deterministically — no network, no subprocess, no sleeping.

## Trade-offs

High leverage: the Orchestrator's entire retry/record loop is the ~8 lines above regardless of transport; `TaskSpec` being loop-invariant means it's built once per Task rather than re-serialized into every Trial call. Thin spot, deliberately: no mid-trial progress hook or cancellation — see `docs/adr/0001-no-fault-injection-or-cancellation-in-adapter.md` for why that's not a gap, it's a seam placement decision.
