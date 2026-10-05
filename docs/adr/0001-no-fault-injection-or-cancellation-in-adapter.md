# Fault injection and cancellation are not part of the Adapter port

The spec's fault-injection feature (`jerald stress`) works by routing the AUT's own model and
tool calls through `JERALD_MODEL_BASE_URL`/`JERALD_TOOL_BASE_URL` proxies, configured via
environment before the AUT runs — not by Jerald's Adapter passing a fault plan into the call.
Budget enforcement is a pre-trial gate using a cost estimate ("before every trial"), not a
reactive kill of a trial already in flight. So `Adapter.run_trial` takes no `fault_plan` and no
cancellation token: both would duplicate control that already lives at the proxy layer and in
the Orchestrator's between-trials budget check, for no requirement the spec actually states —
in-flight cancellation of a single running trial isn't called for anywhere in it.

## Considered options

A parallel design (built while comparing three interface shapes for this seam) added optional
`fault_plan`, `on_step` (streaming), and `cancel_token` fields to the request object, all
defaulting to `None` so unused callers pay nothing. Rejected: fault injection doesn't operate
through this seam at all (see above), so the field would be dead weight; `on_step` streaming
had no grounding in the spec; and cancellation has no motivating requirement given how budget
enforcement is actually specified. Revisit this if a future requirement needs a trial killed
mid-flight — don't restore it preemptively.
