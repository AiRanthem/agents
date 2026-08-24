---
title: Sandbox-manager State Model and Layering
authors:
  - "@AiRanthem"
reviewers: []
creation-date: 2026-07-15
last-updated: 2026-08-24
status: provisional
---

# Sandbox-manager State Model and Layering

## Summary

**Scope discipline:** this proposal does not solve State, Route, or cache synchronization between
sandbox-manager replicas. Healthy replicas continue serving requests independently, and the
existing primary Lease remains limited to background coordination. Cross-replica observations may
temporarily disagree. This proposal must not make that existing limitation worse by allowing a
stale observation to mutate another delivery, release its quota, or remove its Route. A separate
design will define replica synchronization.

This proposal defines one backend-neutral structured State for sandbox-manager. A shared
Sandbox-CR-specific mapper translates native Sandbox facts once. Infra returns the resulting State
and an Observation to Manager. Manager applies lifecycle and capability policy without reading
Sandbox CR Phase, Conditions, or reasons. API authenticates the caller, checks caller-to-owner
authorization, and maps domain results to the public protocol.

State contains four independent dimensions:

    State {
        Delivery    unclaimed | claimed | ready
        Release     none | due | terminal | committed
        PauseResume none | pausing | resuming
        Workload    provisioning | ready | paused | unready | completed
    }

`Delivery` separates persisted ownership from completed delivery. `claimed` proves that one owner
and DeliveryEpoch have been assigned, but the Sandbox remains externally invisible and cannot
route traffic. `ready` is persisted only after the Controller has observed the claimed workload
revision and every required delivery action, including the initial TrafficPolicy, has succeeded.

`Release` distinguishes a reversible deadline, a stopped workload, and an irreversible release
commit. Those facts have different Kill, Route, visibility, and quota behavior. An absent object is
a separate NotFound result, not a synthetic State.

Every state-sensitive operation uses one Observation:

    Observation {
        State         State
        Owner         string
        MutationToken opaque
    }

The existing persisted claim-lock UUID is the immutable DeliveryEpoch for one claim delivery. A
manager-owned top-level Sandbox annotation records that the current epoch is ready. The token binds
the observation to that DeliveryEpoch and one backend object version. Infra must not transparently
retry an operation after the token becomes stale. This prevents an operation authorized for one
owner from crossing a recycle boundary and affecting the next owner of the same Sandbox CR.

`ShutdownTime` is an instruction to Controller, not an immediate traffic or quota boundary. A
locally reached deadline produces `Release=due`, but a ready delivery remains owner-visible and its
Route is derived from workload capability until Controller persists an irreversible release fact.
While due, only List, Describe, and Kill are admitted for that ready delivery; other owner
capabilities cannot rescue the deadline. No deadline is added to the Route wire shape.

Claim and ready persistence form a two-stage delivery. Claim persistence is not a visibility
commit: Create or Clone remains hidden and unroutable while Delivery is `claimed`. The final
`claimed -> ready` metadata patch is the visibility commit and the successful-response
linearization point. It occurs only after all delivery work has finished, so a Sandbox may become
visible shortly before the handler returns but never while its delivery is incomplete.

For a selected ready warm Sandbox, that final annotation Patch changes the successful-path write
count from three to four without an initial TrafficPolicy, or from four to five with one. It changes
no spec, Pod template, or status and therefore causes no dependent write. The extra API-server write
rate is exactly the successful Create or Clone rate.

The proposal remains provisional. It defines per-observation safety and delivery fencing, not
multi-replica consistency, linearizable public responses, or recovery from partial delivery.

## Background

Sandbox state affects pool candidate selection, Create and Clone completion, Pause and Resume,
traffic forwarding, owner visibility, quota, and release. When each path interprets Sandbox CR
Phase, Conditions, annotations, or local time independently, the same backend fact can produce
different business results.

A flat lifecycle string also collapses questions that are not interchangeable. A pool Sandbox that
is still starting, a claimed Sandbox that is temporarily unready, a stopped workload awaiting
cleanup, a reached deadline, and an accepted deletion all cannot be represented safely as one
`dead` or `releasing` value.

Recycle makes the observation boundary especially important. A successful recycle keeps the same
Sandbox CR and UID, clears the old claim, and later permits a new owner to claim it. Checking owner
and State before a mutation is insufficient if the backend mutation can silently retry against the
new claim.

