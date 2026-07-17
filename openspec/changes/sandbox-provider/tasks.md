## 1. Provider Contracts and Dependency Closure

- [ ] 1.1 Add `pkg/sandboxprovider` with the shared Sandbox capability, observation, claim request,
      explicit defaults, admission, resource/update, result, lock, and metrics types.
- [ ] 1.2 Add `pkg/sandboxprovider/sandboxcr` with a read-only CR view, pure CR helpers, and a narrow
      claim backend contract; ensure it imports no concrete client/cache and Gateway receives only
      the read-only view.
- [ ] 1.3 Replace cache-owned uses of Manager configuration/logging with cache options and neutral
      context logging; translate Manager startup configuration at the call site.
- [ ] 1.4 Replace controller runtime/CSI imports of Manager config with responsibility-specific shared
      types and localize Controller-only constants.
- [ ] 1.5 Add source and package-closure checks proving provider production code imports no
      controller, sandbox-manager, or servers package and controller production code imports no
      sandbox-manager package.

## 2. Pool and SandboxSet Mechanics

- [ ] 2.1 Move explicit-time pool creating and available/claimable predicates to
      `pkg/sandboxprovider/sandboxcr` with the existing terminal, Pending, ownership, and Ready rules.
- [ ] 2.2 Move SandboxSet-to-Sandbox materialization to the CR provider and migrate Controller and
      claim creation callers without changing templates, revisions, labels, annotations, priority,
      or owner references.
- [ ] 2.3 Migrate SandboxSet grouping/event handling and cache pool indexing to the provider
      predicates while keeping active count, waiter, quota, and enqueue policies purpose-specific.
- [ ] 2.4 Add table-driven equivalence tests for pool classification, grouping, event transitions,
      materialization, template references, pool indexing, and active-count behavior.

## 3. Shared Claim Operation

- [ ] 3.1 Move common claim options, explicit defaults, admission, resource/update/runtime/CSI intent,
      result, lock, failure records, and metrics out of Manager infra into sandboxprovider.
- [ ] 3.2 Add sandboxcr execution options for CR-only metadata, execution controls, and the narrow
      backend capability without concrete client/cache types; resolve caller defaults before
      validation and side effects.
- [ ] 3.3 Move claim validation, candidate selection, locking orchestration, post-processing
      sequencing, failure retention orchestration, annotation ownership, and `TryClaimSandbox` into
      the CR provider without importing Manager, server, Controller, or concrete cache/client packages.
- [ ] 3.4 Implement the narrow claim backend in Manager infra/sandboxcr and SandboxClaim Controller,
      keeping concrete clients, cache reads, CR writes, waits, runtime/CSI, identity, and cleanup I/O
      inside those component boundaries; retain caller-local quota/error mapping and resolved options.
- [ ] 3.5 Remove old duplicate types and helpers after both adapters use the shared orchestration.
- [ ] 3.6 Add table-driven equivalence tests for validation, candidates, speculation, revision
      preference, create-on-no-stock, admission pairing, retries, cancellation, readiness, runtime,
      identity, CSI, metadata, cleanup, reservation, errors, and metrics.

## 4. Shared Observation and Manager Adapter

- [ ] 4.1 Move CR observation and current route projection into the read-only sandboxcr view; require
      `GetRoute` to call `GetState` and expose no free CR-to-state or CR-to-route function.
- [ ] 4.2 Make the Manager mutable Sandbox delegate observation methods to the shared view while
      retaining all concrete clients/cache, reads/writes, lifecycle, clone, checkpoint, volume,
      quota-source, and builder code in `pkg/sandbox-manager/infra/sandboxcr`.
- [ ] 4.3 Migrate Gateway's CR watcher to the read-only provider without changing current routing or
      peer-refresh behavior; do not add a Gateway dependency on Manager infra or state.
- [ ] 4.4 Add table-driven parity tests showing Manager and Gateway obtain identical current routes
      from the same CR observation and that mutable methods are unavailable from the Gateway view.
- [ ] 4.5 Add non-forwarding deletion tombstones to Manager/proxy and Gateway route stores, keyed by
      route identity, Sandbox UID, and resource version; reject equal/older same-UID resurrection and
      allow newer-RV or new-UID replacement.
- [ ] 4.6 Add table-driven tests for delete-not-active behavior, stale same-version re-add rejection,
      newer resource-version recovery, Sandbox ID reuse with new UID, and active-route List/data-plane
      invisibility.
- [ ] 4.7 Harden the shared legacy GetRoute projection so it emits `running` only when every future
      Allow safety gate is satisfied; emit a non-running legacy value for resume initialization,
      in-place update, cleanup request, reserved failure, missing address, and every other known
      non-serving observation without adding Action or changing the wire shape.
- [ ] 4.8 Add table-driven legacy-route tests covering every safety gate and proving Manager and
      Gateway baseline producers never emit `running` for a future Deny or Delete observation.
- [ ] 4.9 Gate peer route mutation and data-plane readiness on authoritative local Sandbox cache
      synchronization; rebuild current decisions through GetRoute after restart and reject or defer
      peer updates whose identity, UID, or resource version is absent, stale, superseded, or ahead of
      the local observation, and reject actions weaker than the locally derived same-version
      decision.
- [ ] 4.10 Garbage-collect tombstones after authoritative absence or supersession and add focused
      restart, cache-not-ready, delayed-peer, ahead-of-cache, local-decision-rank, absence, new-UID,
      newer-active-route, newer-Delete, and bounded-tombstone tests for Manager/proxy and Gateway
      receivers.

## 5. Verification and Handoff

- [ ] 5.1 Verify no public API, CRD, generated client, Route wire, claim behavior, default, retry,
      timeout, quota, metric, or E2B response changes; confirm the only route changes are stale
      same-or-older resurrection rejection, conservative legacy-running safety, and authoritative
      receiver readiness/validation required to make those decisions restart-safe.
- [ ] 5.2 Run focused Go tests for changed packages under `pkg/` only, using table-driven cases and
      `expectError string`; never run tests under `test/`.
- [ ] 5.3 Run repository-approved static checks, `git diff --check`, and final builds for the
      controller, manager, and Gateway only after focused tests pass.
- [ ] 5.4 Run strict OpenSpec validation and confirm `sandbox-manager-state-model` treats this change
      as its completed provider and route-safety prerequisite; deploy the baseline to all supported
      route producers and receivers before enabling the dependent Action semantics.
