## Context

The first prerequisite change adds Controller failure-stage reasons and a directly tested pure lifecycle model while intentionally leaving `pkg/utils.GetSandboxState` unchanged. Independently, the approved short Sandbox ID design installs the neutral Projector, ObjectKey/UID/resourceVersion-fenced Store, conditional peer protocol, targeted Repairer, opaque claimed-ID cache lookup, manager-owned route feeder, and route-free infra interface. Part 2 then makes CR lookup and ownership independent from routes and activates canonical state through that short-ID routing foundation. Part 2 is therefore already a production data-plane decision change; this final change activates every remaining state consumer and the public API behavior.

This final change is the semantic activation point. The existing wrapper is used across SandboxSet, cache indexes and accounting, claim selection and recovery, waiters, sandbox-manager infra, and E2B handlers. Switching only some callers would create contradictory capacity, readiness, routing, and API behavior, so the wrapper and all remaining consumers move in one implementation change.

The public E2B API can expose only `running` and `paused`. Internal states therefore require one projection boundary and a structured error taxonomy. Route absence is no longer an existence signal because the prerequisite lookup change returns the CR first. Today `getSandboxOfUser(expectedStates)` and `SandboxManager.GetSandbox(expectedStates)` form a distributed whitelist that turns any non-listed state into 404 before projection; that whitelist must be removed, not merely supplemented with a converter.

The runtime HTTP error body is `web.ApiError`, with `code`, `headers`, `message`, and `request_id`. The separate `models.Error` contains only `code` and `message` but is not serialized by the registered handler error path. The optional lifecycle `reason` therefore belongs on `web.ApiError`.

## Goals / Non-Goals

**Goals:**

- Activate one exhaustive lifecycle interpretation across all remaining consumers.
- Keep CRD phase, condition, claim/cleanup annotation, and Controller-reason interpretation below the infra boundary for the manager HTTP path.
- Preserve pool capacity, claimed active count, and quota liveness as separate policies.
- Preserve waiter-specific failure signals while eliminating generic `dead` assumptions.
- Keep E2B response states within the official two-value enum.
- Give every Sandbox lifecycle-related 404 a stable reason distinguishing true absence from a CR that exists but is unavailable.
- Make pause, resume, connect, and delete behavior explicit and idempotent where selected.
- Remove expected-state whitelist filtering and use one normalized lifecycle observation for projection and operation policy.
- Preserve short-ID opacity, authorization diagnostics, route ownership, and fenced Store semantics while removing the temporary tuple-state extraction seam.

**Non-Goals:**

- Changing Controller phases or in-place failure-stage reasons established by the first change.
- Redesigning opaque claimed-ID lookup or the Projector/Store/Repairer, Route shape, Gateway registry facade, conditional peer protocol, collision/fence semantics, and feeder ownership established by short-ID and Part 2.
- Extending the official E2B Sandbox state enum.
- Changing non-Sandbox 404 contracts for templates, volumes, API keys, or unrelated resources.
- Coupling quota release to the active-state list.
- Refactoring unrelated E2B imports of `api/v1alpha1` used for templates, extension metadata, or other non-lifecycle contracts.

## Decisions

### 1. Enforce a normalized lifecycle boundary for the manager path

The manager lifecycle dependency is directional:

`E2B -> SandboxManager -> infra.Sandbox lifecycle/owner/capability contract -> sandboxcr -> api/v1alpha1 + pkg/utils/lifecycle`.

Routing remains a separate, equally one-way branch:

`manager composition / Gateway CR adapter -> sandboxroute.Projector -> ObjectKey/UID/RV-fenced Store -> data-plane facade`.

`pkg/sandboxroute` does not import infra, manager, E2B, controller, or the lifecycle package. Lifecycle is supplied as the neutral `ProjectionInput.State` string by CR-aware adapters; Store semantics do not interpret it beyond component policy outside the Store.

The sandboxcr adapter is the only manager-path component that interprets Sandbox phase, lifecycle conditions, the claimed/cleanup labels and annotations, or Controller reason strings. It returns the named normalized lifecycle observation prepared in Part 2. Sandbox-manager owns authorization and operation orchestration over that observation; E2B owns public projection and HTTP status/body mapping. Neither layer reconstructs CRD semantics.