Creation has another boundary: a ready warm Pod can already serve while runtime initialization,
credentials, CSI mounts, and the initial TrafficPolicy are still being established. Persisted
ownership alone therefore cannot prove that the Sandbox is safe to expose. In particular, allowing
a running Route before the TrafficPolicy and the policy-selecting Pod labels are durable creates a
Route-before-policy window that no delivery-epoch fence can repair after the fact.

State does not create a second backend lifecycle beside the Sandbox CR. It creates a dependency
boundary: Sandbox CR Infra interprets native facts once, while Manager and API depend on neutral
meanings and conditional capability contracts.

### Goals

- Give release due, terminal workload, and irreversible release commit distinct meanings.
- Keep Sandbox CR Phase, Conditions, annotations, and reasons out of Manager and API business
  decisions.
- Make every state-sensitive capability conditional on the claim delivery that was authorized.
- Use one CR mapper for Infra observations and Route projection.
- Keep workload capability separate from owner visibility and quota release.
- Define safe, typed provisioning and ready predicates.
- Prevent a stale authorized operation from affecting another claim delivery.
- Give ownership assignment and completed delivery separate persisted commit points.
- Keep Route and every owner capability closed until the initial TrafficPolicy and all other
  delivery requirements are complete.

### Non-goals

- This proposal does not introduce SandboxRecord or another authoritative visibility store.
- It does not preserve visibility when the Sandbox CR is actually absent.
- It does not make `ShutdownTime` a strict wall-clock traffic cutoff and does not add a deadline to
  Route.
- It does not make Claim or Clone recoverable from an arbitrary Manager process crash.
- It does not model which delivery steps have completed, introduce a failed Delivery state, or
  define retry, rollback, cleanup, quota, or retention behavior for partial delivery. This proposal
  specifies the successful path and records partial-delivery cases as open questions.
- It does not coordinate observations between Manager replicas or synchronize Manager and Gateway
  informer state. It introduces no persistent Sandbox-ID resolver or business-API primary gate.
- It does not otherwise change Checkpoint API or lifecycle semantics; only claim-delivery fencing
  for creation, production, completion, and consumption is in scope.
- Except for the release-safety prerequisite in Implementation Notes, it does not describe
  migration, rollout, implementation tasks, or test procedures.

## Target Design

### 1. Overall Boundary

Dependencies follow one direction:

    Sandbox CR
        |
        | pkg/sandboxstate/sandboxcr mapper
        v
    pkg/sandboxstate State + Observation
        |                                   |
        | Infra observation/capability      | sandboxroute projection
        v                                   v
    Manager business policy -> API     manager and gateway Route stores
                                                |
                                                v
                                      gateway traffic admission

`pkg/sandboxstate` defines only backend-neutral State, Observation, enum validation, and opaque
token contracts. It does not import the Sandbox API. `pkg/sandboxstate/sandboxcr` owns the Sandbox
CR mapping and may import the Sandbox API. Both `infra/sandboxcr` and `sandboxroute` use the CR
mapper. Manager and neutral Infra interfaces use only the neutral package.

The desired workload revision is the policy-neutral hash of `spec.template` or `spec.templateRef`.
The Controller and CR mapper use the same neutral revision function without introducing a
Controller-to-Manager dependency.

The mapper accepts the clock explicitly:

    FromSandbox(sandbox, now) -> State

Local time may change `Release` between `none` and `due`. Route projection deliberately ignores
that difference, so the same persisted CR facts still produce the same Route even when Manager and
Gateway clocks differ.

The Sandbox Controller continues to own native status and workload reconciliation. It also owns the
irreversible meaning of a persisted cleanup trigger: once that trigger exists for a claim, the
Controller must recycle or delete that claim and must never restore it to service.

Every healthy Manager replica may continue to serve owner-facing APIs. The primary Lease controls
only background reconciliation jobs. Route and informer disagreement between replicas retains its
existing eventual behavior and is not an authority for visibility, authorization, or absence.

### 2. State and Observation Contracts

| Field | Values | Question answered |
|---|---|---|
| Delivery | unclaimed / claimed / ready | Has ownership been persisted, and has this delivery completed? |
| Release | none / due / terminal / committed | What release fact has been observed? |
| PauseResume | none / pausing / resuming | Is an ordinary Pause or Resume transition in progress? |
| Workload | provisioning / ready / paused / unready / completed | What workload capability is currently proven? |

