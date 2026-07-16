## 1. Atomic Consumer Inventory and Cutover

- [ ] 1.1 Inventory every `GetSandboxState`/tuple `GetState` call, direct comparison with legacy API state constants, raw `Phase()` use, lifecycle condition/label/annotation interpretation, and `expectedStates` whitelist in controller, cache, sandbox-manager, infra, and E2B; also verify short-ID-removed `GetSandboxID`/`GetRoute` remain absent and the manager feeder already consumes normalized lifecycle through `ProjectionInput.State`.
- [ ] 1.2 Switch `pkg/utils.GetSandboxState` to the canonical explicit-time lifecycle function and remove local derived-`dead` behavior while retaining `dead` only for peer compatibility.
- [ ] 1.3 Migrate claim selection, readiness/update tasks, and all CR-aware controller/cache consumers without duplicating phase/condition logic or importing infra/manager/E2B packages.
- [ ] 1.4 Migrate Sandbox-manager and E2B lifecycle decisions to the Part 2 normalized infra lifecycle/owner/capability contract and its canonical-state aliases; replace the manager raw `Phase()` recycle gate and remove tuple `GetState`, raw `Phase`, split recycle, and route-owner compatibility methods after final use without duplicating the vocabulary or moving ID resolution/Route projection into infra.
- [ ] 1.5 Add focused table-driven consumer/waiter/boundary tests for all eleven states, including ordinary `creating` retry, `StartContainerFailed` fast failure, update outcomes, terminal completion, explicit-time deadline behavior, recycle eligibility, and proof that upper-layer lifecycle code does not inspect CRD phase/conditions.

## 2. SandboxSet, Pool, and Accounting

- [ ] 2.1 Update pool indexes to include only unclaimed SandboxSet-controlled `creating` and `available` objects.
- [ ] 2.2 Update SandboxSet grouping/status to distinguish unclaimed capacity, claimed used states, recycling/ignored non-capacity, and terminal garbage collection exhaustively; change the default from reconcile-failing error to logged ignored/non-capacity degradation for a future unexpected state.
- [ ] 2.3 Update `CountActiveSandboxes` to require the claimed label and count exactly `creating`, `running`, `pausing`, `paused`, `resuming`, and `upgrading` while leaving `IsLiveForQuota` and quota-source behavior unchanged.
- [ ] 2.4 Add table-driven tests for pool index/grouping, claimed creation, deleting objects, recycling, terminal cleanup, and every active-count state.
- [ ] 2.5 Add SandboxClaim recovery regression tests proving unclaimed pool objects are excluded, owner/lock metadata and `sandbox-claimed=true` are committed by the same successful create/update, and the existing `max(status count, actual count)` self-healing behavior remains correct.

## 3. Public Projection and 404 Reasons

- [ ] 3.1 Add stable Sandbox 404 reason constants and `web.ApiError.Reason` serialized as `reason,omitempty` while preserving its existing runtime `code`, `headers`, `message`, and `request_id` fields; verify the unused two-field `models.Error` is not substituted into handler serialization.
- [ ] 3.2 Remove `expectedStates` from `SandboxManager.GetSandbox` and E2B `getSandboxOfUser`, delete `claimedSandboxStates`/`liveSandboxStates`, and add one normalized-infra-to-public conversion/error boundary for List, Describe, Create, Clone, Resume, Connect, Snapshot, Timeout, and every other direct Sandbox response/gate.
- [ ] 3.3 Map confirmed absence to `SandboxNotFound`, reserved-failed claimed CRs to `SandboxFailed`, and every other unrepresentable found CR to its approved lifecycle reason; preserve backend lookup failures as 5xx and ownership mismatch as the existing authorization response.
- [ ] 3.4 Add table-driven web/E2B tests for all six reasons, all five runtime error fields when `reason` is present, true indexed/APIReader-confirmed absence versus backend/ambiguity failure, reserved-failed versus absent, route-less terminal lookup, found transitional CRs surviving lookup, paused-family filter expansion, prevention of raw internal-state leakage, and short-ID diagnostic disclosure rules for `sandboxResource`.

## 4. Lifecycle-Aware Operations

- [ ] 4.1 Update Pause and Resume to accept their approved same-direction state sets, join existing wait tasks, preserve first-writer timeout/parameters, and return the upstream-documented 409 for the opposite transition.
- [ ] 4.2 Update Connect for `running`, `paused`, `resuming`, and `pausing`; use the upstream-documented 400 for `pausing` and require refreshed `running` before returning a successful body.
- [ ] 4.3 Make Delete return 204 for every owned claimed lifecycle state, confirmed absence, and concurrent NotFound while preserving ownership and non-NotFound backend errors.
- [ ] 4.4 Add table-driven concurrency and gate tests for repeated Pause/Resume, opposite-direction conflict, all Connect branches, all-state Delete, concurrent deletion, and backend/ownership failures.

## 5. Verification

- [ ] 5.1 Confirm Part 1, the approved short-ID routing/cache/infra foundation, and Part 2 are implemented in the required partial order; Part 1 tests gate the already-active `ProjectionInput.State` path, and route-based lookup/ownership is gone before enabling the remaining wrapper cutover.
- [ ] 5.2 Run focused Go tests only for changed packages under `pkg/`, including lifecycle consumers, cache, SandboxSet, SandboxClaim core, sandbox-manager, sandboxcr, web, and E2B; never run tests under `test/`.
- [ ] 5.3 Run repository-approved lint/static checks and final builds for `cmd/agent-sandbox-controller` and `cmd/sandbox-manager` only after focused tests pass.
- [ ] 5.4 Verify by source/import inventory that Sandbox-manager/E2B lifecycle decisions no longer use raw CR phase/conditions, API lifecycle constants, ownership/cleanup annotation keys, or expected-state whitelists; `GetSandboxID`/`GetRoute` remain absent; no client ID is parsed; and Controller/lifecycle packages do not import upper layers.
- [ ] 5.5 Verify `docs/proposals/20260715-sandbox-lifecycle-state-model.md` still matches the implemented three-change contract, short-ID prerequisite and no-rollback boundary, runtime error structure, lifecycle/routing dependency split, and minimal Gateway policy delta over the fenced Store.
- [ ] 5.6 Re-run strict OpenSpec validation and confirm every tracked task and every Sandbox lifecycle-related 404 reason is covered.
