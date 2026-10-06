import json
import sys
from pathlib import Path

import pytest

from jerald.adapters.cli_adapter import CliAdapter
from jerald.adapters.http_adapter import HttpAdapter
from jerald.adapters.python_adapter import PythonAdapter
from jerald.config.loader import ConfigLoadError, load_config


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "jerald.yaml"
    path.write_text(text)
    return path


_HTTP_CONFIG = """
project: support-agent
adapter:
  type: http
  url: http://localhost:8000/invoke
policy:
  alpha: 0.05
  margin_pp: 3
configs:
  baseline:
    label: main@a1b2c3
    model: example-model-2026-09
    params: {temperature: 0.2}
  candidate:
    label: pr-481
    model: example-model-2026-10
    params: {temperature: 0.2}
"""


def test_load_config_builds_http_adapter_with_margin_and_alpha(tmp_path: Path) -> None:
    config = load_config(_write(tmp_path, _HTTP_CONFIG))

    assert config.project == "support-agent"
    assert isinstance(config.adapter, HttpAdapter)
    assert config.adapter.url == "http://localhost:8000/invoke"
    assert config.margin_pp == 3.0
    assert config.alpha == 0.05


def test_load_config_excludes_label_from_overrides_and_keeps_factor_values(tmp_path: Path) -> None:
    config = load_config(_write(tmp_path, _HTTP_CONFIG))

    assert config.baseline.name == "baseline"
    assert "label" not in config.baseline.overrides
    assert config.baseline.overrides["model"] == "example-model-2026-09"
    assert config.candidate.name == "candidate"
    assert config.candidate.overrides["model"] == "example-model-2026-10"
    assert config.baseline.adapter is config.candidate.adapter


def test_load_config_defaults_margin_and_alpha_when_policy_is_absent(tmp_path: Path) -> None:
    text = _HTTP_CONFIG.replace("policy:\n  alpha: 0.05\n  margin_pp: 3\n", "")
    config = load_config(_write(tmp_path, text))

    assert config.margin_pp == 3.0
    assert config.alpha == 0.05


def test_load_config_builds_cli_adapter_from_command_list(tmp_path: Path) -> None:
    text = _HTTP_CONFIG.replace(
        "adapter:\n  type: http\n  url: http://localhost:8000/invoke\n",
        f"adapter:\n  type: cli\n  command: [{json.dumps(sys.executable)}, \"-c\", \"pass\"]\n",
    )
    config = load_config(_write(tmp_path, text))

    assert isinstance(config.adapter, CliAdapter)
    assert config.adapter.command == [sys.executable, "-c", "pass"]


def test_load_config_builds_python_adapter_from_target_import_string(tmp_path: Path) -> None:
    text = _HTTP_CONFIG.replace(
        "adapter:\n  type: http\n  url: http://localhost:8000/invoke\n",
        "adapter:\n  type: python\n  target: tests.config._fixture_agent:echo_agent\n",
    )
    config = load_config(_write(tmp_path, text))

    assert isinstance(config.adapter, PythonAdapter)
    assert config.adapter.aut.__class__.__name__ == "EchoAgent"


def test_load_config_raises_for_unsupported_adapter_type(tmp_path: Path) -> None:
    text = _HTTP_CONFIG.replace(
        "adapter:\n  type: http\n  url: http://localhost:8000/invoke\n",
        "adapter:\n  type: mcp\n",
    )
    with pytest.raises(ConfigLoadError, match="mcp"):
        load_config(_write(tmp_path, text))


def test_load_config_raises_when_baseline_config_is_missing(tmp_path: Path) -> None:
    text = _HTTP_CONFIG.replace(
        "  baseline:\n    label: main@a1b2c3\n    model: example-model-2026-09\n"
        "    params: {temperature: 0.2}\n",
        "",
    )
    with pytest.raises(ConfigLoadError, match="baseline"):
        load_config(_write(tmp_path, text))


def test_load_config_raises_on_invalid_yaml_syntax(tmp_path: Path) -> None:
    with pytest.raises(ConfigLoadError):
        load_config(_write(tmp_path, "project: [unterminated"))