The mapper turns incomplete input and stale positive status into a valid conservative State,
normally Workload=unready. An unknown output State enum value or invalid State combination fails
validation; Infra returns a neutral internal or unavailable error instead of presenting it as
invisible or NotFound. Only a validated State enters Manager policy. Route projection fails closed
to dead when it cannot obtain a valid State. NotFound remains outside State.

#### Observation and MutationToken

Infra lookup returns State, the neutral owner identity, and one opaque MutationToken from the same
snapshot. The token binds at least:

- Sandbox UID and backend object version;
- Delivery, the persisted claimed marker, and owner;
- the DeliveryEpoch, which is the current persisted claim-lock UUID;
- the public Sandbox ID for the current delivery.

The DeliveryEpoch is non-secret, is persisted atomically with owner and claimed identity, never
rotates within one claim, and is cleared by successful recycle. No new Sandbox epoch field is
introduced.

A `claimed` or `ready` observation is valid only when owner, DeliveryEpoch, and a uniquely
resolvable public Sandbox ID are non-empty and a MutationToken can be constructed. Invalid
delivery identity returns neutral internal or unavailable, and Route projection fails closed. It
must never appear as NotFound, owner mismatch, or a running Route.

The token is required by Pause, Resume, Connect, Snapshot, Set timeout, Update network, Browser use,
checkpoint creation, delivery finalization, and release commit. It applies to workload access as
well as CR writes.

Infra validates the token at the effective backend boundary of each capability:

- Sandbox CR writes test the observed resource version, Delivery, claimed marker, owner, public ID,
  and DeliveryEpoch. A failed precondition returns conflict and is never retried against a new
  claim.
- Browser requests carry a delivery-scoped runtime credential, and runtime rejects a credential
  from another DeliveryEpoch. Browser is not admitted when no verifiable credential exists.
- TrafficPolicy and its selected Pod identity carry the DeliveryEpoch. Create, update, read, and
  delete paths match both Sandbox ID and DeliveryEpoch.
- Route carries DeliveryEpoch and rejects stale events from another delivery.
- Checkpoint and its SandboxTemplate carry DeliveryEpoch. The producer validates it before work and
  before completion; consumers reject results from another delivery.
- Connect obtains a new Observation after Resume and continues only when DeliveryEpoch is unchanged.

When a capability boundary cannot prove a matching DeliveryEpoch, the capability returns conflict
or unavailable. It must not fall back to Sandbox name, UID, public ID, or owner reference alone.

These fences prevent a stale operation from reaching a later delivery through a reused name,
legacy Sandbox ID, or the same Sandbox UID. They do not distinguish an already-forwarded external
Gateway request when traffic authentication is disabled and the public Sandbox ID is reused; that
client-traffic limitation is outside this proposal.

When validation fails, Infra returns a conflict without retrying the business mutation against a
new snapshot. Manager obtains a new Observation and re-evaluates lifecycle admission. API then
re-evaluates caller-to-owner authorization. Manager may retry only if the refreshed Observation
still describes the same authorized claim and still admits the operation.

#### Delivery

Delivery combines ownership assignment and delivery completion without exposing the individual
post-claim steps:

| Delivery | Persisted facts | External meaning |
|---|---|---|
| unclaimed | The sandbox-claimed marker is not true and no ready fact exists | No user delivery owns the Sandbox |
| claimed | The claimed marker and complete claim identity exist, but no ready fact exists | Ownership is reserved; the Sandbox is hidden and unroutable |
| ready | The claimed marker and complete claim identity exist, and the ready fact equals the current DeliveryEpoch | Delivery is complete and may become owner-visible |

The ready fact is the manager-owned top-level Sandbox annotation
`agents.kruise.io/delivery-ready`; its value is the current DeliveryEpoch. It is not part of spec,
the Pod template, or status. Persisting it therefore does not increment Sandbox Generation, change
the desired workload revision, or require a Pod or status mutation. A ready fact that is non-empty
but does not equal the current DeliveryEpoch is invalid; it must never make the Sandbox visible or
routable.

For a pool candidate, Infra atomically persists lock, owner, Sandbox ID, the claimed marker, and
removal of any old ready fact. A newly created Sandbox contains those facts in its create write.
This first commit produces Delivery=`claimed`. It reserves one delivery identity but proves
nothing about delivery completion.

