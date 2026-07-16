## Why

The lifecycle model and supporting lookup/route infrastructure do not solve the user-visible problem until every legacy five-state consumer switches together. A coordinated final cutover is required so transient states stop becoming `dead` or ambiguous HTTP 404 while cache, SandboxSet, waiters, manager operations, and E2B responses remain consistent.

## What Changes

- **BREAKING (internal state contract):** switch `pkg/utils.GetSandboxState` to the canonical eleven-state derivation and require all callers to handle the exhaustive vocabulary; local derivation no longer returns `dead`, which remains only the copy-only peer deletion value carried by short-ID's conditional Route protocol.
- Migrate SandboxSet grouping, pool indexing, claimed active accounting, claim recovery, readiness waiters, sandbox-manager infra wrappers, and remaining state consumers atomically. Unexpected future states degrade to logged non-capacity handling instead of failing an entire SandboxSet reconcile.
- Preserve `IsLiveForQuota` as a separate policy and require the claimed label before `CountActiveSandboxes` counts a Sandbox.
- Keep the public E2B Sandbox state enum limited to `running` and `paused`, projecting pausing/resuming into public paused and rejecting other internal states.
- Remove the current `getSandboxOfUser(expectedStates)` white-list gate and replace it with CR-backed lookup followed by normalized lifecycle projection and reasoned errors.
- Add an optional JSON `reason` field to the runtime `web.ApiError` response, which currently has `code`, `headers`, `message`, and `request_id`; require every Sandbox lifecycle-related HTTP 404 to identify confirmed absence or the exact found-but-unavailable category. The separate two-field `models.Error` is not the handler's runtime error body.
- Make Pause and Resume directionally idempotent, make Connect explicit for paused-family states, and make Delete idempotent for all owned claimed states and confirmed absence.
- Preserve operation-specific fast failures such as `StartContainerFailed` even when their lifecycle state is converging.
- Complete the lifecycle dependency cleanup: E2B and Sandbox-manager consume normalized infra state/reason/owner/capabilities, do not interpret CRD phase or Controller conditions, and remove the manager's raw `Phase()` recycle gate.
- Preserve the approved short-ID boundaries: E2B and infra never choose or parse Sandbox IDs, `infra.Sandbox` exposes neither `GetSandboxID()` nor `GetRoute()`, manager/Gateway continue using the neutral Projector and fenced Store, and lifecycle adoption does not reintroduce route-backed lookup or ownership.
- Use upstream-documented status families: Pause/Resume conflict uses 409, and Connect invalid transition uses 400.

## Capabilities

### New Capabilities

- `sandbox-lifecycle-consumers`: Atomic migration of cache, SandboxSet, active accounting, claim recovery, waiters, and manager state consumers.
- `e2b-sandbox-lifecycle`: Public state projection, CR-backed lifecycle errors, stable 404 reasons, and lifecycle-aware operation gates.

### Modified Capabilities

None. The prerequisite changes are tracked separately and must be applied before this change.

## Impact

- Compatibility wrapper and every remaining `GetSandboxState` consumer under `pkg/`.
- SandboxSet grouping/status, pool cache indexes, claim accounting/recovery, and lifecycle wait tasks.
- Sandbox-manager infra/service state gates and E2B/web response serialization.
- Public error bodies gain an additive optional `reason`; the official public Sandbox state enum and CRD schema do not change.
- Lifecycle decision code follows `E2B -> SandboxManager -> infra -> sandboxcr/controller-owned CR facts`; the separate routing branch remains `manager/Gateway adapter -> sandboxroute.Projector -> fenced Store`. Unrelated pre-existing E2B uses of CRD types for templates or extension metadata are outside this change.
- This is part 3 of 3 and depends on both `1-define-sandbox-lifecycle-state-model` and the approved short-ID routing/cache/infra foundation preceding `2-prepare-sandbox-lifecycle-infrastructure`; Part 3 follows all three.