This cannot make every change live only in infra: Controller/cache/SandboxSet consumers belong to the K8s control path, while public `reason` serialization and E2B state projection belong to the HTTP boundary. The invariant is that CRD interpretation is centralized, not that HTTP or controller policy is moved into infra.

As part of adoption:

- `SandboxManager.GetSandbox` no longer accepts `expectedStates`; it fetches an owned, claimed Sandbox and returns its normalized lifecycle observation to the caller;
- E2B `getSandboxOfUser` no longer owns `claimedSandboxStates` or `liveSandboxStates` whitelists;
- manager recycle behavior uses the infra recycle-eligibility capability prepared in Part 2, preserving the existing phase/annotation decision without calling raw `Phase()`;
- manager/E2B lifecycle code uses the infra-exposed aliases of the canonical lifecycle constants rather than `api/v1alpha1.SandboxState*` values;
- tuple `GetState`, raw `Phase`, split recycle compatibility methods, and route-owner helpers are removed when their final callers are gone;
- short-ID-removed `GetSandboxID()` and `GetRoute()` remain absent, and ID resolution/projection continues above infra;
- manager route projection continues building the neutral `ProjectionInput`, but consumes the Part 2 lifecycle and owner accessors rather than raw CRD fields.

Controller, SandboxSet, and cache code consume the canonical lifecycle package directly because they are already CR-aware. They do not depend on infra, Sandbox-manager, web, or E2B. No new dependency from Controller code toward E2B is introduced.

### 2. Switch the wrapper and consumers atomically

`pkg/utils.GetSandboxState` becomes a clock-supplying compatibility wrapper over the canonical explicit-time function. It adds no policy. The canonical function remains the only phase/condition normalization boundary.

Every call site is inventoried and moved in the same implementation change. Consumers use exhaustive switches or named predicates for their own policy. No consumer treats a default branch as legacy `dead`, and no caller independently inspects upgrade/resume conditions to reconstruct lifecycle state.

`dead` remains a constant only for the copy-only peer deletion state prepared by Part 2 on top of short-ID's full/ID-only conditional protocol. It is not returned for a local Sandbox CR observation and never selects an unconditional Store delete.

### 3. Keep pool capacity, active claims, and quota distinct

SandboxSet classification evaluates claim identity before lifecycle grouping:

- unclaimed SandboxSet-controlled `creating` and `available` populate pool capacity;
- claimed `creating`, `running`, `pausing`, `paused`, `resuming`, and `upgrading` populate `Used`;
- `recycling` and other non-terminal, non-capacity observations enter a new explicit ignored/non-capacity group and remain outside pool capacity and terminal garbage collection;
- `terminating`, `succeeded`, and `failed` populate `Dead` for existing garbage collection, without deleting an already-deleting object twice.

The pool index contains only unclaimed SandboxSet-controlled `creating` and `available` objects.

`CountActiveSandboxes` first requires `agents.kruise.io/sandbox-claimed=true`, excludes reserved-failed objects, and counts exactly `creating`, `running`, `pausing`, `paused`, `resuming`, and `upgrading`. The SandboxClaim self-healing path continues using the maximum of status count and actual count, but its actual count now follows this claimed-only contract. Regression tests cover unclaimed pool objects, recycling, terminal states, and recovery.

The claim write path already mutates owner/lock annotations and `sandbox-claimed=true` on the same Sandbox object before one create/update call. A regression test makes that atomicity an explicit invariant: observers must not see a successful claim write with owner set but the claimed label missing.

`IsLiveForQuota` and the quota source keep their existing deletion, terminating, recycling, and cleanup-annotation policy. They do not call `CountActiveSandboxes` and do not adopt its state set.

For future vocabulary expansion, `groupAllSandboxes` still handles every currently declared state explicitly, but its default no longer returns an error that aborts the whole SandboxSet reconcile. An unexpected state is logged with state/reason and placed in an ignored/non-capacity bucket: it contributes neither pool capacity nor terminal garbage collection until a deliberate mapping is added.

### 4. Waiters consume state but retain operation diagnostics

Claim selection, wait-ready, pause, resume, update, and other lifecycle tasks use the canonical state rather than local five-state or condition heuristics. State answers whether the Sandbox is converging, usable, paused, or terminal; the diagnostic reason still answers whether an operation should fail fast.