After all delivery requirements succeed, Infra conditionally patches the ready fact from absent to
the current DeliveryEpoch. The patch succeeds only when the claimed marker, owner, public ID,
DeliveryEpoch, backend object version, and `Release=none` still match the observation used to
authorize finalization. Conflict is re-observed and re-authorized; it is never transparently
retried across a different delivery. This second commit produces Delivery=`ready` and is the only
visibility commit.

Successful recycle first persists removal of claim-scoped SandboxPaused, SandboxResumed, and
RuntimeInitialized conditions. It then atomically clears the old claim, owner, lock, public Sandbox
ID, ready fact, and cleanup trigger as the final claim-clear write. The object cannot become a
candidate before that final write. A later claim has a different DeliveryEpoch and MutationToken
even though the CR UID is unchanged.

#### Release

The mapper uses the first matching release rule:

1. `committed` when DeletionTimestamp exists, a cleanup trigger is persisted, or Phase is
   Recycling or Terminating;
2. `terminal` when Phase is Succeeded or Failed;
3. `due` when ShutdownTime exists and `now.After(ShutdownTime)` is true;
4. `none` otherwise.

The exact deadline is not due. Typed serving freshness is required before granting positive
capability, but status that already reports terminal, Recycling, or Terminating remains
conservative and does not restore service.

`due` is reversible. Controller's paused-retention policy may persist a later ShutdownTime before
deletion is committed, after which a new observation returns `none`. For Delivery=`ready`, only
List, Describe, and Kill are admitted while `due` remains observed. Pause, Resume, Connect,
Snapshot, Set timeout, Update network, and Browser use cannot advance the deadline or otherwise
rescue the Sandbox. The Controller may conditionally commit timeout release only for the
DeliveryEpoch whose deadline it observed. Owner visibility, public state, traffic, and quota remain
based on the other State dimensions until that commit is persisted.

`terminal` says that the workload has stopped, not that cleanup is committed. It hides a ready
delivery and denies traffic, but Kill must still commit release and quota remains held.

`committed` is monotonic for one claim delivery. A persisted cleanup trigger counts as committed
because Controller has the following contract:

- a recyclable Sandbox enters recycle;
- a paused Sandbox, a Sandbox with PVCs, or another Sandbox that cannot recycle is deleted;
- recycle failure may retain the object only as hidden committed cleanup with eventual deletion;
- no rejection or failure path may clear the release fact and return the same claim to service;
- only successful recycle may clear the trigger, together with all old claim identity.

These rules make a successful cleanup-trigger write sufficient for Kill success and quota release;
Manager does not need a second recycle acknowledgement.

For Delivery=`ready`, release policies are independent of PauseResume and Workload. Delivery values
`unclaimed` and `claimed` remain externally invisible and make Kill an idempotent no-op regardless
of this table:

| Observation | Owner visibility | Kill | Quota | Traffic |
|---|---|---|---|---|
| Release=none | Evaluate other State | Commit release | Keep | Evaluate capability |
| Release=due | Evaluate other State | Commit release | Keep | Evaluate capability |
| Release=terminal | Hidden | Commit cleanup | Keep | Deny |
| Release=committed | Hidden | Idempotent success | Releasable | Deny |
| NotFound | Hidden | Idempotent success | Converge release | No Route |

#### PauseResume

PauseResume uses typed desired and observed pause facts rather than whole-object generation. A
timeout-only spec update therefore cannot erase an in-progress Pause or Resume.
Delivery=`unclaimed` always maps to `none`, even if claim-scoped transition Conditions remain on a
recycled object.

The exact Condition Types are `SandboxPaused` (`SandboxConditionPaused`), `SandboxResumed`
(`SandboxConditionResumed`), and `RuntimeInitialized`.

The first matching rule wins:

1. Delivery is `unclaimed`; Release is terminal or committed; or Phase is Succeeded, Failed, or
   Upgrading: `none`.
2. Phase is Resuming; or Phase is Paused, SandboxPaused=True, and spec.paused=false; or Phase is
   Running, SandboxResumed=True, and RuntimeInitialized is missing or not True: `resuming`.
3. Phase is Running and spec.paused=true; or Phase is Paused and SandboxPaused is missing or not
   True: `pausing`.
4. Otherwise: `none`.

An internal Controller wake-up during upgrade is not an ordinary Resume.

#### Workload

