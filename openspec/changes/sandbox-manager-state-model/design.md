## Context

`pkg/utils.GetSandboxState` currently derives `creating`, `available`, `running`, `paused`, or
`dead` for every component. That apparent consistency hides several different policies:

- SandboxSet needs to know whether a pool member is creating or available for claim.
- cache needs pool indexing, active counting, and operation-wait predicates.
- sandbox-manager needs pause/resume progress, temporary unavailability, removal, and completion.
- proxy and Gateway need a forwarding action, not lifecycle vocabulary.
- E2B exposes only `running` and `paused` and needs stable errors for other observations.

The shared helper under-describes Manager state and over-couples unrelated components. Its `dead`
result combines deletion, normal completion, failed completion, termination, and a claimed Running
Sandbox whose Ready condition is false.

The completed `sandbox-provider` prerequisite gives these components a neutral dependency boundary.
`pkg/sandboxprovider` owns cross-provider contracts, `pkg/sandboxprovider/sandboxcr` owns Kubernetes
CR observation, and `pkg/sandbox-manager/infra/sandboxcr` remains the Manager-specific adapter.
Controller uses provider pool predicates but does not consume the Manager state. Manager and
Gateway can now obtain routes from the same CR provider implementation.

## Goals / Non-Goals

**Goals:**

- Cover every state distinction required by Manager operations without mirroring every Controller
  phase or condition outcome.
- Return one deterministic state and non-empty diagnostic reason for every CR observation.
- Keep raw CR interpretation behind the sandboxprovider Sandbox methods.
- Make Manager and Gateway call one canonical GetRoute implementation that is derived from GetState.
- Preserve existing SandboxSet, pool-index, active-count, claim-selection, quota, and waiter behavior
  unless this change explicitly says otherwise.
- Remove lifecycle vocabulary from core Route and make forwarding/removal behavior explicit.
- Keep internal state out of public E2B response bodies.
- Keep mixed-version Manager and Gateway rollout fail-closed while Route changes from state to action.

**Non-Goals:**

- Adding a lifecycle field to the Sandbox CRD.
- Making Controller, SandboxSet, cache, or proxy consume the manager-oriented eight-state type.
- Adding Controller phases or in-place update reasons, or changing mutation/retry behavior other
  than the recycle-rejection fallback required to honor an accepted Delete.
- Distinguishing successful and failed completion in internal state or public unavailable reason.
- Distinguishing deletion from recycling in internal state or public unavailable reason.
- Tightening pool availability with Pod IP, lock, claimed label, or new health requirements.
- Changing quota liveness, route identity, peer membership, resource-version parsing, route
  ownership, or reconciliation topology. The prerequisite tombstone/authoritative-observation
  baseline and this change's equal-version action rank are the approved freshness additions.
- Reintroducing a Gateway-local or Manager-local raw CR routing policy.

## Decisions

### 1. One manager-oriented vocabulary behind the provider contract

`pkg/sandboxprovider` defines `SandboxState`, exactly eight state values, and
`SandboxStateObservation`. Its Sandbox capability returns the observation through `GetState`.

The CR implementation in `pkg/sandboxprovider/sandboxcr` delegates `GetState` to an unexported pure
derivation that accepts the observation time explicitly. The method supplies the current time;
package tests use an explicit time. No exported CR-to-state function exists.

Only Manager consumes the observation through its neutral infra port. Manager exposes
protocol-independent lifecycle outcomes through its Manager interface. E2B calls that interface and
owns public projection, HTTP status, and error-reason mapping without importing provider or infra.
Gateway does not branch on state; it obtains the result indirectly through the same provider's
GetRoute. Controller, SandboxSet, cache, and proxy cannot import or compare the eight state constants.

`Reason` is always non-empty and supports protected diagnostics. It is not a stable public enum and
must not be returned as public Sandbox state or Route data.

### 2. First-match derivation covers Manager needs

The first matching rule wins:

| Priority | State | Decisive facts |
|---:|---|---|
| 1 | `terminating` | deletion timestamp; observation time is after shutdown time; or phase Recycling/Terminating |
| 2 | `completed` | reserved-failed label without a higher removal fact; or phase Succeeded/Failed |
| 3 | `resuming` | phase Resuming; phase Paused with completed Paused condition and `spec.paused=false`; or exact post-resume initialization gate |
| 4 | `pausing` | phase Running with `spec.paused=true`; or phase Paused before the Paused condition is true |
| 5 | `paused` | phase Paused, `spec.paused=true`, and Paused condition true |
| 6 | `unready` | cleanup request metadata before removal starts; phase Upgrading; or an existing unsafe in-place update observation |
| 7 | `claimable` | the provider pool-available predicate is true |
| 8 | `running` | phase Running, not paused, Ready true, Pod IP non-empty, and no higher rule matched |
| 9 | `unready` | every other live observation, including Pending, Ready false/absent, empty Pod IP, empty phase, and an unsupported future phase |

