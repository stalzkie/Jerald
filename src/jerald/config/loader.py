from __future__ import annotations

import importlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from jerald.adapters.base import Adapter
from jerald.adapters.cli_adapter import CliAdapter
from jerald.adapters.http_adapter import HttpAdapter
from jerald.adapters.python_adapter import PythonAdapter
from jerald.orchestrator.core import Arm

_DEFAULT_MARGIN_PP = 3.0
_DEFAULT_ALPHA = 0.05


class ConfigLoadError(Exception):
    """jerald.yaml is malformed, missing a required field, has the wrong type
    for one, or names an adapter type nothing implements yet."""


@dataclass(frozen=True)
class ProjectConfig:
    project: str
    adapter: Adapter
    baseline: Arm
    candidate: Arm
    margin_pp: float
    alpha: float


def load_config(path: str | Path) -> ProjectConfig:
    path = Path(path)
    try:
        text = path.read_text()
    except OSError as e:
        raise ConfigLoadError(f"{path}: could not read file: {e}") from e
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ConfigLoadError(f"{path}: invalid YAML: {e}") from e

    if not isinstance(raw, dict):
        raise ConfigLoadError(f"{path}: config file must be a YAML mapping")

    project = _require_str(raw, "project", context=str(path))
    adapter_block = _require_mapping(raw, "adapter", context=str(path))
    adapter = _build_adapter(adapter_block, context=f"{path}: adapter")

    policy = raw.get("policy", {})
    if not isinstance(policy, dict):
        raise ConfigLoadError(f"{path}: 'policy' must be a mapping")
    margin_pp = _optional_number(policy, "margin_pp", _DEFAULT_MARGIN_PP, context=f"{path}: policy")
    alpha = _optional_number(policy, "alpha", _DEFAULT_ALPHA, context=f"{path}: policy")

    configs = _require_mapping(raw, "configs", context=str(path))
    baseline = _build_arm("baseline", configs, adapter, context=str(path))
    candidate = _build_arm("candidate", configs, adapter, context=str(path))

    return ProjectConfig(
        project=project,
        adapter=adapter,
        baseline=baseline,
        candidate=candidate,
        margin_pp=margin_pp,
        alpha=alpha,
    )


def _build_arm(name: str, configs: Mapping[str, Any], adapter: Adapter, *, context: str) -> Arm:
    entry = configs.get(name)
    if not isinstance(entry, dict):
        raise ConfigLoadError(f"{context}: configs.{name} is required and must be a mapping")
    overrides = {k: v for k, v in entry.items() if k != "label"}
    return Arm(name=name, adapter=adapter, overrides=overrides)


def _build_adapter(block: Mapping[str, Any], *, context: str) -> Adapter:
    adapter_type = _require_str(block, "type", context=context)

    if adapter_type == "http":
        url = _require_str(block, "url", context=context)
        return HttpAdapter(url)

    if adapter_type == "cli":
        command = block.get("command")
        if not isinstance(command, list) or not command or not all(isinstance(c, str) for c in command):
            raise ConfigLoadError(f"{context}: 'command' must be a non-empty list of strings")
        return CliAdapter(command)

    if adapter_type == "python":
        target = _require_str(block, "target", context=context)
        return PythonAdapter(_resolve_target(target, context=context))

    raise ConfigLoadError(
        f"{context}: adapter type {adapter_type!r} is not implemented yet "
        "(supported: cli, http, python)"
    )


def _resolve_target(target: str, *, context: str) -> Any:
    if ":" not in target:
        raise ConfigLoadError(f"{context}: 'target' must be 'module.path:attr', got {target!r}")
    module_path, _, attr_path = target.partition(":")
    try:
        obj: Any = importlib.import_module(module_path)
    except ImportError as e:
        raise ConfigLoadError(f"{context}: could not import module {module_path!r}: {e}") from e
    for attr in attr_path.split("."):
        try:
            obj = getattr(obj, attr)
        except AttributeError as e:
            raise ConfigLoadError(f"{context}: {target!r} has no attribute {attr!r}: {e}") from e
    return obj


def _require(mapping: Mapping[str, Any], key: str, *, context: str = "") -> Any:
    if key not in mapping:
        raise ConfigLoadError(f"{context}: missing required field {key!r}")
    return mapping[key]


def _require_str(mapping: Mapping[str, Any], key: str, *, context: str = "") -> str:
    value = _require(mapping, key, context=context)
    if not isinstance(value, str):
        raise ConfigLoadError(f"{context}: {key!r} must be a string")
    return value


def _require_mapping(mapping: Mapping[str, Any], key: str, *, context: str = "") -> dict:
    value = _require(mapping, key, context=context)
    if not isinstance(value, dict):
        raise ConfigLoadError(f"{context}: {key!r} must be a mapping")
    return value


def _optional_number(mapping: Mapping[str, Any], key: str, default: float, *, context: str) -> float:
    if key not in mapping:
        return default
    value = mapping[key]
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ConfigLoadError(f"{context}: {key!r} must be a number")
    return float(value)
