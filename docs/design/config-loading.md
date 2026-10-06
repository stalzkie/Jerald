# Config loading — deep module design

Sibling to `docs/design/suite-loading.md`, same reasoning: parses `jerald.yaml` (the spec's
§"Configuration file") into exactly what the Orchestrator needs on the Arm side, the way the
suite loader supplies the Task side. Together the two loaders produce everything
`Orchestrator.run_comparison` takes except `trials_per_task` is the suite's, not this file's.

## Scope

```python
@dataclass(frozen=True)
class ProjectConfig:
    project: str
    adapter: Adapter
    baseline: Arm
    candidate: Arm
    margin_pp: float
    alpha: float


class ConfigLoadError(Exception): ...


def load_config(path: str | Path) -> ProjectConfig: ...
```

**One Adapter, two Arms.** `adapter:` describes one physical endpoint/process/object; the same
AUT serves both arms, told which Configuration to behave as via the `overrides` sent on each
`run_trial` call — exactly the Adapter contract's Request field, "`overrides`: Factors to vary
for this arm, such as `model`". So `load_config` builds the `Adapter` once and wraps it in two
`Arm`s, one per `configs.baseline`/`configs.candidate` entry.

**`label` is excluded from `overrides`.** The spec's Factor dimensions are exactly six: model,
prompt, tools, retrieval, parameters, code revision (`CONTEXT.md`). `label` (`main@a1b2c3`,
`pr-481`) is display metadata, not a Factor — forwarding it to the AUT inside `overrides` would
send the adapter contract a field it never promised to understand. It's popped out before
building each Arm's `overrides` dict; nothing downstream currently reads it (no reporting layer
exists yet), so it's dropped rather than threaded somewhere with no consumer, same call as
`suite-loading.md`'s on `tags`/`fixtures`.

**Adapter types.** `http` (`url` → `HttpAdapter`) and `cli` (`command: [...]` → `CliAdapter`) map
directly onto what's built. `python` needs a way to name an in-process object from YAML, which
the spec doesn't specify a shape for — this picks the standard import-string convention
(`target: "package.module:attr"`, the same shape Gunicorn/Celery/entry-points use), resolved via
`importlib.import_module` plus a dotted `getattr` walk, then wrapped in `PythonAdapter`. `mcp`
raises `ConfigLoadError` naming it not implemented yet — same pattern as the suite loader's
unsupported scorer types — since no `McpAdapter` exists.

**`policy` fields consumed vs. not.** Only `margin_pp` and `alpha` are read (both optional,
defaulting to 3.0/0.05 — the Q2-decided default, same as `compare()`'s own default). Not parsed,
since nothing consumes them in this fixed-n slice: `min_trials`/`max_trials` (the sequential
rounds engine — `plan`'s job — isn't built), `budget_usd` (no cost tracking exists; `Usage` is
hardcoded to zero everywhere), `gate.critical_slices` (needs `tags`, which the suite loader
doesn't parse yet for the same reason). Same discipline as the suite loader: don't store data
nothing reads.

## Trade-offs

High leverage: `load_suite(...)` + `load_config(...)` together are the entire input side of
`jerald compare`'s eventual CLI wiring — that command becomes "load both, call
`Orchestrator.run_comparison`, print the verdict." Thin spot, deliberately: `configs` only
supports exactly the keys `baseline` and `candidate` (not the 4-8 arms factorial `attribute` runs
need per `CONTEXT.md`) — the Orchestrator itself is a two-arm `run_comparison` for this slice, so
a config loader that promised more arms than the Orchestrator can consume would be the same kind
of unconsumed-data mistake flagged above.