In particular, `creating` with `StartContainerFailed` preserves the current operation-specific fast failure. A waiter must not blindly retry every `creating` state. Recreate and in-place update failure reasons retain their existing task-specific error or retry behavior while their global lifecycle state remains `upgrading`.

### 5. Replace expected-state whitelists with one E2B projection boundary

The public conversion is:

- internal `running` -> public `running`;
- internal `pausing`, `paused`, or `resuming` -> public `paused`;
- every other internal state -> not representable.

A CR marked reserved-failed is also unrepresentable even if its raw lifecycle observation would otherwise project: the CR exists as a retained failed claim artifact, so direct HTTP classification uses `SandboxFailed`, never `SandboxNotFound`.

Describe returns a projected Sandbox or a lifecycle-classified 404. List includes only representable objects; `state=paused` expands to all three paused-family states rather than the current single internal `paused` string. Create, Clone, Resume, and Connect return a Sandbox body only after a refreshed internal state is `running`. Raw internal values are never serialized into the public state field.

Sandbox IDs remain opaque and manager-resolved exactly as required by short-ID. Projection does not call `GetSandboxID()`, parse an ID, reconstruct an ObjectKey, or derive identity from a Route. Public list pagination and protected `sandbox-resource` metadata continue using the short-ID contracts independently from lifecycle filtering.

The current `getSandboxOfUser(expectedStates)` and manager-side `expectedStates` filtering are removed. Lookup establishes existence and ownership; the projection/operation helper then evaluates the normalized lifecycle observation and either returns a public value or a typed lifecycle-unavailable result. This prevents a whitelist miss from being prematurely collapsed into generic NotFound.

### 6. Make every Sandbox lifecycle 404 reasoned on the runtime error type

`web.ApiError`, whose existing runtime JSON fields are `code`, `headers`, `message`, and `request_id`, gains `Reason string` serialized as `reason,omitempty`. `models.Error` is not substituted into the handler path. Every HTTP 404 caused by Sandbox lookup or an unrepresentable internal lifecycle state has one stable reason:

| Situation | Reason | Meaning |
|---|---|---|
| confirmed CR absence or non-claimed object | `SandboxNotFound` | the claimed user Sandbox truly does not exist |
| `creating`, `available`, `upgrading` | `SandboxTemporarilyUnavailable` | the CR exists but is not currently representable/usable |
| `succeeded` | `SandboxSucceeded` | the CR exists and completed normally |
| `failed`, or a CR marked reserved-failed | `SandboxFailed` | the CR exists and either terminated unsuccessfully or is retained after a failed claim |
| `terminating` | `SandboxTerminating` | the CR exists or is being removed |
| `recycling` | `SandboxRecycling` | the CR exists but is returning to the pool |

Every reason other than `SandboxNotFound` proves a CR was found but unavailable for that operation. The error message also includes internal state and diagnostic reason. Unrelated errors may omit `reason`.

Short-ID diagnostic disclosure rules still apply. `SandboxNotFound`, ambiguity, and ownership failure do not disclose namespace/name. A found-but-unavailable lifecycle error may include the protected `sandboxResource=<namespace>/<name>` context only after claimed lookup and ownership authorization have succeeded.

Cache/APIReader/timeout/transport failures and opaque-ID ambiguity from the prerequisite lookup change map to non-404 errors, not absence. Ownership mismatch keeps the existing authorization status. Delete's confirmed absence remains idempotent 204 and therefore does not emit a 404.

This is an additive vendor extension to the E2B error body; all four existing `web.ApiError` fields retain their current behavior.

### 7. Apply explicit operation gates with upstream-compatible statuses

Pause accepts `running`, `pausing`, and `paused`. A request already `pausing` joins the existing wait; `paused` succeeds immediately. `resuming` conflicts with HTTP 409.

Resume accepts `paused`, `resuming`, and `running`. A request already `resuming` joins the existing wait; `running` succeeds immediately. `pausing` conflicts with HTTP 409.

Same-direction joins preserve the existing first-writer-wins mutation and timeout ownership; a second request does not replace the first operation's parameters.

Connect:

- returns an already `running` Sandbox without starting Resume;
- starts Resume for `paused`;
- joins the Resume wait for `resuming`;
- rejects `pausing` with HTTP 400;
- returns no successful body until refreshed state is `running`.

Delete accepts every lifecycle state for an owned claimed CR. It returns 204 after delete/recycle is accepted, when lookup confirms absence, or when a concurrent delete returns NotFound. It does not convert ownership or non-NotFound backend failure to success.