Removal overrides completion because an object being removed is still in progress. Only
`completed` is terminal. `terminating` is a transition whose end is object absence.

The shutdown comparison preserves current behavior: the deadline is reached only when observation
time is strictly after `spec.shutdownTime`. A reserved-failed Sandbox without a higher-priority
removal fact is `completed`: it is excluded from future claims and cannot become active, including
when the caller selected forever retention. A finite retained failure becomes `terminating` once
its shutdown deadline expires.

Cleanup annotations alone record a request, not Controller acceptance. They derive `unready` until
the Sandbox enters Recycling or receives a deletion timestamp. This avoids deleting the route for
a request the Controller has not yet acted on.

### 3. Pause, resume, and update details are narrow

Pause and resume are explicit because Manager operations need to join or reject in-flight work:

- phase Resuming is always `resuming`;
- phase Paused with Paused true and `spec.paused=false` is `resuming`;
- phase Running with Resumed true is `resuming` only when RuntimeInitialized exists and is not true;
- phase Running with `spec.paused=true` is `pausing`;
- phase Paused before Paused true is `pausing`;
- phase Paused with `spec.paused=true` and Paused true is `paused`.

An absent RuntimeInitialized condition does not imply resume progress, preventing legacy healthy
objects from remaining `resuming` indefinitely.

The post-resume initialization rule precedes Running plus `spec.paused=true` and does not require
`spec.paused=false`. Resume is incomplete until runtime initialization converges, so Pause in that
window is an opposite-direction conflict. After initialization completes, a later pause observation
derives `pausing` normally.

Phase Upgrading and existing InplaceUpdate reasons InplaceUpdating or Failed are `unready`.
InplaceUpdate Succeeded falls through to Ready and Pod-IP evaluation. No new update reason is added;
Ready remains the final service signal after known unsafe markers.

### 4. Pool predicates remain separate and provider-owned

`pkg/sandboxprovider/sandboxcr` owns pure explicit-time pool creating and available predicates. They
preserve the former five-state helper's pool behavior:

- deletion, expired shutdown, Succeeded, Failed, and Terminating are neither creating nor available;
- Pending is creating;
- a SandboxSet-controlled non-terminal object is available when Ready is true and creating otherwise;
- available does not require Pod IP, lock availability, a claimed-label check, or revision match.

SandboxSet grouping/event handling and cache pool indexing use these predicates. Claim candidate
selection uses the same predicates plus its independent freshness, Pod-IP, lock, speculation, and
revision checks. Manager GetState uses only the available predicate after all higher-priority rules
to derive `claimable`.

The provider package never imports Controller. Controller remains self-contained and never calls
the manager-oriented GetState.

### 5. Other non-Manager consumers keep purpose-specific policy

`pkg/utils.GetSandboxState` is removed rather than redirected to the new model. The five
`api/v1alpha1.SandboxState*` strings are removed after compatibility adapters no longer use them.
Generic fact helpers may remain shared, but no generic lifecycle package may own or alias the
Manager state.

Behavior-preserving migrations remain local:

- active Sandbox counting keeps its reserved-failed and legacy-dead exclusion policy;
- pool indexing retains creating-or-available behavior;
- SandboxSet grouping, status, rolling update, and enqueue behavior remain unchanged;
- waiters keep their required CR facts and operation-specific fast failures;
- quota liveness remains an independent policy;
- claim selection keeps atomic safeguards beyond the `claimable` observation.

### 6. Recycle eligibility is a provider capability

The provider Sandbox capability exposes `IsRecyclable` instead of giving Manager raw `Phase` and
`IsRecycleEnabled`. The CR implementation returns true when cleanup is enabled, phase is Running,
and known Controller preconditions permit recycling, including the absence of persistent-volume
claims.

Manager preserves the trigger-recycle operation and metrics when IsRecyclable is true, and uses its
existing direct-delete path when it is false or triggering fails. A successful trigger creates a
cleanup request, which GetState reports as `unready` until Controller starts removal. Controller
uses the same known preconditions; if a request becomes ineligible before reconcile or another
precondition rejects it, Controller falls back to direct deletion rather than leaving a successful
Delete request serving indefinitely. Once phase is Recycling or deletion starts, GetState returns
`terminating`.

### 7. GetRoute is the only state-to-action mapping

The neutral core Route replaces lifecycle `State` with typed `Action` values Allow, Deny, and
Delete. Route identity, IP, owner, resource version, and access token remain unchanged.

`pkg/sandboxprovider/sandboxcr` owns the only state-to-action mapping:

