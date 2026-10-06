from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from jerald.adapters.base import Step, TrialResult, Usage
from jerald.analysis.compare import Verdict
from jerald.orchestrator.core import TrialRecord
from jerald.scorers.base import ScoreResult

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    project TEXT NOT NULL,
    suite_name TEXT NOT NULL,
    suite_version INTEGER NOT NULL,
    seed INTEGER NOT NULL,
    margin_pp REAL,
    alpha REAL NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT NOT NULL,
    verdict_label TEXT,
    verdict_effect_pp REAL,
    verdict_ci_low_pp REAL,
    verdict_ci_high_pp REAL
);

CREATE TABLE IF NOT EXISTS trials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    task_id TEXT NOT NULL,
    arm_name TEXT NOT NULL,
    trial_index INTEGER NOT NULL,
    seed INTEGER NOT NULL,
    outcome TEXT NOT NULL,
    passed INTEGER NOT NULL,
    final_message TEXT,
    model_reported TEXT,
    usage_input_tokens INTEGER NOT NULL,
    usage_output_tokens INTEGER NOT NULL,
    usage_cost_usd REAL NOT NULL,
    trajectory_json TEXT NOT NULL,
    scores_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS baselines (
    name TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    saved_at TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class StoredRun:
    run_id: str
    kind: str
    project: str
    suite_name: str
    suite_version: int
    seed: int
    alpha: float
    started_at: datetime
    ended_at: datetime
    verdict: Verdict | None
    trials: Sequence[TrialRecord]


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    kind: str
    project: str
    suite_name: str
    started_at: datetime
    verdict_label: str | None
    verdict_effect_pp: float | None


@dataclass(frozen=True)
class BaselineSummary:
    name: str
    run_id: str
    saved_at: datetime
    project: str
    suite_name: str


class Store:
    def __init__(self, path: str | Path) -> None:
        self._connection = sqlite3.connect(str(path))
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.executescript(_SCHEMA)
        self._connection.commit()

    def journal_mode(self) -> str:
        return self._connection.execute("PRAGMA journal_mode").fetchone()[0]

    def save_run(
        self,
        *,
        kind: str,
        project: str,
        suite_name: str,
        suite_version: int,
        seed: int,
        alpha: float,
        started_at: datetime,
        ended_at: datetime,
        trials: Sequence[TrialRecord],
        verdict: Verdict | None = None,
    ) -> str:
        run_id = str(uuid4())
        self._connection.execute(
            """
            INSERT INTO runs (
                run_id, kind, project, suite_name, suite_version, seed, margin_pp, alpha,
                started_at, ended_at, verdict_label, verdict_effect_pp,
                verdict_ci_low_pp, verdict_ci_high_pp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id, kind, project, suite_name, suite_version, seed,
                verdict.margin_pp if verdict else None, alpha,
                started_at.isoformat(), ended_at.isoformat(),
                verdict.label if verdict else None,
                verdict.effect_pp if verdict else None,
                verdict.ci_low_pp if verdict else None,
                verdict.ci_high_pp if verdict else None,
            ),
        )
        self._connection.executemany(
            """
            INSERT INTO trials (
                run_id, task_id, arm_name, trial_index, seed, outcome, passed,
                final_message, model_reported, usage_input_tokens, usage_output_tokens,
                usage_cost_usd, trajectory_json, scores_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    run_id, r.task_id, r.arm_name, r.trial_index, r.seed, r.trial.outcome,
                    int(r.passed), r.trial.final_message, r.trial.model_reported,
                    r.trial.usage.input_tokens, r.trial.usage.output_tokens,
                    r.trial.usage.cost_usd,
                    json.dumps([asdict(step) for step in r.trial.trajectory]),
                    json.dumps([asdict(score) for score in r.scores]),
                )
                for r in trials
            ],
        )
        self._connection.commit()
        return run_id

    def get_run(self, run_id: str) -> StoredRun | None:
        row = self._connection.execute(
            "SELECT * FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            return None
        columns = [c[0] for c in self._connection.execute("SELECT * FROM runs").description]
        run = dict(zip(columns, row, strict=True))

        trial_rows = self._connection.execute(
            "SELECT * FROM trials WHERE run_id = ? ORDER BY task_id, arm_name, trial_index",
            (run_id,),
        ).fetchall()
        trial_columns = [
            c[0] for c in self._connection.execute("SELECT * FROM trials").description
        ]
        trials = [
            _row_to_trial_record(dict(zip(trial_columns, trial_row, strict=True)))
            for trial_row in trial_rows
        ]

        verdict = (
            Verdict(
                label=run["verdict_label"],
                effect_pp=run["verdict_effect_pp"],
                ci_low_pp=run["verdict_ci_low_pp"],
                ci_high_pp=run["verdict_ci_high_pp"],
                margin_pp=run["margin_pp"],
            )
            if run["verdict_label"] is not None
            else None
        )
        return StoredRun(
            run_id=run["run_id"],
            kind=run["kind"],
            project=run["project"],
            suite_name=run["suite_name"],
            suite_version=run["suite_version"],
            seed=run["seed"],
            alpha=run["alpha"],
            started_at=datetime.fromisoformat(run["started_at"]),
            ended_at=datetime.fromisoformat(run["ended_at"]),
            verdict=verdict,
            trials=trials,
        )

    def list_runs(self) -> Sequence[RunSummary]:
        rows = self._connection.execute(
            "SELECT run_id, kind, project, suite_name, started_at, verdict_label, "
            "verdict_effect_pp FROM runs ORDER BY started_at DESC"
        ).fetchall()
        return [
            RunSummary(
                run_id=row[0], kind=row[1], project=row[2], suite_name=row[3],
                started_at=datetime.fromisoformat(row[4]), verdict_label=row[5],
                verdict_effect_pp=row[6],
            )
            for row in rows
        ]

    def save_baseline(self, *, name: str, run_id: str, saved_at: datetime) -> None:
        self._connection.execute(
            "INSERT OR REPLACE INTO baselines (name, run_id, saved_at) VALUES (?, ?, ?)",
            (name, run_id, saved_at.isoformat()),
        )
        self._connection.commit()

    def get_baseline(self, name: str) -> StoredRun | None:
        row = self._connection.execute(
            "SELECT run_id FROM baselines WHERE name = ?", (name,)
        ).fetchone()
        if row is None:
            return None
        return self.get_run(row[0])

    def list_baselines(self) -> Sequence[BaselineSummary]:
        rows = self._connection.execute(
            """
            SELECT b.name, b.run_id, b.saved_at, r.project, r.suite_name
            FROM baselines b JOIN runs r ON r.run_id = b.run_id
            ORDER BY b.saved_at DESC
            """
        ).fetchall()
        return [
            BaselineSummary(
                name=row[0], run_id=row[1], saved_at=datetime.fromisoformat(row[2]),
                project=row[3], suite_name=row[4],
            )
            for row in rows
        ]

    def close(self) -> None:
        self._connection.close()


def _row_to_trial_record(row: dict) -> TrialRecord:
    trajectory = [Step(**step) for step in json.loads(row["trajectory_json"])]
    scores = [ScoreResult(**score) for score in json.loads(row["scores_json"])]
    trial = TrialResult(
        trial_id=f"{row['task_id']}:{row['arm_name']}:{row['trial_index']}",
        task_id=row["task_id"],
        outcome=row["outcome"],
        final_message=row["final_message"],
        trajectory=trajectory,
        usage=Usage(
            input_tokens=row["usage_input_tokens"],
            output_tokens=row["usage_output_tokens"],
            cost_usd=row["usage_cost_usd"],
        ),
        model_reported=row["model_reported"],
    )
    return TrialRecord(
        task_id=row["task_id"],
        arm_name=row["arm_name"],
        trial_index=row["trial_index"],
        seed=row["seed"],
        trial=trial,
        scores=scores,
        passed=bool(row["passed"]),
    )
