## Why

Controller currently imports sandbox-manager configuration, infra contracts, and the CR
implementation to reuse Sandbox claim behavior, while Gateway separately interprets the same
Sandbox CR for routing. Shared CR mechanics need a neutral owner so controller remains
self-contained and Manager and Gateway can reuse one observation path.

## What Changes

- Add `pkg/sandboxprovider` for implementation-neutral Sandbox capabilities, claim inputs and
  results, options, defaults, admission callbacks, resource types, and metrics.
- Add `pkg/sandboxprovider/sandboxcr` for reusable Sandbox CR algorithms, including a read-only
  observation view, `GetState`, `GetRoute`, pool predicates, SandboxSet materialization, CR-specific
  claim options, a narrow backend contract, and `TryClaimSandbox` orchestration.
- Keep `pkg/sandbox-manager/infra` as the Manager port and keep its `sandboxcr` child as the owner of
  concrete Kubernetes clients, cache access, CR reads/writes, Manager assembly, and operations; make
  it implement the shared backend contract and delegate reusable algorithms.
- Move common claim options out of Manager infra, keep CR-only inputs and backend capabilities in
  the sandboxcr child, keep concrete clients/cache in component adapters, and require callers to
  supply policy defaults explicitly.
- Remove shared-provider dependencies on Manager errors, constants, logs, E2B models, and
  controller packages. Remove controller production imports of sandbox-manager from the migrated
  claim and runtime paths.
- Add a route compatibility baseline: deletion leaves a non-forwarding freshness tombstone, and the
  shared legacy GetRoute emits `running` only for observations that satisfy every later Allow
  safety gate. Gate restart readiness and peer updates on synchronized authoritative Sandbox
  observation so tombstones can be rebuilt or safely collected. Keep the legacy wire shape
  unchanged.
- Preserve existing SandboxSet, claim, state, retry, cleanup, quota, runtime, CSI, identity, public
  API, and wire behavior. The only route changes are conservative safety hardening; the dependent
  state-model change owns the lifecycle and Action semantics.

## Capabilities

### New Capabilities

- `sandbox-provider-boundary`: package ownership, dependency direction, Sandbox observation access,
  Manager adaptation, and the route compatibility baseline.
- `sandbox-cr-claim`: shared claim options, explicit defaults, CR-specific execution, admission,
  cleanup, and behavior equivalence.

### Modified Capabilities

None. This repository has no archived OpenSpec capability specifications.

## Impact

- Adds `pkg/sandboxprovider` and `pkg/sandboxprovider/sandboxcr` as internal Go APIs.
- Changes internal imports, option ownership, stale route deletion handling, route-receiver
  readiness/validation, and conservative legacy route projection across controller, cache,
  sandbox-manager, and Gateway without changing external APIs or CRDs.
- Leaves API validation, authorization, quota policy, unavailable-reason mapping, and Manager
  orchestration above the provider boundary.
- Establishes the prerequisite package boundary used by `sandbox-manager-state-model`.
