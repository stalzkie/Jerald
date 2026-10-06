from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import click

from jerald import __version__
from jerald.adapters.base import AdapterInfrastructureError
from jerald.analysis.compare import compare as run_compare
from jerald.config.loader import ConfigLoadError, load_config
from jerald.orchestrator.core import Arm, Orchestrator, TrialRecord
from jerald.store.store import Store
from jerald.suite.loader import SuiteLoadError, load_suite

EXIT_NO_REGRESSION = 0
EXIT_REGRESSION = 1
EXIT_INCONCLUSIVE = 2
EXIT_USAGE_ERROR = 3
EXIT_INFRASTRUCTURE_FAILURE = 4

_EXIT_CODE_BY_VERDICT_LABEL = {
    "REGRESSION": EXIT_REGRESSION,
    "INCONCLUSIVE": EXIT_INCONCLUSIVE,
    "NO_REGRESSION": EXIT_NO_REGRESSION,
    "IMPROVEMENT": EXIT_NO_REGRESSION,
}


@click.group()
@click.version_option(__version__, prog_name="jerald")
def main() -> None:
    """Jerald: a statistical regression harness for AI agents."""


@main.command()
@click.option(
    "--config", "config_path", default="jerald.yaml", show_default=True,
    type=click.Path(path_type=Path), help="Path to jerald.yaml.",
)
@click.option(
    "--suite", "suite_path", default=None,
    type=click.Path(path_type=Path), help="Path to the suite YAML file.",
)
@click.option("--margin-pp", default=None, type=float, help="Override the config's margin_pp.")
@click.option("--alpha", default=None, type=float, help="Override the config's alpha.")
@click.option("--seed", default=0, type=int, show_default=True, help="Top-level comparison seed.")
@click.option(
    "--parallel", default=4, type=int, show_default=True, help="Maximum concurrent trials.",
)
@click.option("--dry-run", is_flag=True, help="Print the plan without running any trials.")
@click.option(
    "--out", "out_path", default=None,
    type=click.Path(path_type=Path), help="Write the verdict as JSON to this path.",
)
@click.option(
    "--store", "store_path", default=None,
    type=click.Path(path_type=Path), help="Persist the run to this SQLite store.",
)
@click.pass_context
def compare(
    ctx: click.Context,
    config_path: Path,
    suite_path: Path | None,
    margin_pp: float | None,
    alpha: float | None,
    seed: int,
    parallel: int,
    dry_run: bool,
    out_path: Path | None,
    store_path: Path | None,
) -> None:
    """Compare two arms using the fixed-n statistics engine.

    This is the fixed-n slice only: there is no sequential rounds engine yet,
    so every task gets exactly the suite's `defaults.trials` trials per arm
    regardless of how clear the result looks early. --max-trials,
    --budget-usd, and --fixed-n from the spec's CLI reference are not
    implemented: there is no sequential engine to opt out of yet, and no
    cost tracking to cap.

    --store is opt-in (no default path): pass it to persist the run and its
    trials to a SQLite store and print the run_id; omit it to only print the
    verdict, as before.
    """
    if suite_path is None:
        click.echo("Error: --suite is required.", err=True)
        ctx.exit(EXIT_USAGE_ERROR)

    try:
        project_config = load_config(config_path)
    except ConfigLoadError as e:
        click.echo(f"Error: {e}", err=True)
        ctx.exit(EXIT_USAGE_ERROR)

    try:
        suite = load_suite(suite_path)
    except SuiteLoadError as e:
        click.echo(f"Error: {e}", err=True)
        ctx.exit(EXIT_USAGE_ERROR)

    resolved_margin_pp = margin_pp if margin_pp is not None else project_config.margin_pp
    resolved_alpha = alpha if alpha is not None else project_config.alpha

    if dry_run:
        click.echo(f"suite: {suite.name} (v{suite.version})")
        click.echo(f"tasks: {len(suite.tasks)}")
        click.echo(f"trials per task per arm: {suite.trials_per_task}")
        click.echo(f"margin_pp: {resolved_margin_pp}, alpha: {resolved_alpha}")
        click.echo(f"baseline overrides: {dict(project_config.baseline.overrides)}")
        click.echo(f"candidate overrides: {dict(project_config.candidate.overrides)}")
        click.echo("Cost estimation is not implemented yet; this only shows the plan.")
        ctx.exit(EXIT_NO_REGRESSION)

    orchestrator = Orchestrator(max_concurrency=parallel)
    started_at = datetime.now(UTC)
    try:
        result = orchestrator.run_comparison(
            suite.tasks,
            project_config.baseline,
            project_config.candidate,
            trials_per_task=suite.trials_per_task,
            seed=seed,
            margin_pp=resolved_margin_pp,
            alpha=resolved_alpha,
        )
    except AdapterInfrastructureError as e:
        click.echo(f"Infrastructure failure: {e}", err=True)
        ctx.exit(EXIT_INFRASTRUCTURE_FAILURE)
    ended_at = datetime.now(UTC)

    verdict = result.verdict
    click.echo(
        f"{verdict.label}: effect={verdict.effect_pp:+.2f}pp "
        f"CI=[{verdict.ci_low_pp:+.2f}, {verdict.ci_high_pp:+.2f}]pp margin={verdict.margin_pp}pp"
    )

    if out_path is not None:
        out_path.write_text(json.dumps({
            "label": verdict.label,
            "effect_pp": verdict.effect_pp,
            "ci_low_pp": verdict.ci_low_pp,
            "ci_high_pp": verdict.ci_high_pp,
            "margin_pp": verdict.margin_pp,
        }, indent=2))

    if store_path is not None:
        store = Store(store_path)
        run_id = store.save_run(
            kind="compare",
            project=project_config.project,
            suite_name=suite.name,
            suite_version=suite.version,
            seed=seed,
            alpha=resolved_alpha,
            started_at=started_at,
            ended_at=ended_at,
            trials=result.trials,
            verdict=verdict,
        )
        store.close()
        click.echo(f"run_id: {run_id}")

    ctx.exit(_EXIT_CODE_BY_VERDICT_LABEL[verdict.label])