Workload freshness is scoped to serving-related facts. The mapper computes the desired workload
revision from `spec.template` or `spec.templateRef` and compares it with `Status.UpdateRevision`.
PauseTime and ShutdownTime changes do not change this revision. The mapper then uses the first
matching rule:

1. Phase Succeeded or Failed: `completed`.
2. Phase Paused and SandboxPaused=True: `paused`.
3. Phase Running, desired revision equals `Status.UpdateRevision`, Ready=True,
   `Status.PodInfo.PodIP` is non-empty, and InplaceUpdate is absent or has a recognized safe result:
   `ready`.
4. Phase Pending and desired revision equals `Status.UpdateRevision`: `provisioning`.
5. Every other input: `unready`.

For InplaceUpdate, absent, True/Succeeded, and False/Failed are serving-safe results.
False/InplaceUpdating, Unknown, and unknown or invalid status/reason combinations are unready.
False/Failed records that the desired update did not converge, but it does not override serving
capability: when Ready=True and every other ready predicate passes, the existing workload remains
ready. Update convergence and serving capability are separate facts.

Ready missing, False, or Unknown is not ready. A revision mismatch, missing PodInfo.PodIP,
Upgrading, unknown native Sandbox CR Phase, or incomplete State is unready unless a higher
conservative terminal rule applies. RuntimeInitialized missing, False, or Failed after Resume does
not override Workload when Ready=True; it keeps PauseResume=resuming, which independently denies
Route and capability admission. An InplaceUpdate failure is never provisioning.

SandboxSet ownership does not prove provisioning. In particular, SandboxSet-controlled
Running+Ready!=True is unready. The CR CreationTimestamp is only an auxiliary speculation-age
threshold after Workload is already provisioning; age never proves provisioning by itself.

Backend reasons may remain in Infra diagnostics, but Manager and API do not branch on them. A
future backend may map another explicit typed progress fact to provisioning, but it must define that
fact in its own mapper.

#### Valid Combinations

| State combination | Meaning |
|---|---|
| Delivery=unclaimed, Release=none, Workload=ready | Available pool Sandbox |
| Delivery=claimed, Release=none, Workload=ready | Warm workload assigned to an incomplete, hidden delivery |
| Delivery=ready, Release=none, Workload=ready | Normal user Sandbox |
| Delivery=ready, Release=due, Workload=ready | Deadline reached; Controller has not committed release |
| Delivery=ready, Release=terminal, Workload=completed | Workload stopped; cleanup is still required |
| Delivery in {claimed, ready}, Release=committed | Hidden delivery undergoing cleanup |
| Delivery=unclaimed, Release=committed | Unclaimed object being deleted or recycled |

Delivery=`unclaimed` alone does not make an object a candidate. Release must be none, the object
must belong to the target pool and be unlocked, and its Workload must satisfy candidate policy.

### 3. Layer Responsibilities

| Layer | Owns | Does not own |
|---|---|---|
| API | Authentication, caller-to-owner authorization, protocol validation, HTTP mapping, E2B projection | CR status interpretation, Route-based existence, lifecycle policy |
| Manager | Resource visibility, candidate policy, quota, lifecycle and capability admission, orchestration after conflict | CR Phase, Conditions, annotations, HTTP semantics |
| Infra | Observation, CR mapping, conditional backend capabilities, waits, conflicts, claim fencing | Caller authentication, HTTP status, quota policy |
| Controller | Native CR and workload reconciliation, irreversible cleanup-trigger outcome | Manager or API policy, dependencies on Manager or Infra implementations |

The API obtains the authenticated owner identity and supplies it as an explicit selection or lookup
constraint. Manager derives resource visibility from neutral State. API compares Observation.Owner
with the authenticated caller. Non-Kill APIs map absence, invisibility, and owner mismatch to the
same public 404; Kill applies its separate uniform HTTP 204 contract. This keeps authentication and
authorization in API while keeping backend-neutral visibility policy in Manager.

Route is never the authority for Sandbox existence or owner authorization. Missing, stale, or
non-running Route state cannot reject a request before the authoritative Observation is evaluated.

List applies authenticated owner and resource-visibility filtering before pagination. Describe and
all single-Sandbox APIs use the same observation and authorization boundary.

Manager replicas continue to accept owner-facing API traffic independently. The primary Lease is
not an API admission or readiness gate. This proposal neither synchronizes their observations nor
claims identical responses across replicas; its safety guarantee begins after one replica has
obtained an Observation.

### 4. Claim and Clone

