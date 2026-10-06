from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

from jerald.adapters.base import Adapter, AdapterInfrastructureError, TaskSpec, TrialResult
from jerald.analysis.compare import Verdict, compare
from jerald.scorers.base import Scorer


@dataclass(frozen=True)
class Task:
    spec: TaskSpec
    scorers: Sequence[Scorer]


@dataclass(frozen=True)
class Arm:
    name: str
    adapter: Adapter
    overrides: Mapping[str, Any]


@dataclass(frozen=True)
class ComparisonResult:
    verdict: Verdict
    baseline_scores: Mapping[str, Sequence[bool]]
    candidate_scores: Mapping[str, Sequence[bool]]


def _default_backoff(attempt: int) -> None:
    time.sleep(min(2**attempt * 0.1, 2.0))


def _task_passed(scorers: Sequence[Scorer], trial: TrialResult) -> bool:
    results = [s.score(trial) for s in scorers]
    return all(r.passed for r in results if r.required)


class Orchestrator:
    def __init__(
        self,
        *,
        max_concurrency: int = 4,
        max_retries: int = 3,
        backoff: Callable[[int], None] | None = None,
    ) -> None:
        self._max_concurrency = max_concurrency
        self._max_retries = max_retries
        self._backoff = backoff if backoff is not None else _default_backoff

    def run_comparison(
        self,
        tasks: Sequence[Task],
        baseline: Arm,
        candidate: Arm,
        trials_per_task: int,
        seed: int = 0,
        margin_pp: float = 3.0,
        alpha: float = 0.05,
        n_bootstrap: int = 10_000,
    ) -> ComparisonResult:
        rng = random.Random(seed)
        env_seeds: dict[tuple[str, int], int] = {
            (task.spec.task_id, i): rng.randrange(2**32)
            for task in tasks
            for i in range(trials_per_task)
        }

        # Shared env seeds above pair baseline/candidate at the same (task, trial
        # index); the shuffle below only changes submission order, not seeds, so
        # it interleaves arms/tasks without disturbing the pairing.
        jobs: list[tuple[Task, Arm, int]] = [
            (task, arm, i)
            for task in tasks
            for i in range(trials_per_task)
            for arm in (baseline, candidate)
        ]
        rng.shuffle(jobs)

        baseline_scores: dict[str, list[bool]] = {task.spec.task_id: [] for task in tasks}
        candidate_scores: dict[str, list[bool]] = {task.spec.task_id: [] for task in tasks}
        lock = threading.Lock()

        def run_job(task: Task, arm: Arm, trial_index: int) -> None:
            trial_id = f"{task.spec.task_id}:{arm.name}:{trial_index}"
            env_seed = env_seeds[(task.spec.task_id, trial_index)]
            trial = self._execute_with_retry(arm.adapter, task.spec, trial_id, env_seed, arm.overrides)
            passed = _task_passed(task.scorers, trial)
            target = baseline_scores if arm is baseline else candidate_scores
            with lock:
                target[task.spec.task_id].append(passed)

        # A raised AdapterInfrastructureError propagates as soon as any job's
        # future completes with it; threads already running cannot be killed
        # (mirrors the lesson in PythonAdapter), so the `with` block still waits
        # for every submitted job to finish before returning control.
        with ThreadPoolExecutor(max_workers=self._max_concurrency) as pool:
            futures = [pool.submit(run_job, *job) for job in jobs]
            for future in as_completed(futures):
                future.result()

        verdict = compare(
            baseline_scores=baseline_scores,
            candidate_scores=candidate_scores,
            margin_pp=margin_pp,
            alpha=alpha,
            n_bootstrap=n_bootstrap,
            seed=seed,
        )
        return ComparisonResult(
            verdict=verdict,
            baseline_scores=baseline_scores,
            candidate_scores=candidate_scores,
        )

    def _execute_with_retry(
        self,
        adapter: Adapter,
        task_spec: TaskSpec,
        trial_id: str,
        seed: int,
        overrides: Mapping[str, Any],
    ) -> TrialResult:
        for attempt in range(self._max_retries):
            try:
                return adapter.run_trial(task_spec, trial_id, seed, overrides)
            except AdapterInfrastructureError as e:
                if not e.retryable or attempt == self._max_retries - 1:
                    raise
                self._backoff(attempt)
        raise AssertionError("unreachable")
