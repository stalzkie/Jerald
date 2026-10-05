from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from jerald.adapters.base import TrialResult


@dataclass(frozen=True)
class ScoreResult:
    scorer_id: str
    passed: bool
    value: float
    evidence: str
    required: bool = True


class Scorer(Protocol):
    def score(self, trial: TrialResult) -> ScoreResult: ...