Manager uses these candidate rules:

| Candidate | Required facts |
|---|---|
| Normal | Delivery=unclaimed, Release=none, PauseResume=none, Workload=ready, target pool, unlocked |
| Speculative | Delivery=unclaimed, Release=none, PauseResume=none, Workload=provisioning, target pool, unlocked, speculation age elapsed |
| Ineligible | Delivery is claimed or ready; Release is due, terminal, or committed; Workload is paused, unready, or completed; wrong pool; or locked |

CreationTimestamp may be used only as the elapsed-time threshold after the typed provisioning
predicate is true. A zero configured duration disables speculative selection.

Claim and Clone follow this contract:

1. Manager validates the request and reserves quota.
2. Infra atomically persists or creates owner, lock, public Sandbox ID, DeliveryEpoch, and the
   claimed marker, producing Delivery=`claimed`.
3. Manager waits until Controller has observed the current desired workload revision, the selected
   Pod carries the current owner and DeliveryEpoch metadata, and Workload is ready.
4. Manager completes runtime initialization, credentials, CSI, and every other required delivery
   action. If the request requires an initial TrafficPolicy, that policy is persisted with the same
   DeliveryEpoch before delivery can complete.
5. Infra conditionally patches the ready fact to the current DeliveryEpoch, producing
   Delivery=`ready`.
6. Create or Clone returns success only after the ready patch succeeds.

Delivery=`claimed` is an internal reservation, not resource visibility. List, Describe, Kill, and
every other owner API treat it as invisible, and Route projection remains non-running even when the
warm Pod itself is ready. Consequently, the initial TrafficPolicy and its policy-selecting Pod
labels become durable before any Route can run. Update network cannot race initial network setup
because no user capability is admitted before Delivery=`ready`.

The `claimed -> ready` patch is the successful-response linearization point. It re-validates the
same DeliveryEpoch and `Release=none`; a concurrent release or recycled delivery prevents success.
After the patch, informer propagation may make the Sandbox visible shortly before Create or Clone
returns, but every delivery requirement is already complete.

#### Marginal Write Cost

The final ready fact adds exactly one successful Sandbox metadata Patch to each successful Create
or Clone. The following count covers the selected, already-ready warm Sandbox and its existing Pod.
It assumes no conflict or retry, no image or resource in-place update, and excludes SandboxSet
replenishment, Kubernetes Events, and scheduler or kubelet writes.

The three-write claim-only reference consists of the Manager claim update to the Sandbox, the
Controller patch that brings the selected Pod metadata to the claimed revision, and the Controller
status patch that records that observed revision. Initial network configuration adds one
TrafficPolicy create. Requested ID-token delivery adds one Sandbox annotation patch. Two-stage
delivery adds only the final ready annotation patch.

| Successful delivery path | Sandbox writes | Pod writes | TrafficPolicy writes | Total writes | Ready-patch increase |
|---|---:|---:|---:|---:|---:|
| Claim-only reference, no TrafficPolicy | 2 | 1 | 0 | 3 | - |
| Two-stage delivery, no TrafficPolicy | 3 | 1 | 0 | 4 | +1 (+33%) |
| Claim-only reference, with TrafficPolicy | 2 | 1 | 1 | 4 | - |
| Two-stage delivery, with TrafficPolicy | 3 | 1 | 1 | 5 | +1 (+25%) |
| Two-stage delivery, with TrafficPolicy and ID token | 4 | 1 | 1 | 6 | +1 (+20% versus the corresponding claim-only path) |

The additional Patch changes one fixed annotation key to one 36-character UUID DeliveryEpoch
value. Its payload does not grow with Sandbox spec size, Pod count, or the number of delivery steps.
It does not increment Generation and therefore adds no dependent Pod Patch or Sandbox status
Patch. It produces one additional Sandbox watch event; Controller observes a delivery-only change
without a write. At a successful Create or Clone rate of `R` per second, the added API-server write
rate is exactly `R` small metadata Patches per second.

### 5. Owner Visibility and Public State

Manager derives caller-independent resource visibility:

    ResourceVisible =
        Sandbox exists
        && State.Delivery == ready
        && State.Release in {none, due}

API then applies owner authorization:

    OwnerVisible = ResourceVisible && Observation.Owner == authenticated caller

