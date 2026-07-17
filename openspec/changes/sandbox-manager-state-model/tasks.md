## 0. Prerequisite

- [ ] 0.1 Complete `sandbox-provider`, including neutral dependency closure, shared claim behavior,
      provider-owned pool predicates, a read-only CR view, component-owned backend adapters,
      Manager adaptation, route deletion decision tombstones, and conservative legacy-running
      projection.
- [ ] 0.2 Verify no state, route, claim, CRD, wire, API, retry, timeout, quota, or metric behavior
      changed unexpectedly in the prerequisite extraction, and deploy its complete route-safety
      baseline to every Manager, proxy, and Gateway producer and receiver before enabling this
      change.

## 1. Provider State Contract

- [ ] 1.1 Add `SandboxState`, the eight constants, and `SandboxStateObservation` to
      `pkg/sandboxprovider`; change the provider Sandbox `GetState` capability to return the
      observation.
- [ ] 1.2 Implement the unexported explicit-time derivation in
      `pkg/sandboxprovider/sandboxcr` with the approved precedence, non-empty diagnostics, and total
      `unready` fallback; expose no free CR-to-state function.
- [ ] 1.3 Cover deletion/shutdown, forever and finite reserved failure, cleanup request versus
      recycling, completion, pause/resume, post-resume initialization precedence, upgrade/in-place
      update, claimable, Ready, Pod IP, empty/unsupported phase, and every precedence conflict with
      table-driven tests.
- [ ] 1.4 Replace Manager raw `Phase` plus `IsRecycleEnabled` use with provider `IsRecyclable` while
      incorporating known Controller recycle preconditions such as no persistent-volume claims;
      use direct deletion when false and preserve applicable recycle/fallback metrics.
- [ ] 1.5 Make Controller use the same known recycle preconditions and fall back to direct deletion
      when an accepted cleanup request cannot enter Recycling, so Delete converges to absence.

## 2. Controller, Cache, Claim, and Waiter Decoupling

- [ ] 2.1 Retain provider-owned explicit-time pool creating and available predicates from the
      prerequisite; ensure they remain independent of the eight-state observation.
- [ ] 2.2 Migrate SandboxSet grouping/event handling and pool indexing away from the legacy helper
      without changing status, rolling-update, capacity, enqueue, Pod-IP, lock, or claimed-label
      behavior.
- [ ] 2.3 Migrate shared sandboxcr claim selection to the pool predicates while retaining
      expectation, candidate, speculation duration, Pod-IP, lock, and revision safeguards.
- [ ] 2.4 Replace cache active-count and readiness/pause/resume waiter uses of the legacy helper with
      purpose-specific facts; preserve active-count, quota, fast-failure, timeout, and retry semantics.
- [ ] 2.5 Add table-driven equivalence tests for pool classification, indexing, grouping/events,
      active count, candidate selection, quota liveness, and waiter outcomes.

## 3. Canonical Route Action

- [ ] 3.1 Replace core Route `State` with typed `Action` values Allow, Deny, and Delete while
      preserving identity, metadata, resource-version comparison, and token redaction.
- [ ] 3.2 Implement the only state-to-action mapping inside shared sandboxcr GetRoute; require it to
      call GetState exactly once and return complete metadata plus Action.
- [ ] 3.3 Migrate Manager route production and Gateway informer handling to the same GetRoute method;
      remove every Manager/Gateway raw phase, readiness, paused, resume-init, update, cleanup, or
      completion route branch.
- [ ] 3.4 Update proxy, Gateway registry/server, peer refresh, periodic/event reconciliation, and
      data-plane filters so Allow/Deny are retained, only Allow forwards, Delete only removes, and
      invalid/empty Action fails closed; preserve non-forwarding Delete tombstones.
- [ ] 3.5 Add a compatibility wire adapter that emits Action plus legacy state, prefers valid Action,
      and applies the approved Manager/proxy and Gateway fallbacks when Action is absent.
- [ ] 3.6 Add table-driven tests for all eight mappings, same-CR Manager/Gateway parity with explicit
      time, shutdown boundary, same-version Delete-over-Deny-over-Allow ordering, tombstone
      resurrection prevention, new UID and newer-RV replacement, invalid Action, Delete-not-active,
      data-plane Deny, sender legacy values, both legacy receive policies, and mixed-version refresh.

## 4. Manager and E2B Adoption

- [ ] 4.1 Migrate only Manager to provider `SandboxStateObservation`; expose a protocol-independent
      lifecycle outcome through the Manager interface and prevent E2B from importing provider/infra
      or inspecting Sandbox phase, conditions, cleanup/reserved labels, or Controller reasons.
- [ ] 4.2 Remove expected-state parameters, whitelist variables, and the reserved-failed
      short-circuit from shared claimed-Sandbox lookup; establish existence and ownership before
      lifecycle policy while preserving non-NotFound backend and authorization errors.
- [ ] 4.3 Add optional `web.ApiError.Reason` and exactly four stable lifecycle reasons:
      SandboxNotFound, SandboxTemporarilyUnavailable, SandboxCompleted, and SandboxTerminating.
- [ ] 4.4 Centralize API-layer public projection from the Manager outcome: running maps to running;
      pausing/paused/resuming map to paused; List omits other states; direct representation returns
      the approved HTTP 404 and reason.
- [ ] 4.5 Apply the approved Pause, Resume, Connect, Snapshot, Timeout, Create/Clone response, and
      all-state idempotent Delete policies without leaking internal state into public bodies;
      preserve Resume's empty HTTP 204 response after refreshed running.
- [ ] 4.6 Add table-driven tests for all eight states, four reasons, filters/projection, explicit
      Upgrading/Recycling/empty/unsupported 200-to-404 migration, reserved-failed Describe/Delete,
      lookup/backend/ownership separation, transition concurrency, Resume empty success, Connect
      branches, refreshed success bodies, and Delete idempotency.

## 5. Legacy Cleanup and Verification

- [ ] 5.1 Remove `pkg/utils.GetSandboxState`, its test clock seam if unused, the five
      `api/v1alpha1.SandboxState*` constants, tuple GetState, raw Phase, IsRecycleEnabled, free
      CR-to-route functions, and all remaining lifecycle comparisons outside the approved consumers.
- [ ] 5.2 Run `make generate manifests` after the API package edit and verify no CRD schema or
      unrelated generated artifact changes.
- [ ] 5.3 Verify by source and package-closure inventory that Controller/cache do not consume the
      eight-state model, Manager consumes state only through GetState, Manager/Gateway produce routes
      only through GetRoute, and data-plane code does not read legacy state.
- [ ] 5.4 Run focused Go tests for changed packages under `pkg/` only, using table-driven cases and
      `expectError string`; never run tests under `test/`.
- [ ] 5.5 Run repository-approved static checks, `git diff --check`, and final builds for
      agent-sandbox-controller, sandbox-manager, and sandbox-gateway after focused tests pass.
- [ ] 5.6 Re-run strict OpenSpec validation and confirm the implementation satisfies both this change
      and the completed `sandbox-provider` prerequisite.