@main.command()
@click.option(
    "--config", "config_path", default="jerald.yaml", show_default=True,
    type=click.Path(path_type=Path), help="Path to jerald.yaml.",
)
@click.option(
    "--suite", "suite_path", default=None,
    type=click.Path(path_type=Path), help="Path to the suite YAML file.",
)
@click.option(
    "--arm", "arm_name", default="baseline", show_default=True,
    type=click.Choice(["baseline", "candidate"]), help="Which jerald.yaml config to run.",
)
@click.option("--trials", "trials", default=None, type=int, help="Override the suite's defaults.trials.")
@click.option("--seed", default=0, type=int, show_default=True, help="Top-level run seed.")
@click.option(
    "--parallel", default=4, type=int, show_default=True, help="Maximum concurrent trials.",
)
@click.option("--dry-run", is_flag=True, help="Print the plan without running any trials.")
@click.option(
    "--out", "out_path", default=None,
    type=click.Path(path_type=Path), help="Write the per-task pass counts as JSON to this path.",
)
@click.option(
    "--store", "store_path", default=None,
    type=click.Path(path_type=Path), help="Persist the run to this SQLite store.",
)
@click.pass_context
def run(
    ctx: click.Context,
    config_path: Path,
    suite_path: Path | None,
    arm_name: str,
    trials: int | None,
    seed: int,
    parallel: int,
    dry_run: bool,
    out_path: Path | None,
    store_path: Path | None,
) -> None:
    """Run one configuration and store its trials.

    --arm selects which entry of jerald.yaml's `configs:` to run
    (default: baseline). The spec's CLI reference doesn't name this flag --
    there's no jerald baseline/init yet to otherwise supply a default
    Configuration to run, so a selector is the only way to pick one.

    --store is required (not optional, unlike jerald compare's): the
    entire point of jerald run, per the spec, is storing its trials --
    a run that stores nothing would do nothing useful.
    """
    if suite_path is None:
        click.echo("Error: --suite is required.", err=True)
        ctx.exit(EXIT_USAGE_ERROR)

    try:
        project_config = load_config(config_path)
    except ConfigLoadError as e:
        click.echo(f"Error: {e}", err=True)
        ctx.exit(EXIT_USAGE_ERROR)

    try:
        suite = load_suite(suite_path)
    except SuiteLoadError as e:
        click.echo(f"Error: {e}", err=True)
        ctx.exit(EXIT_USAGE_ERROR)

    arm: Arm = project_config.baseline if arm_name == "baseline" else project_config.candidate
    trials_per_task = trials if trials is not None else suite.trials_per_task

    if dry_run:
        click.echo(f"suite: {suite.name} (v{suite.version})")
        click.echo(f"tasks: {len(suite.tasks)}")
        click.echo(f"arm: {arm_name}")
        click.echo(f"trials per task: {trials_per_task}")
        click.echo(f"overrides: {dict(arm.overrides)}")
        ctx.exit(EXIT_NO_REGRESSION)

    if store_path is None:
        click.echo("Error: --store is required.", err=True)
        ctx.exit(EXIT_USAGE_ERROR)

    orchestrator = Orchestrator(max_concurrency=parallel)
    started_at = datetime.now(UTC)
    try:
        result = orchestrator.run_single(suite.tasks, arm, trials_per_task=trials_per_task, seed=seed)
    except AdapterInfrastructureError as e:
        click.echo(f"Infrastructure failure: {e}", err=True)
        ctx.exit(EXIT_INFRASTRUCTURE_FAILURE)
    ended_at = datetime.now(UTC)

    for task_id, scores in result.scores.items():
        click.echo(f"{task_id}: {sum(scores)}/{len(scores)} passed")

    if out_path is not None:
        out_path.write_text(json.dumps(
            {task_id: {"passed": sum(scores), "total": len(scores)}
             for task_id, scores in result.scores.items()},
            indent=2,
        ))

    store = Store(store_path)
    run_id = store.save_run(
        kind="run",
        project=project_config.project,
        suite_name=suite.name,
        suite_version=suite.version,
        seed=seed,
        alpha=project_config.alpha,
        started_at=started_at,
        ended_at=ended_at,
        trials=result.trials,
        verdict=None,
    )
    store.close()
    click.echo(f"run_id: {run_id}")

    ctx.exit(EXIT_NO_REGRESSION)