| Situation | Non-Kill owner API | Kill |
|---|---|---|
| NotFound | HTTP 404 | HTTP 204 |
| Delivery=unclaimed or claimed | HTTP 404 | HTTP 204, no-op |
| Release=terminal | HTTP 404 | Commit cleanup for the same claim |
| Release=committed | HTTP 404 | HTTP 204 |
| Delivery=ready and owner mismatch | HTTP 404 | HTTP 204, no-op |
| OwnerVisible | Apply State admission | Commit release for the same claim |

Release=due remains OwnerVisible, but Kill must commit release and every owner capability other
than List, Describe, and Kill is rejected while the deadline remains due.

Kill returns HTTP 204 for NotFound, Delivery=`unclaimed` or `claimed`, Release=committed, and owner
mismatch. An owner mismatch is recorded only in protected audit logs and has no resource, Route, or
quota side effect. For the correct owner of a ready delivery with Release=none, due, or terminal,
HTTP 204 requires a successful claim-fenced release commit. Backend failure or invalid delivery
identity returns the mapped unavailable or internal result instead of false success.

List contains only OwnerVisible Sandboxes and filters them before pagination. Describe returns 200
for every OwnerVisible ready delivery, including paused, provisioning, unready, and due
observations.

E2B public state remains intentionally small:

| State | E2B state |
|---|---|
| OwnerVisible, PauseResume=none, Workload=ready | running |
| Every other OwnerVisible State | paused |

### 6. Operation Admission

The following table applies only after Delivery=`ready` and OwnerVisible authorization. Every
admitted operation still requires a valid MutationToken or claim-delivery fence. Delivery=`claimed`
never reaches this table.

Release=due is an independent denial for every capability in this section. Only List, Describe,
and Kill remain admitted until Controller changes the deadline or persists release commit.

| PauseResume and Workload | Pause | Resume | Connect |
|---|---|---|---|
| none + ready | Start Pause | No-op success | Connect |
| none + paused | No-op success | Start Resume | Resume, then connect |
| pausing + any Workload | Join and wait | HTTP 409 | HTTP 400 |
| resuming + any Workload | HTTP 409 | Join and wait | Wait, then connect |
| none + provisioning or unready | HTTP 409 | HTTP 409 | HTTP 500 |

Snapshot, Set timeout, Update network, and Browser use require PauseResume=none and Workload=ready.
Their public rejection results remain:

| API | OwnerVisible but not admitted |
|---|---|
| Snapshot | HTTP 400; no Sandbox mutation |
| Set timeout | HTTP 500; no deadline mutation |
| Update network | HTTP 500; no policy mutation |
| Browser use | HTTP 500 |

As one consequence, Set timeout is not admitted for Release=due even when Workload=ready. A
Controller-persisted paused-retention extension may later change Release back to none, after which a
new Set timeout observation is evaluated normally.

Manager owns same-direction join, opposite-direction conflict, and refreshed admission after a
token conflict. Infra owns only the conditional backend action and wait. API owns the status-code
mapping. Composite Connect obtains a new Observation after Resume and does not reuse the original
token for workload access.

### 7. Route

`sandboxroute.RouteFromSandbox` uses the same Sandbox CR mapper as Infra, then combines State with
route identity, DeliveryEpoch, and `Status.PodInfo.PodIP`. Route does not carry full State or
ShutdownTime.

DeletionTimestamp, a confirmed delete event, or a tombstone deletes the Route. For another existing
object, the first matching rule wins:

| State and route data | Route.State |
|---|---|
| Any of: Release=terminal or committed; Workload=completed; invalid or incomplete State | dead |
| Delivery=claimed | dead |
| Delivery=ready, Release=none or due, PauseResume=none, Workload=ready, IP exists | running |
| PauseResume is pausing or resuming, or Workload=paused | paused |
| Workload=unready | dead |
| Workload=provisioning or IP missing | creating |
| Delivery=unclaimed, Release=none, Workload=ready, IP exists | available |
| Any other combination | dead |

Release=due never changes Route. If no CR mutation occurs when ShutdownTime passes, Gateway may
continue forwarding the existing running Route. Controller persistence of DeletionTimestamp,
Terminating, Recycling, or another committed fact produces the event that denies or deletes Route.
This is the selected eventual deadline contract.

Gateway forwards only Route.State=running. The ready metadata event is the earliest event that can
produce that state, so a running Route implies that initial network policy creation and the other
delivery requirements completed first. Route identity, DeliveryEpoch, and version ordering reject
stale events from another claim delivery, but Route presence or state never determines Sandbox
existence, owner authorization, or Manager State in the opposite direction. DeliveryEpoch does not
make an already-forwarded unauthenticated client request delivery-aware.

