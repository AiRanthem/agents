## Why

The expanded lifecycle model cannot be activated safely while route presence is used as proof that a Sandbox exists or owns a request. Routes are intentionally absent or non-forwarding for several real CR states.

This change also overlaps the routing seams owned by the approved [short Sandbox ID design](../../../docs/specs/2026-07-10-short-sandbox-id-design.md). That design is a mandatory prerequisite and source of truth for route identity, projection, Store fencing, peer compatibility, targeted repair, and feeder ownership. Lifecycle activation must extend those seams instead of retaining or rebuilding the legacy `GetRouteFromSandbox`, registry, or periodic-reconcile algorithms.

## What Changes

- Make claimed-Sandbox lookup CR-based and independent from route presence or lifecycle filtering.
- Preserve short-ID's opaque zero/one/multiple indexed lookup contract. Use APIReader only after a cache hit supplies an ObjectKey and staleness is proven; never parse an ID or issue a full Sandbox List to repair a pure miss. Distinguish a clean indexed absence from ambiguity, context expiry, and backend failure.
- Expose CR-derived owner and lifecycle observations through backend-neutral `infra.Sandbox` accessors. Move ownership enforcement to that CR-backed owner and remove route-table ownership checks from E2B authentication middleware and sandbox-manager.
- Feed the canonical lifecycle state into short-ID's neutral `sandboxroute.ProjectionInput.State` without restoring production use of `GetRouteFromSandbox` or rewriting empty-IP observations to `creating`.
- Add component inclusion/disposition policy for retained, forwarding, and deletion states to the manager-owned cache feeder and Gateway CR adapter. Reuse the same policy in each short-ID targeted Repairer so repair cannot re-add an excluded terminal route.
- Generalize the existing explicit-delete copy-to-`dead` wire translation so terminal and recycling observations use short-ID's full conditional peer-delete path while retained states are never translated.
- Preserve short-ID's ObjectKey/UID/resourceVersion Store, conditional delete, collision quarantine, retired/deletion fences, and targeted direct-Get repair. Do not add a competing registry, unconditional delete path, periodic full List, or route projection inside `sandboxcr.Infra`.
- Treat this as the first production activation of canonical derivation: route state directly gates both proxy and Gateway forwarding. Require the complete Part 1 test gate and add golden-path/data-plane regressions in this change.

## Capabilities

### New Capabilities

- `sandbox-cr-lookup`: Route-independent opaque claimed-Sandbox lookup, bounded indexed-absence confirmation, cache-hit APIReader refresh, typed failure preservation, and CR-based ownership.
- `sandbox-route-lifecycle`: Lifecycle integration with the short-ID Projector/Store/Repairer, terminal disposition, forwarding boundary, and legacy peer-wire translation.

### Modified Capabilities

None. This repository has no archived OpenSpec capability specifications.

## Impact

- Sandbox-manager cache/infra lookup, typed errors, backend-neutral lifecycle/owner accessors, ownership checks, E2B authentication middleware, and minimal error-code mapping needed to preserve authorization and keep backend failures out of 404.
- The manager-owned short-ID route feeder, `sandboxroute.ProjectionInput` assembly, component disposition callback, and copy-only peer deletion send path; `pkg/utils/proxyutils` gains no production projection responsibility.
- Only lifecycle policy/extraction wiring in the Gateway CR adapter; the shared short-ID Store/Repairer and peer conditional-delete machinery are reused rather than redesigned.
- This is part 2 of 3. It requires both the implemented, passing `1-define-sandbox-lifecycle-state-model` and the routing/cache/infra foundation from `docs/specs/2026-07-10-short-sandbox-id-design.md`. It deliberately switches the route consumer and therefore changes non-running route retention/deletion behavior, but it does not yet switch general state consumers or public E2B lifecycle behavior.
