from __future__ import annotations

from jerald.adapters.base import TrialResult
from jerald.scorers.base import ScoreResult


def exact(expected: str):
    class _Exact:
        def score(self, trial: TrialResult) -> ScoreResult:
            passed = trial.final_message == expected
            return ScoreResult(
                scorer_id="exact",
                passed=passed,
                value=1.0 if passed else 0.0,
                evidence=f"final_message={trial.final_message!r}",
            )

    return _Exact()


def regex(pattern: str):
    import re as _re

    compiled = _re.compile(pattern)

    class _Regex:
        def score(self, trial: TrialResult) -> ScoreResult:
            text = trial.final_message or ""
            match = compiled.search(text)
            return ScoreResult(
                scorer_id="regex",
                passed=match is not None,
                value=1.0 if match else 0.0,
                evidence=f"final_message={text!r}",
            )

    return _Regex()


def json_schema(schema: dict):
    import json as _json

    import jsonschema as _jsonschema

    validator = _jsonschema.Draft202012Validator(schema)

    class _JsonSchema:
        def score(self, trial: TrialResult) -> ScoreResult:
            text = trial.final_message or ""
            try:
                instance = _json.loads(text)
            except ValueError as exc:
                return ScoreResult(
                    scorer_id="json_schema",
                    passed=False,
                    value=0.0,
                    evidence=f"final_message is not valid JSON: {exc}",
                )

            errors = list(validator.iter_errors(instance))
            passed = not errors
            evidence = "matches schema" if passed else "; ".join(e.message for e in errors)
            return ScoreResult(
                scorer_id="json_schema",
                passed=passed,
                value=1.0 if passed else 0.0,
                evidence=evidence,
            )

    return _JsonSchema()