| Provider observation | Action |
|---|---|
| `running` | Allow |
| `claimable`, `pausing`, `paused`, `resuming`, `unready` | Deny |
| `terminating`, `completed` | Delete |

The read-only CR view's GetRoute calls GetState exactly once and uses that observation to populate
the action together with route metadata. No metadata-only caller assignment and no second mapping
in Manager, proxy, or Gateway is allowed.

Manager route reconciliation calls GetRoute on its provider-backed Sandbox. Gateway wraps informer
objects in the same read-only CR view and calls GetRoute. Gateway must not inspect phase, Ready,
Pod IP serviceability, paused flags, RuntimeInitialized, InplaceUpdate, cleanup, or completion facts
to select an action.

For the same CR snapshot and explicit observation time, Manager and Gateway obtain identical route
metadata and Action. Independent wall clocks may cross a configured shutdown deadline at different
instants; both execute the same strict-after comparison, while the equal-version safety ordering and
deletion tombstone below resolve the temporary observation difference fail-closed.

Allow and Deny are retained active records. Data planes forward only Allow. Delete removes the
active route and retains only a non-forwarding decision tombstone containing route identity, UID,
resource version, and action rank. Missing or unknown Action is invalid after compatibility decoding
and cannot mutate a route or enable forwarding.

For one Sandbox UID, resource version remains the primary freshness key. When resource versions are
equal, safety action order is Delete greater than Deny greater than Allow. A stronger equal-version
decision replaces a weaker one; a weaker decision is rejected. A Delete tombstone rejects Allow or
Deny with the same or older resource version. A strictly newer resource version for the same UID,
or a new UID for a reused route ID, may replace the tombstone.

This ordering is required because shutdown expiry is derived from observation time without changing
the CR resource version. A fast clock may produce Delete while a slow clock still produces Allow
for the same snapshot. The tombstone makes the fast fail-closed decision monotonic and prevents a
late equal-version Allow from recreating the route. Tombstones are not returned by active-route List
or data-plane lookup and therefore do not violate the rule that Delete is not an active route.

### 8. Mixed-version Route compatibility is isolated and fail-closed

Core Route never contains lifecycle state. A wire adapter temporarily emits both action and a
legacy top-level state field:

| Action | Legacy field sent |
|---|---|
| Allow | `running` |
| Deny | `paused` |
| Delete | `dead` |

A valid received Action is authoritative. When Action is absent:

- Manager/proxy maps legacy `dead` to Delete, `running` to Allow, and every other value to Deny;
- Gateway maps legacy `running` to Allow and every other value to Delete, preserving its current
  peer-refresh behavior.

An old Gateway may delete a new Deny route instead of retaining it. These record-level differences
are allowed during mixed-version rollout because neither fallback converts a non-running legacy
value into Allow. Compatibility decoding occurs before freshness and action ordering, so legacy
Delete also creates a tombstone.

Arbitrary versions older than the `sandbox-provider` prerequisite are not supported peers for this
rollout because they can delete without retaining decision freshness or can emit legacy `running`
for observations the new model denies. Every Manager, proxy, and Gateway producer and receiver must
first run the prerequisite tombstone and conservative legacy-running baseline. The supported mixed
window is then baseline provider behavior versus this state-model behavior. New components validate
the normalized action before mutation.

The legacy field is not copied into core Route, stored as lifecycle state, or used by data-plane
filters. Resource-version comparison, registry ownership, peer selection, reconciliation topology,
and access-token redaction remain unchanged.

### 9. E2B remains a two-state public projection

Only Manager consumes SandboxStateObservation. It converts the provider observation into a
protocol-independent Manager lifecycle outcome. E2B consumes that outcome through the Manager
interface and owns the following public projection:

| Internal state | Public result |
|---|---|
| `running` | Sandbox state `running` |
| `pausing`, `paused`, `resuming` | Sandbox state `paused` |
| `claimable`, `unready` | unrepresentable, `SandboxTemporarilyUnavailable` |
| `terminating` | unrepresentable, `SandboxTerminating` |
| `completed` | unrepresentable, `SandboxCompleted` |
| confirmed absence | `SandboxNotFound` |

`web.ApiError` gains an optional `reason`. The four listed reason strings are the only stable
lifecycle-unavailable reasons. Internal state and diagnostic reason may appear in protected logs
after ownership succeeds but never in public Sandbox state.

The API layer does not call provider GetState, import sandboxprovider, or bypass Manager for lookup
or operation policy. Manager does not assign HTTP codes or construct E2B response models.

