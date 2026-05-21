# Sandbox Controller

This package reconciles each `Sandbox` CR with its owned Pod and status. It is
controller logic, not the sandbox-manager request API.

## Responsibilities

- Register the reconciler only when the Sandbox feature gate and CRD discovery allow it.
- Reconcile Sandbox and same-named Pod events through expectations, finalizers, timeout handling, phase transitions, and status updates.
- Keep top-level files focused on orchestration, event handling, and metrics.
- Keep Pod lifecycle actions, pause/resume, in-place update, lifecycle hooks, and post-recreate initialization inside `core`.

## Dependency Direction

The sandbox-manager (E2B API layer) depends on the controller, not the other way around.
When reasoning about controller behavior, do NOT consider sandbox-manager or E2B API
semantics. The controller is the source of truth for sandbox lifecycle; upper layers
conform to the contracts it establishes.

## Local Guidance

- Preserve the split between reconcile orchestration in this package and Pod control/status mutation in `core`.
- When adding a phase or condition, update status calculation, control handling, metrics, and pod event filtering where relevant.
- Use expectations around Pod create/delete and resource-version-sensitive writes instead of assuming informer cache freshness.
- Keep feature-gate behavior in `Add` and event handlers intact.
- For in-place updates, reject immutable template changes and preserve vertical resize compatibility handling.

## Auto-Pause

The auto-pause branch in `Reconcile` is **atomic**: when `canFlipPausedTrue`
holds, refresh `Spec.PauseTime` AND flip `Spec.Paused = true` in the same
patch. Otherwise do nothing — never write a partial pause action.

`canFlipPausedTrue` requires `Status.Phase == Running` and
`Conditions[Ready] == True` for at least `autoPauseReadyStableGrace`. This
guards against the asymmetric Resume race in sandbox-manager: `Resume()` flips
`Spec.Paused = false` but does NOT write `Spec.PauseTime`; the new
`PauseTime` is only written later by `updateConnectTimeout`. Between those
two writes the CR is transiently observable as `{Paused=false,
PauseTime=stale, Phase ∈ {Paused, Resuming, Running w/ fresh Ready}}`.
Without the gate, the controller would auto-pause the in-transition sandbox
and break the resume.

When refreshing, `Spec.PauseTime` adopts `Spec.ShutdownTime` if it is still
in the future, otherwise falls back to `now + 1000y` (mirroring
`pkg/servers/e2b/pause_resume.go::buildPauseTimeoutOptions`). The sentinel
value is not load-bearing — what matters is that a subsequent Resume cannot
observe a stale deadline.

Use `client.MergeFromWithOptions(box, client.MergeFromWithOptimisticLock{})`
so a patch that loses the optimistic-lock race against a concurrent writer
surfaces as 409 and is requeued for re-evaluation rather than silently
overwriting freshly-written state. When the gate fails, set a short
`RequeueAfter` so the next reconcile re-evaluates promptly.
