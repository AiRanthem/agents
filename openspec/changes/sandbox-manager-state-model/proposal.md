## Why

The current shared five-value Sandbox state helper both hides distinctions required by sandbox-manager and leaks SandboxSet-specific policy into unrelated components. The internal model must become a sandbox-manager-only contract while Controller, SandboxSet, cache, routing, and E2B retain purpose-specific behavior.

## What Changes

- **BREAKING (internal API):** replace the shared five-state helper with a sandbox-manager-owned eight-state model: `claimable`, `running`, `pausing`, `paused`, `resuming`, `unready`, `terminating`, and `completed`.
- Make `completed` the only terminal state. Merge successful and failed workload completion into it, and merge recycling, reserved-failed retention, and other accepted removal flows into non-terminal `terminating`.
- Add `SandboxStateObservation` under `pkg/sandbox-manager/infra`; make `infra.Sandbox.GetState()` return that observation and keep CR interpretation in an unexported, explicit-time function inside `pkg/sandbox-manager/infra/sandboxcr`.
- Add `IsSandboxCreating` and `IsSandboxAvailable` to `pkg/controller/sandboxset` with the existing pool semantics. SandboxSet, cache, and sandboxcr claim selection use those helpers without treating them as sandbox-manager state.
- Replace `Sandbox.Phase()` plus `Sandbox.IsRecycleEnabled()` with one `Sandbox.IsRecyclable()` capability that preserves the current recycle predicate without exposing raw Controller phase.
- **BREAKING (internal Route API):** replace lifecycle-valued Route behavior with an explicit `Allow`, `Deny`, or `Delete` action selected by each route producer. Preserve mixed-version rollout through a compatibility-only wire `state` field; route storage and data-plane decisions use only Action.
- Keep public E2B Sandbox state limited to `running` and `paused`. Add stable unavailable reasons `SandboxNotFound`, `SandboxTemporarilyUnavailable`, `SandboxCompleted`, and `SandboxTerminating` without leaking internal states into response bodies.
- **BREAKING (E2B observation behavior):** keep stable `running`/`paused` observations compatible, but change claimed Upgrading, Recycling, empty-phase, and unsupported-phase observations that currently fall back to HTTP 200 `paused` into the applicable HTTP 404 unavailable result.
- Migrate all consumers atomically in one change and remove `pkg/utils.GetSandboxState` plus the five `api/v1alpha1.SandboxState*` constants after their final use.

## Capabilities

### New Capabilities

- `sandbox-manager-state-model`: sandbox-manager-only vocabulary, deterministic CR observation, infra boundary, and recycle capability.
- `sandboxset-pool-classification`: SandboxSet creating/available helpers and behavior-preserving controller/cache adoption.
- `sandbox-route-action`: producer-selected route action, forwarding/deletion behavior, and mixed-version wire compatibility.
- `e2b-sandbox-lifecycle`: public state projection, stable unavailable reasons, and lifecycle-aware operation gates.

### Modified Capabilities

None. This repository has no archived OpenSpec capability specifications.

## Impact

- `pkg/sandbox-manager/infra` and `pkg/sandbox-manager/infra/sandboxcr` own the state contract and CR interpretation.
- SandboxSet, cache, claim selection, waiters, proxy, Gateway, sandbox-manager, web errors, and E2B handlers migrate in one atomic implementation.
- `api/v1alpha1` loses derived-state string constants but gains no serialized lifecycle field or CRD schema change.
- Route JSON gains `action`; the legacy `state` member remains compatibility-only during rolling upgrade.
- Public Sandbox state enum values remain `running` and `paused`, but transition visibility is intentionally not fully backward compatible: several legacy 200 `paused` fallbacks become reasoned 404 responses. Error bodies gain an additive optional `reason`.
- Controller in-place update phases, reasons, mutation mechanics, retry behavior, quota liveness, route identity, peer topology, and storage freshness algorithms are not redesigned.
