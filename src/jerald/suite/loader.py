from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from jerald.adapters.base import TaskSpec
from jerald.orchestrator.core import Task
from jerald.scorers.base import Scorer
from jerald.scorers.efficiency import efficiency
from jerald.scorers.outcome import exact, json_schema, regex
from jerald.scorers.trajectory import trajectory


class SuiteLoadError(Exception):
    """The YAML is malformed, missing a required field, has the wrong type for
    one, or names a scorer type nothing implements yet."""


@dataclass(frozen=True)
class Suite:
    name: str
    version: int
    tasks: Sequence[Task]
    trials_per_task: int


def load_suite(path: str | Path) -> Suite:
    path = Path(path)
    try:
        text = path.read_text()
    except OSError as e:
        raise SuiteLoadError(f"{path}: could not read file: {e}") from e
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise SuiteLoadError(f"{path}: invalid YAML: {e}") from e

    if not isinstance(raw, dict):
        raise SuiteLoadError(f"{path}: suite file must be a YAML mapping")

    name = _require_str(raw, "suite", context=str(path))
    version = _require_int(raw, "version", context=str(path))
    defaults = _require_mapping(raw, "defaults", context=str(path))
    default_timeout_s = _require_number(defaults, "timeout_s", context=f"{path}: defaults")
    default_max_steps = _require_int(defaults, "max_steps", context=f"{path}: defaults")
    trials_per_task = _require_int(defaults, "trials", context=f"{path}: defaults")

    raw_tasks = raw.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise SuiteLoadError(f"{path}: suite must define at least one task")

    tasks = [
        _load_task(entry, default_timeout_s, default_max_steps, context=f"{path}: tasks[{i}]")
        for i, entry in enumerate(raw_tasks)
    ]

    return Suite(name=name, version=version, tasks=tasks, trials_per_task=trials_per_task)


def _load_task(entry: Any, default_timeout_s: float, default_max_steps: int, *, context: str) -> Task:
    if not isinstance(entry, dict):
        raise SuiteLoadError(f"{context}: task must be a mapping")

    task_id = _require_str(entry, "id", context=context)
    task_context = f"{context} ({task_id})"

    input_block = _require_mapping(entry, "input", context=task_context)
    messages = input_block.get("messages")
    if not isinstance(messages, list) or not messages:
        raise SuiteLoadError(f"{task_context}: input.messages must be a non-empty list")

    timeout_s = _optional_number(entry, "timeout_s", default_timeout_s, context=task_context)
    max_steps = _optional_int(entry, "max_steps", default_max_steps, context=task_context)

    raw_scorers = entry.get("scorers")
    if not isinstance(raw_scorers, list) or not raw_scorers:
        raise SuiteLoadError(f"{task_context}: task must define at least one scorer")

    scorers = [
        _load_scorer(s, context=f"{task_context}: scorers[{i}]") for i, s in enumerate(raw_scorers)
    ]

    spec = TaskSpec(
        task_id=task_id, messages=messages, timeout_s=float(timeout_s), max_steps=int(max_steps)
    )
    return Task(spec=spec, scorers=scorers)


_SCORER_FACTORIES: Mapping[str, Any] = {
    "exact": lambda cfg, required: exact(_require_str(cfg, "expected"), required=required),
    "regex": lambda cfg, required: regex(_require_str(cfg, "pattern"), required=required),
    "json_schema": lambda cfg, required: json_schema(
        _require_mapping(cfg, "schema"), required=required
    ),
    "trajectory": lambda cfg, required: trajectory(
        tool_called=cfg.get("tool_called"),
        tool_not_called=cfg.get("tool_not_called"),
        args_match=cfg.get("args_match"),
        required=required,
    ),
    "efficiency": lambda cfg, required: efficiency(
        max_steps=cfg.get("max_steps"),
        max_cost_usd=cfg.get("max_cost_usd"),
        max_latency_s=cfg.get("max_latency_s"),
        required=required,
    ),
}


def _load_scorer(entry: Any, *, context: str) -> Scorer:
    if not isinstance(entry, dict):
        raise SuiteLoadError(f"{context}: scorer must be a mapping")

    scorer_type = _require_str(entry, "type", context=context)
    factory = _SCORER_FACTORIES.get(scorer_type)
    if factory is None:
        supported = ", ".join(sorted(_SCORER_FACTORIES))
        raise SuiteLoadError(
            f"{context}: scorer type {scorer_type!r} is not implemented yet "
            f"(supported: {supported})"
        )

    required = entry.get("required", True)
    try:
        return factory(entry, required)
    except SuiteLoadError:
        raise
    except Exception as e:
        raise SuiteLoadError(f"{context}: {e}") from e


def _require(mapping: Mapping[str, Any], key: str, *, context: str = "") -> Any:
    if key not in mapping:
        raise SuiteLoadError(f"{context}: missing required field {key!r}")
    return mapping[key]


def _require_str(mapping: Mapping[str, Any], key: str, *, context: str = "") -> str:
    value = _require(mapping, key, context=context)
    if not isinstance(value, str):
        raise SuiteLoadError(f"{context}: {key!r} must be a string")
    return value


def _require_int(mapping: Mapping[str, Any], key: str, *, context: str = "") -> int:
    value = _require(mapping, key, context=context)
    if not isinstance(value, int) or isinstance(value, bool):
        raise SuiteLoadError(f"{context}: {key!r} must be an integer")
    return value


def _require_number(mapping: Mapping[str, Any], key: str, *, context: str = "") -> float:
    value = _require(mapping, key, context=context)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise SuiteLoadError(f"{context}: {key!r} must be a number")
    return value


def _require_mapping(mapping: Mapping[str, Any], key: str, *, context: str = "") -> dict:
    value = _require(mapping, key, context=context)
    if not isinstance(value, dict):
        raise SuiteLoadError(f"{context}: {key!r} must be a mapping")
    return value


def _optional_number(mapping: Mapping[str, Any], key: str, default: float, *, context: str) -> float:
    if key not in mapping:
        return default
    value = mapping[key]
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise SuiteLoadError(f"{context}: {key!r} must be a number")
    return value


def _optional_int(mapping: Mapping[str, Any], key: str, default: int, *, context: str) -> int:
    if key not in mapping:
        return default
    value = mapping[key]
    if not isinstance(value, int) or isinstance(value, bool):
        raise SuiteLoadError(f"{context}: {key!r} must be an integer")
    return value
