## 1. Sandbox-manager State Boundary

- [ ] 1.1 Add `SandboxState`, the eight constants, and `SandboxStateObservation` to `pkg/sandbox-manager/infra`; change `Sandbox.GetState()` to return the observation struct.
- [ ] 1.2 Implement unexported `getSandboxState(sbx, now)` in `pkg/sandbox-manager/infra/sandboxcr` with the approved precedence, non-empty diagnostics, explicit observation time, and total `unready` fallback.
- [ ] 1.3 Cover deletion/shutdown, reserved-failed, cleanup/recycling, completion, pause/resume, post-resume RuntimeInitialized taking precedence over `spec.paused=true`, upgrade/in-place update, pool availability, Ready, Pod IP, empty/unsupported phase, and every precedence conflict with table-driven tests.
- [ ] 1.4 Replace `Sandbox.IsRecycleEnabled()` and `Sandbox.Phase()` with `Sandbox.IsRecyclable()` while preserving the exact cleanup-enabled plus Running-phase predicate and existing recycle/fallback metrics.
- [ ] 1.5 Update `pkg/utils/lifecycle/AGENTS.md` to prohibit ownership of or aliases to the sandbox-manager state model; keep its sibling `CLAUDE.md` as `@./AGENTS.md`.

## 2. SandboxSet, Cache, Claim, and Waiter Decoupling

- [ ] 2.1 Add explicit-time `IsSandboxCreating` and `IsSandboxAvailable` to `pkg/controller/sandboxset`, preserving the old terminal prechecks, Pending behavior, SandboxSet controller ownership, and Ready-only availability rule.
- [ ] 2.2 Migrate SandboxSet grouping/event handling and pool indexing to those helpers without changing status, rolling-update, capacity, enqueue, Pod-IP, lock, or claimed-label behavior.
- [ ] 2.3 Migrate sandboxcr claim candidate selection to the creating/available helpers; retain the independent expectation, candidate, speculation duration, Pod-IP, lock, and revision checks.
- [ ] 2.4 Replace cache active-count and readiness/pause/resume waiter uses of the shared state helper with purpose-specific local facts; keep current active-count, quota, fast-failure, timeout, and retry semantics.
- [ ] 2.5 Add table-driven equivalence tests for creating/available edge cases, pool index, SandboxSet grouping/event transitions, active count, candidate selection, and waiter outcomes.

## 3. Explicit Route Action

- [ ] 3.1 Replace core Route `State` with typed `Action` values `Allow`, `Deny`, and `Delete`; make Sandbox route projection metadata-only so callers must assign an action.
- [ ] 3.2 Map manager observations to actions exactly as specified and add a Gateway-local CR action policy that does not import manager state.
- [ ] 3.3 Update manager proxy, Gateway registry/server, peer refresh, periodic/event reconciliation, and data-plane filters so Allow/Deny are retained, only Allow forwards, Delete only removes, and invalid/empty action fails closed.
- [ ] 3.4 Add a compatibility wire adapter that emits action plus legacy state, prefers valid action on receive, and applies the approved component-specific legacy fallback when action is absent.
- [ ] 3.5 Preserve current resource-version comparison, peer topology, route identity, reconciliation ownership, and log token redaction.
- [ ] 3.6 Add table-driven tests for every manager state mapping, Gateway Allow/Deny/Delete facts, empty IP, invalid action, Delete-not-stored behavior, data-plane denial, sender compatibility values, both legacy receive policies, and mixed-version refresh.

## 4. Manager and E2B Adoption

- [ ] 4.1 Migrate sandbox-manager and E2B callers to `SandboxStateObservation`; prevent upper layers from inspecting Sandbox phase, conditions, cleanup/reserved labels, or Controller reasons.
- [ ] 4.2 Remove expected-state parameters, state whitelist variables, and the reserved-failed label short-circuit from shared claimed-Sandbox lookup; establish existence and ownership before lifecycle projection, then let GetState and each operation handle reserved-failed while preserving non-NotFound backend and authorization errors.
- [ ] 4.3 Add `web.ApiError.Reason` as `reason,omitempty` and the four stable lifecycle reasons `SandboxNotFound`, `SandboxTemporarilyUnavailable`, `SandboxCompleted`, and `SandboxTerminating`.
- [ ] 4.4 Centralize public projection: running maps to running; pausing/paused/resuming map to paused; List omits other states; direct operations map unrepresentable observations to the approved reason.
- [ ] 4.5 Apply the approved Pause, Resume, Connect, Snapshot, Timeout, Create/Clone response, and all-state idempotent Delete policies without leaking internal state into public Sandbox bodies.
- [ ] 4.6 Add table-driven manager/web/E2B tests for all eight states, all four unavailable reasons, public filters/projection, explicit claimed Upgrading/Recycling/empty/unsupported migration from legacy HTTP 200 `paused` to reasoned HTTP 404 or List omission, reserved-failed Describe returning `SandboxTerminating`, reserved-failed Delete accepting and completing real removal, lookup/backend/ownership separation, same/opposite transition concurrency, Connect branches, successful-body refresh, and Delete idempotency.

## 5. Legacy Cleanup and Verification

- [ ] 5.1 Remove `pkg/utils.GetSandboxState`, its test-only clock seam if unused, the five `api/v1alpha1.SandboxState*` constants, tuple `GetState`, `Phase`, `IsRecycleEnabled`, and all remaining state comparisons outside the manager path.
- [ ] 5.2 Run `make generate manifests` after the API package edit and verify no CRD schema or unrelated generated artifact changes.
- [ ] 5.3 Verify by source/import inventory that only sandbox-manager and its server path consume `SandboxState`; manager-side dependency on `pkg/controller/sandboxset` remains inside sandboxcr infra; Route/data-plane code does not read legacy state.
- [ ] 5.4 Run focused Go tests for changed packages under `pkg/` only, using table-driven cases and `expectError string`; never run tests under `test/`.
- [ ] 5.5 Run repository-approved static checks, `git diff --check`, and final builds for `cmd/agent-sandbox-controller`, `cmd/sandbox-manager`, and `cmd/sandbox-gateway` only after focused tests pass.
- [ ] 5.6 Re-run strict OpenSpec validation and confirm the implementation matches this single atomic change and the architecture proposal.
