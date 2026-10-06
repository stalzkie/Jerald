from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import click

from jerald import __version__
from jerald.adapters.base import AdapterInfrastructureError
from jerald.config.loader import ConfigLoadError, load_config
from jerald.orchestrator.core import Orchestrator
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


if __name__ == "__main__":
    main()