@main.group()
def baseline() -> None:
    """Save, list, or show a named baseline (a configuration plus its per-task results)."""


@baseline.command("save")
@click.argument("name")
@click.option(
    "--config", "config_path", default="jerald.yaml", show_default=True,
    type=click.Path(path_type=Path), help="Path to jerald.yaml.",
)
@click.option(
    "--suite", "suite_path", default=None,
    type=click.Path(path_type=Path), help="Path to the suite YAML file.",
)
@click.option("--trials", "trials", default=None, type=int, help="Override the suite's defaults.trials.")
@click.option("--seed", default=0, type=int, show_default=True, help="Top-level run seed.")
@click.option(
    "--parallel", default=4, type=int, show_default=True, help="Maximum concurrent trials.",
)
@click.option(
    "--store", "store_path", default=None,
    type=click.Path(path_type=Path), help="SQLite store to save the baseline into.",
)
@click.pass_context
def baseline_save(
    ctx: click.Context,
    name: str,
    config_path: Path,
    suite_path: Path | None,
    trials: int | None,
    seed: int,
    parallel: int,
    store_path: Path | None,
) -> None:
    """Run the baseline Configuration and save its result under NAME.

    Saving again under the same NAME replaces what it points to -- a named
    baseline means "the current main" (or whatever NAME represents), not an
    append-only history of runs by that name.
    """
    if suite_path is None:
        click.echo("Error: --suite is required.", err=True)
        ctx.exit(EXIT_USAGE_ERROR)

    if store_path is None:
        click.echo("Error: --store is required.", err=True)
        ctx.exit(EXIT_USAGE_ERROR)

    try:
        project_config = load_config(config_path)
    except ConfigLoadError as e:
        click.echo(f"Error: {e}", err=True)
        ctx.exit(EXIT_USAGE_ERROR)

    try:
        suite = load_suite(suite_path)
    except SuiteLoadError as e:
        click.echo(f"Error: {e}", err=True)
        ctx.exit(EXIT_USAGE_ERROR)

    trials_per_task = trials if trials is not None else suite.trials_per_task

    orchestrator = Orchestrator(max_concurrency=parallel)
    started_at = datetime.now(UTC)
    try:
        result = orchestrator.run_single(
            suite.tasks, project_config.baseline, trials_per_task=trials_per_task, seed=seed
        )
    except AdapterInfrastructureError as e:
        click.echo(f"Infrastructure failure: {e}", err=True)
        ctx.exit(EXIT_INFRASTRUCTURE_FAILURE)
    ended_at = datetime.now(UTC)

    for task_id, scores in result.scores.items():
        click.echo(f"{task_id}: {sum(scores)}/{len(scores)} passed")

    store = Store(store_path)
    run_id = store.save_run(
        kind="baseline",
        project=project_config.project,
        suite_name=suite.name,
        suite_version=suite.version,
        seed=seed,
        alpha=project_config.alpha,
        started_at=started_at,
        ended_at=ended_at,
        trials=result.trials,
        verdict=None,
    )
    store.save_baseline(name=name, run_id=run_id, saved_at=ended_at)
    store.close()
    click.echo(f"baseline '{name}' saved (run_id: {run_id})")

    ctx.exit(EXIT_NO_REGRESSION)


