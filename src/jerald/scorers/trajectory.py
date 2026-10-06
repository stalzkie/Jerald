from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from jerald.adapters.base import Step, TrialResult
from jerald.scorers.base import ScoreResult


def _tool_calls(steps: Sequence[Step], name: str) -> list[Step]:
    return [s for s in steps if s.type == "tool_call" and s.name == name]


def trajectory(
    *,
    tool_called: str | None = None,
    tool_not_called: str | None = None,
    args_match: Mapping[str, Any] | None = None,
    required: bool = True,
):
    if tool_called is None and tool_not_called is None and args_match is None:
        raise ValueError(
            "trajectory scorer needs at least one of tool_called, tool_not_called, args_match"
        )

    class _Trajectory:
        def score(self, trial: TrialResult) -> ScoreResult:
            failures: list[str] = []
            matched_call: Step | None = None

            if tool_called is not None:
                calls = _tool_calls(trial.trajectory, tool_called)
                if not calls:
                    failures.append(f"tool {tool_called!r} was never called")
                else:
                    matched_call = calls[0]

            if tool_not_called is not None and _tool_calls(trial.trajectory, tool_not_called):
                failures.append(f"tool {tool_not_called!r} was called but must not be")

            if args_match is not None:
                if matched_call is None:
                    failures.append("args_match given without a matching tool_called step")
                else:
                    call_args = matched_call.args or {}
                    if any(call_args.get(k) != v for k, v in args_match.items()):
                        failures.append(
                            f"args {dict(call_args)!r} did not match {dict(args_match)!r}"
                        )

            passed = not failures
            evidence = "matched" if passed else "; ".join(failures)
            return ScoreResult(
                scorer_id="trajectory",
                passed=passed,
                value=1.0 if passed else 0.0,
                evidence=evidence,
                required=required,
            )

    return _Trajectory()