The public enum remains stable, but observation behavior is not fully backward compatible. The old
helper can expose claimed Upgrading, Recycling, empty-phase, and unsupported-phase objects as HTTP
200 `paused`. The new policy returns HTTP 404 SandboxTemporarilyUnavailable for
Upgrading/empty/unsupported observations and HTTP 404 SandboxTerminating for Recycling; List omits
all four.

Shared lookup first establishes existence and ownership without state whitelist or reserved-failed
short-circuit. GetState and each operation then apply policy. Confirmed absence remains distinct from
backend, timeout, cancellation, and authorization failures.

Operation policy is:

- Pause accepts `running`, `pausing`, and `paused`; Resume accepts `paused`, `resuming`, and `running`.
- Same-direction progress joins; opposite pause/resume progress returns HTTP 409.
- Connect returns `running`, starts or joins Resume for `paused`/`resuming`, and rejects `pausing`
  with HTTP 400.
- Snapshot and timeout mutation require `running`.
- Create, Clone, and Connect return a Sandbox body only after refreshed `running`. Resume verifies
  refreshed `running` before its existing empty success response.
- Delete accepts every state of an owned Sandbox plus confirmed/concurrent absence, while preserving
  authorization and non-NotFound backend failures.

### 10. Alternatives considered

- **Shared repository-wide lifecycle:** rejected because Controller pool and waiter policies answer
  different questions from Manager operations.
- **Gateway-local CR routing policy:** rejected because duplicated facts cannot guarantee exact new
  Manager/Gateway behavior and had already missed resume/update safety gates during review.
- **Manager-local state package:** rejected because Gateway would need either a forbidden Manager
  dependency or a second mapping; sandboxprovider is the neutral contract selected by the
  prerequisite change.
- **Eleven states mirroring Controller progress:** rejected because Controller detail would become
  upper Manager policy without adding useful decisions.
- **Keep raw phase for recycle:** rejected because IsRecyclable expresses Controller eligibility
  without exposing Controller phase or volume facts to Manager.
- **Keep lifecycle state in Route:** rejected because routing needs forwarding/removal action.
- **Treat every non-running Route as Delete:** rejected because Deny preserves a live unavailable
  record for recovery.
- **Hard wire cutover:** rejected because dual-field encoding is required for rolling upgrades.
- **Tighten pool available:** rejected because claim safeguards remain the correct atomic boundary.

## Risks / Trade-offs

- **A new Controller phase is served accidentally.** Unknown and empty phases fall through to
  `unready`, and GetRoute maps them to Deny.
- **Manager or Gateway bypasses GetRoute.** Source inventory and parity tests prohibit any second raw
  CR action policy.
- **Shutdown clocks differ.** The shared explicit-time rule is deterministic, and same-version
  Delete-over-Deny-over-Allow ordering plus deletion tombstones prevents a slow observer from
  reviving a route after a fast observer crosses the deadline.
- **Delete is persisted.** Upsert paths reject Delete and tests require removal-only behavior.
- **Mixed-version peers retain different non-forwarding records.** Every fallback remains
  fail-closed; action precedence and resource-version tests cover recovery.
- **A recycle request is rejected after Delete succeeds.** IsRecyclable screens known rejection
  facts, request-only observations deny traffic, and Controller falls back to direct deletion when
  it cannot start recycling.
- **Public clients receive internal strings.** Projection is centralized and response tests permit
  only running/paused plus stable error reasons.
- **Claimable sounds stronger than pool available.** Documentation and tests retain independent
  Pod-IP, freshness, lock, speculation, and revision safeguards.

## Migration Plan

1. Complete and verify the `sandbox-provider` prerequisite, including deletion decision tombstones
   and conservative legacy-running projection, and deploy that producer/receiver baseline to every
   Manager, proxy, and Gateway peer.
2. Add the eight-state contract to sandboxprovider, implement explicit-time CR derivation behind
   GetState, and add focused precedence tests.
3. Migrate pool, cache, claim, waiter, quota, and recycle consumers away from the legacy shared
   helper without changing their purpose-specific behavior.
4. Add Route Action and compatibility wire types, change provider GetRoute to the canonical
   state-to-action mapping, and migrate Manager, Gateway, proxy, registry, and data-plane consumers.
5. Atomically switch Manager to SandboxStateObservation, expose protocol-independent outcomes to
   E2B, and add API-layer stable unavailable reasons.
6. Remove legacy state helpers/constants and raw phase/recycle access, then complete focused tests,
   generated-artifact checks, static checks, component builds, and strict OpenSpec validation.

No stored CRD migration is required. Stable running and paused observations remain compatible;
documented legacy paused fallbacks change to reasoned unavailable responses. The legacy wire state
is removed only by a later compatibility cleanup.

## Open Questions

None. Provider ownership, consumers, state precedence, canonical GetRoute mapping, mixed-version
safety, public projection, and rollout order are fixed.