@baseline.command("list")
@click.option(
    "--store", "store_path", required=True,
    type=click.Path(path_type=Path), help="SQLite store to list baselines from.",
)
def baseline_list(store_path: Path) -> None:
    """List saved baselines, most recently saved first."""
    store = Store(store_path)
    summaries = store.list_baselines()
    store.close()

    if not summaries:
        click.echo("No baselines saved.")
        return

    for s in summaries:
        click.echo(f"{s.name}\t{s.suite_name}\t{s.saved_at.isoformat()}\trun_id={s.run_id}")


@baseline.command("show")
@click.argument("name")
@click.option(
    "--store", "store_path", required=True,
    type=click.Path(path_type=Path), help="SQLite store to read the baseline from.",
)
@click.pass_context
def baseline_show(ctx: click.Context, name: str, store_path: Path) -> None:
    """Show a named baseline's configuration and per-task results."""
    store = Store(store_path)
    stored = store.get_baseline(name)
    store.close()

    if stored is None:
        click.echo(f"Error: no baseline named '{name}'.", err=True)
        ctx.exit(EXIT_USAGE_ERROR)

    click.echo(f"name: {name}")
    click.echo(f"project: {stored.project}")
    click.echo(f"suite: {stored.suite_name} (v{stored.suite_version})")
    click.echo(f"seed: {stored.seed}")
    click.echo(f"saved: {stored.ended_at.isoformat()}")

    for task_id, scores in _scores_by_task(stored.trials).items():
        click.echo(f"{task_id}: {sum(scores)}/{len(scores)} passed")


def _scores_by_task(trials: Sequence[TrialRecord]) -> dict[str, list[bool]]:
    scores: dict[str, list[bool]] = {}
    for r in trials:
        scores.setdefault(r.task_id, []).append(r.passed)
    return scores