Other direct Sandbox endpoints use the same projection and reasoned-404 boundary rather than treating an unrepresentable state as missing.

The upstream E2B OpenAPI checked for this design documents HTTP 409 for Pause and deprecated Resume conflicts, and HTTP 400 (but not 409) for Connect errors. The selected opposite-direction statuses therefore stay within the published endpoint response sets: Pause/Resume use 409 and Connect-on-`pausing` uses 400. See [E2B OpenAPI](https://github.com/e2b-dev/E2B/blob/main/spec/openapi.yml).

### 8. Preserve the three-change deployment boundary

The final implementation assumes:

- new Controller reason strings and canonical derivation from part 1;
- the approved short-ID cache resolver, infra interface, Projector/Store/Repairer, manager/Gateway feeder ownership, and conditional peer protocol;
- CR-based lookup/owner and lifecycle-aware adapter/disposition integration from part 2.

Part 3 does not reimplement those mechanisms. This keeps the final PR focused on consumer behavior and makes rollback to the pre-adoption wrapper possible while leaving the safer lookup and route preparation deployed.

## Risks / Trade-offs

- **[Risk] A five-state assumption remains.** -> Inventory every call site, make state switches exhaustive, and add consumer-specific table tests before considering the cutover complete.
- **[Risk] Active count changes SandboxClaim recovery.** -> Require the claimed label explicitly, prove owner/claimed-label atomicity on the claim write, and test the self-healing `max(status, actual)` path with unclaimed pool, converging, recycling, and terminal CRs.
- **[Risk] A future state aborts every SandboxSet reconcile.** -> Log and isolate unexpected states in the ignored/non-capacity group while declared-state coverage still requires deliberate mapping for known vocabulary.
- **[Risk] Upper layers recreate CRD lifecycle semantics.** -> Remove expected-state whitelists, raw `Phase`, API lifecycle constants, and condition/annotation inspection from manager-path lifecycle decisions; verify the dependency boundary by inventory and tests.
- **[Risk] Final adoption reintroduces a short-ID seam that an old state caller previously supplied.** -> Keep `GetSandboxID()`/`GetRoute()` absent, remove tuple `GetState()` only after the manager feeder uses normalized lifecycle, and verify Projector/Store/Repairer ownership and opaque-ID behavior remain unchanged.
- **[Risk] Waiters lose fast failures when `dead` disappears.** -> Assert diagnostic-specific outcomes such as `StartContainerFailed` independently from lifecycle state.
- **[Risk] Internal states leak through E2B.** -> Centralize conversion and assert serialized response bodies for list, describe, create, clone, resume, and connect.
- **[Risk] Strict clients reject the additive error field.** -> Use `omitempty`, retain existing fields/statuses, and keep the official state enum unchanged.
- **[Trade-off] List hides unrepresentable CRs while Describe returns reasoned 404.** -> This preserves the official list schema while direct lookup remains diagnostically precise.

## Migration Plan

1. Verify `1-define-sandbox-lifecycle-state-model`, the approved short-ID routing/cache/infra foundation, and the route-activating `2-prepare-sandbox-lifecycle-infrastructure` are implemented in their required partial order and deployed or included earlier in the same release.
2. Switch the compatibility wrapper; migrate all cache, SandboxSet, accounting, claim, and waiter consumers; then migrate manager/E2B to the normalized infra observation in the same implementation change.
3. Remove expected-state whitelists and obsolete tuple-state/raw-phase/recycle compatibility methods after their final callers are migrated.
4. Run focused package tests, dependency-boundary checks, and endpoint-level status/response-body tests before final controller and manager builds.
5. Roll components normally; peer deletion remains copy-only legacy `dead` over the short-ID conditional protocol, and no lifecycle CR data migration is required. Observe short-ID's separate no-rollback boundary after any persisted short label assignment.

Rollback can restore the legacy wrapper and consumers while leaving part 1 condition reasons and part 2 CR lookup/routes in place. Public `reason` is additive and can disappear on rollback without stored-data repair.

## Open Questions

None. Consumer grouping, count policy, normalized infra boundary, short-ID compatibility, expected-state whitelist removal, runtime error type, public projection, 404 taxonomy, upstream-compatible operation statuses, and rollout dependencies are fixed.
