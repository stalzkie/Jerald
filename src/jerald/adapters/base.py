from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol


@dataclass(frozen=True)
class TaskSpec:
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


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int
    cost_usd: float


TrialOutcome = Literal["completed", "agent_error", "timeout", "max_steps_exceeded"]


@dataclass(frozen=True)
class TrialResult:
    trial_id: str
    task_id: str
    outcome: TrialOutcome
    final_message: str | None
    trajectory: Sequence[Step]
    usage: Usage
    model_reported: str | None


class AdapterInfrastructureError(Exception):
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
    ) -> TrialResult: ...

    def close(self) -> None: ...
