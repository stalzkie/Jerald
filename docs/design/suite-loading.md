# Suite loading — deep module design

Designed directly, like the Orchestrator: the shape is dictated by what already exists downstream
(`TaskSpec`, outcome `Scorer` factories, the Orchestrator's `Task`) and the spec's own suite YAML
format (§"Suite and config formats"), not an open interface choice.

## Scope

Parses a suite YAML file into `Suite(name, version, tasks, trials_per_task)`, where `tasks` is a
`Sequence[jerald.orchestrator.core.Task]` — ready to hand straight to
`Orchestrator.run_comparison`. Reuses that `Task` type rather than inventing a parallel one.

Only what's already built is parsed:

- **Scorers**: `exact`, `regex`, `json_schema` (the outcome family) and `trajectory` (its first
  slice: `tool_called`/`tool_not_called`/`args_match`, see `docs/design/scorer-and-statistics.md`
  — the only Scorer families that exist). A task naming any other `type` (`efficiency`, `state`,
  `python`, `shell`, judge scorers — all real spec types, none implemented yet) raises
  `SuiteLoadError` naming the unsupported type, rather than silently skipping the task or
  guessing. A scorer-less task is also rejected: with no Scorer, every Trial of it vacuously
  "passes" (`all([]) is True`, per the Orchestrator's own scoring rule) and the task tests
  nothing — a correctness trap worth catching at load time, not silently at report time.
- **Fields consumed**: `suite`, `version`, `defaults.timeout_s`, `defaults.max_steps`,
  `defaults.trials`, each task's `id`, `input.messages`, and optional per-task `timeout_s`/
  `max_steps` overrides (merged with the suite defaults exactly as `TaskSpec`'s docstring
  describes). Each scorer's `type` plus its own keys (`expected`/`pattern`/`schema`/
  `tool_called`/`tool_not_called`/`args_match`) and optional
  `required`.
- **Fields deliberately not parsed — no consumer exists for them yet, so parsing them would
  produce dead data**: `tags` (nothing implements `critical_slices`/gate policy yet), `input.env`
  (`seed`/`fixtures` — the Orchestrator already derives its own per-trial seed per
  `docs/design/orchestrator.md`; `fixtures` needs the sandbox layer, which doesn't exist). These
  get added to `Task`/`TaskSpec` when the feature that reads them gets built, not before.

Added `pyyaml` as the YAML parser — it's the de facto standard choice, nothing to compare it
against.

## Interface

```python
class SuiteLoadError(Exception):
    """The YAML is malformed, missing a required field, has the wrong type for one, or
    names a scorer type nothing implements yet. Always raised with a `path: context: message`
    string pinpointing where — the suite, a specific task, or a specific scorer within it."""


@dataclass(frozen=True)
class Suite:
    name: str
    version: int
    tasks: Sequence[Task]
    trials_per_task: int


def load_suite(path: str | Path) -> Suite: ...
```

## Trade-offs

Every validation failure raises the same `SuiteLoadError` type with a contextual message
(`"suites/x.yaml: tasks[2] (ambiguous-request): scorers[0]: scorer type 'trajectory' is not
implemented yet"`) rather than letting `KeyError`/`TypeError`/`yaml.YAMLError` leak through with a
Python traceback a suite author can't act on — one error type for the CLI to catch, one message
shape for a human to read. Deliberately thin: no JSON-Schema-based YAML validation library:
the field set is small enough that explicit checks stay more readable than a schema document,
and every check already needs a custom contextual message anyway.
