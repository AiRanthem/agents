## Why

The current shared five-value Sandbox state helper hides distinctions required by sandbox-manager
and couples unrelated Controller, cache, Gateway, proxy, and E2B policies. Gateway must not replace
that helper with an independent CR routing policy because new Manager and Gateway versions need one
authoritative route decision for the same Sandbox observation.

This change depends on the `sandbox-provider` extraction and its conservative route-safety
baseline. The provider gives Manager and Gateway one CR observation and route path while Controller
retains separate pool and operation-specific predicates.

## What Changes

- **BREAKING (internal API):** replace the shared five-state helper with a manager-oriented
  eight-state observation: `claimable`, `running`, `pausing`, `paused`, `resuming`, `unready`,
  `terminating`, and `completed`.
- Define the state and observation contract in `pkg/sandboxprovider`; make the shared CR provider's
  `GetState` the only CR-to-state path and keep its explicit-time derivation unexported.
- Keep Controller, SandboxSet, and cache off the eight-state model. Reuse provider-owned pool
  creating and available/claimable predicates while preserving their existing local behavior.
- Replace raw phase plus cleanup checks in Manager with one provider `IsRecyclable` capability that
  includes known Controller preconditions. Treat cleanup metadata as a non-serving request until
  recycling or deletion starts, and require direct deletion if Controller cannot recycle an
  accepted request.
- **BREAKING (internal Route API):** replace lifecycle-valued core Route state with explicit
  `Allow`, `Deny`, or `Delete`. Require both Manager and Gateway to call the same CR provider
  `GetRoute`, which obtains `GetState` and applies the only state-to-action mapping.
- Retain mixed-version compatibility through a wire-only legacy `state` field. New receivers prefer
  Action; support only peers on the prerequisite tombstone and conservative legacy-running
  baseline, and keep every legacy fallback fail-closed.
- Keep public E2B Sandbox state limited to `running` and `paused`. Add stable unavailable reasons
  `SandboxNotFound`, `SandboxTemporarilyUnavailable`, `SandboxCompleted`, and
  `SandboxTerminating` without leaking internal states into response bodies.
- **BREAKING (E2B observation behavior):** change claimed Upgrading, Recycling, empty-phase, and
  unsupported-phase observations that currently fall back to HTTP 200 `paused` into the applicable
  HTTP 404 unavailable response; List omits them.
- Migrate consumers atomically and remove `pkg/utils.GetSandboxState` plus the five
  `api/v1alpha1.SandboxState*` constants after their final compatibility use.

## Capabilities

### New Capabilities

- `sandbox-manager-state-model`: eight-state vocabulary, deterministic provider observation,
  Manager consumer boundary, and recycle capability.
- `sandboxset-pool-classification`: provider-owned creating/available predicates and
  behavior-preserving Controller/cache adoption.
- `sandbox-route-action`: canonical provider GetRoute, action storage/forwarding behavior, and
  mixed-version wire compatibility.
- `e2b-sandbox-lifecycle`: public state projection, stable unavailable reasons, and lifecycle-aware
  operation gates.

### Modified Capabilities

None. This repository has no archived OpenSpec capability specifications.

## Impact

- Requires the completed `sandbox-provider` change and changes its observation and route contracts.
- `pkg/sandboxprovider` owns state/action-facing contracts; `pkg/sandboxprovider/sandboxcr` owns CR
  derivation and canonical GetRoute; Manager's infra/sandboxcr adapter delegates to it.
- SandboxSet, cache, claim selection, waiters, proxy, Gateway, Manager, web errors, and E2B handlers
  migrate in one atomic implementation after the prerequisite extraction.
- `api/v1alpha1` loses derived-state string constants but gains no serialized lifecycle field or CRD
  schema change.
- Route JSON gains `action`; the legacy `state` member remains compatibility-only during rolling
  upgrades.
- Public Sandbox enum values remain `running` and `paused`, but several legacy 200 `paused`
  fallbacks become reasoned 404 responses. Error bodies gain an additive optional `reason`.
- Controller mutation mechanics are unchanged except for direct-delete fallback when recycling is
  rejected. Quota liveness, route identity, peer topology, resource-version parsing, and route
  ownership are not redesigned; the provider baseline and equal-version action rank are the
  explicit freshness changes.