### 8. Quota and Failure Behavior

Quota is not a State dimension. Manager reserves quota before the first delivery commit and treats
it as active after Delivery becomes `claimed`, even though the Sandbox is not externally visible.

Quota is releasable only when Release=committed or the backend object is authoritatively NotFound.
Release=due and Release=terminal keep quota. A cleanup trigger is committed only because the
Controller contract guarantees recycle-or-delete and forbids restoration of the same claim.

If a release write fails, Release does not become committed, Kill returns the backend-derived
error, owner visibility is unchanged, and quota stays held. Infra reports neutral NotFound,
conflict, unavailable, or operation failure. Manager combines the latest Observation with that
result. API maps the domain result without inspecting CR state.

### 9. External Contract

| Scenario | Target behavior | Why |
|---|---|---|
| Owner mismatch | Non-Kill APIs return HTTP 404; Kill returns HTTP 204 with no side effect | Keep Kill idempotent without creating an existence oracle |
| Reached ShutdownTime on a ready delivery before Controller commit | Visibility, public state, and Route remain governed by the other State dimensions; due alone does not change Route; only List, Describe, and Kill are admitted; quota stays held | Deadline is a Controller instruction, not a release commit |
| Persisted cleanup trigger for a ready delivery | Kill may return success and quota may release; Controller must recycle or delete | Trigger is an irreversible current-claim commitment |
| Terminal Succeeded or Failed on a ready delivery | Hidden and Route dead; Kill still commits cleanup; quota stays held | Workload termination is not cleanup completion |
| Stale Observation after recycle and re-claim | CR writes, Browser, TrafficPolicy, Route, Checkpoint, and composite Connect are fenced and cannot affect the new owner | UID alone does not identify one delivery |
| Create or Clone before ready commit | Hidden from every owner API and Route dead | Persisted ownership does not prove completed delivery |
| Initial TrafficPolicy setup | The current-epoch policy and policy-selecting Pod labels exist before the ready commit; Update network is not reachable earlier | No traffic or owner mutation can race incomplete initial policy |
| Ready commit succeeds | Sandbox may become owner-visible and Route may become running; Create or Clone may return success | The ready patch is the visibility and successful-response commit |
| Running with Ready missing, False, Unknown, revision mismatch, or unsafe update | Workload=unready and never a speculative candidate solely because of age | Service or progress cannot be proven |
| InplaceUpdate=False/Failed with Ready=True | Workload may remain ready when all other serving predicates pass | Update convergence and existing workload capability are separate |
| Claimed or ready delivery identity is incomplete or conflicting | Internal or unavailable; Route fails closed | Corruption must not appear invisible or routable |
| More than one Manager process | Replicas may disagree temporarily; no replica may use a stale authorized observation to mutate another delivery | Replica synchronization is a separate design |

## Open Questions

### Partial Delivery

This proposal deliberately defines only the successful `unclaimed -> claimed -> ready` path and
does not introduce a failed Delivery value or per-step progress. The following partial outcomes are
possible in a real system but are not resolved here:

- runtime initialization succeeds before credential delivery or CSI mounts finish;
- some CSI mounts succeed before a later mount fails;
- the current-epoch TrafficPolicy is created but the ready patch does not complete;
- Manager stops after any subset of delivery actions and before the ready patch.

Without the ready fact these outcomes remain externally invisible and cannot produce a running
Route. A separate design must decide whether the same epoch resumes, rolls back, or commits release;
how partial runtime, credential, CSI, and TrafficPolicy effects are reconciled; when quota is
released; how long a claimed delivery may remain; and what operators can observe or repair. This
proposal makes no recovery, cleanup, retention, or latency guarantee for those cases and
deliberately leaves those guarantees to separate future design work.

## Implementation Notes

The Controller recycle-or-delete contract is a hard release prerequisite. Every Controller instance
must first be upgraded and verified to delete paused, PVC-backed, or otherwise non-recyclable
Sandboxes after a cleanup trigger, and to retain failed recycle only as committed cleanup with
eventual deletion. Only after that prerequisite is satisfied may Manager and Gateway treat a
persisted cleanup trigger as Release=committed. This proposal uses deployment ordering rather than
a feature gate or version handshake.