@main.command()
@click.option(
    "--baseline", "baseline_name", default=None,
    help="Name of the saved baseline to compare the candidate against.",
)
@click.option(
    "--config", "config_path", default="jerald.yaml", show_default=True,
    type=click.Path(path_type=Path), help="Path to jerald.yaml.",
)
@click.option(
    "--suite", "suite_path", default=None,
    type=click.Path(path_type=Path), help="Path to the suite YAML file.",
)
@click.option("--margin-pp", default=None, type=float, help="Override the config's margin_pp.")
@click.option("--alpha", default=None, type=float, help="Override the config's alpha.")
@click.option("--seed", default=0, type=int, show_default=True, help="Top-level check seed.")
@click.option(
    "--parallel", default=4, type=int, show_default=True, help="Maximum concurrent trials.",
)
@click.option("--dry-run", is_flag=True, help="Print the plan without running any trials.")
@click.option(
    "--out", "out_path", default=None,
    type=click.Path(path_type=Path), help="Write the verdict as JSON to this path.",
)
@click.option(
    "--store", "store_path", default=None,
    type=click.Path(path_type=Path),
    help="SQLite store holding the baseline; this check's run is also recorded there.",
)
@click.pass_context
def check(
    ctx: click.Context,
    baseline_name: str | None,
    config_path: Path,
    suite_path: Path | None,
    margin_pp: float | None,
    alpha: float | None,
    seed: int,
    parallel: int,
    dry_run: bool,
    out_path: Path | None,
    store_path: Path | None,
) -> None:
    """CI wrapper: compare the working tree with a named baseline and set the exit code.

    The candidate Arm is run fresh; the baseline side is read from a
    previously saved `jerald baseline save` run, not re-run. --budget-usd
    and --format from the spec's CLI reference are not implemented: no
    cost tracking exists, and no report renderer beyond this plain-text
    summary plus --out's JSON exists yet.
    """
    if baseline_name is None:
        click.echo("Error: --baseline is required.", err=True)
        ctx.exit(EXIT_USAGE_ERROR)

    if suite_path is None:
        click.echo("Error: --suite is required.", err=True)
        ctx.exit(EXIT_USAGE_ERROR)

    try:
        project_config = load_config(config_path)
    except ConfigLoadError as e:
        click.echo(f"Error: {e}", err=True)
        ctx.exit(EXIT_USAGE_ERROR)

    try:
        suite = load_suite(suite_path)
    except SuiteLoadError as e:
        click.echo(f"Error: {e}", err=True)
        ctx.exit(EXIT_USAGE_ERROR)

    resolved_margin_pp = margin_pp if margin_pp is not None else project_config.margin_pp
    resolved_alpha = alpha if alpha is not None else project_config.alpha

    if dry_run:
        click.echo(f"baseline: {baseline_name}")
        click.echo(f"suite: {suite.name} (v{suite.version})")
        click.echo(f"tasks: {len(suite.tasks)}")
        click.echo(f"trials per task: {suite.trials_per_task}")
        click.echo(f"margin_pp: {resolved_margin_pp}, alpha: {resolved_alpha}")
        click.echo(f"candidate overrides: {dict(project_config.candidate.overrides)}")
        ctx.exit(EXIT_NO_REGRESSION)

    if store_path is None:
        click.echo("Error: --store is required.", err=True)
        ctx.exit(EXIT_USAGE_ERROR)

    store = Store(store_path)
    baseline_run = store.get_baseline(baseline_name)
    if baseline_run is None:
        store.close()
        click.echo(f"Error: no baseline named '{baseline_name}'.", err=True)
        ctx.exit(EXIT_USAGE_ERROR)

    orchestrator = Orchestrator(max_concurrency=parallel)
    started_at = datetime.now(UTC)
    try:
        result = orchestrator.run_single(
            suite.tasks, project_config.candidate,
            trials_per_task=suite.trials_per_task, seed=seed,
        )
    except AdapterInfrastructureError as e:
        store.close()
        click.echo(f"Infrastructure failure: {e}", err=True)
        ctx.exit(EXIT_INFRASTRUCTURE_FAILURE)
    ended_at = datetime.now(UTC)

    baseline_scores = _scores_by_task(baseline_run.trials)
    candidate_scores = dict(result.scores)
    if baseline_scores.keys() != candidate_scores.keys():
        store.close()
        missing = set(baseline_scores) - set(candidate_scores)
        extra = set(candidate_scores) - set(baseline_scores)
        click.echo(
            "Error: the current suite's tasks don't match baseline "
            f"'{baseline_name}''s tasks (missing: {sorted(missing)}, extra: {sorted(extra)}).",
            err=True,
        )
        ctx.exit(EXIT_USAGE_ERROR)

    verdict = run_compare(
        baseline_scores=baseline_scores,
        candidate_scores=candidate_scores,
        margin_pp=resolved_margin_pp,
        alpha=resolved_alpha,
        seed=seed,
    )
    click.echo(
        f"{verdict.label}: effect={verdict.effect_pp:+.2f}pp "
        f"CI=[{verdict.ci_low_pp:+.2f}, {verdict.ci_high_pp:+.2f}]pp margin={verdict.margin_pp}pp"
    )

    if out_path is not None:
        out_path.write_text(json.dumps({
            "label": verdict.label,
            "effect_pp": verdict.effect_pp,
            "ci_low_pp": verdict.ci_low_pp,
            "ci_high_pp": verdict.ci_high_pp,
            "margin_pp": verdict.margin_pp,
        }, indent=2))

    run_id = store.save_run(
        kind="check",
        project=project_config.project,
        suite_name=suite.name,
        suite_version=suite.version,
        seed=seed,
        alpha=resolved_alpha,
        started_at=started_at,
        ended_at=ended_at,
        trials=result.trials,
        verdict=verdict,
    )
    store.close()
    click.echo(f"run_id: {run_id}")

    ctx.exit(_EXIT_CODE_BY_VERDICT_LABEL[verdict.label])


if __name__ == "__main__":
    main()
