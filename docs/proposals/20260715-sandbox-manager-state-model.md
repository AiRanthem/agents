---
title: Sandbox-manager State Model and Layering
authors:
  - "@AiRanthem"
reviewers: []
creation-date: 2026-07-15
last-updated: 2026-08-26
status: provisional
---

# Sandbox-manager State Model and Layering

## Summary

This proposal defines a backend-neutral structured State for sandbox-manager. It separates user
delivery, release, Pause/Resume transitions, and current workload capability so visibility,
routing, operation admission, and quota no longer interpret Sandbox CR Phases, Conditions,
annotations, or reasons independently.

State has four independent dimensions:

    State {
        Delivery    unclaimed | claimed | ready | reserved-failed
        Release     none | due | terminal | committed
        PauseResume none | pausing | resuming
        Workload    provisioning | ready | paused | unready | completed
    }

Claim and Clone use two-stage delivery. The first-stage Sandbox CR write records the owner, public
ID, claim lock, quota reservation reference, and fixed delivery deadline, producing a hidden and
non-routable `claimed` delivery.
Only after the current Pod's runtime, credentials, CSI, and TrafficPolicy serving facts are ready
does the final conditional write of the second stage commit `DeliveryReady=True` and produce
`ready`. That final write is the commit point for visibility, a running Route, and a successful
response.

The claim-lock UUID is the DeliveryEpoch, the identity of one delivery attempt. Traffic and every
operation that requires proven-safe state must match the current epoch. Missing or mismatched
facts are rejected. Before another claim is allowed, Recycle forms a complete isolation barrier so
resources, credentials, connections, and late operations from the old epoch cannot affect the
next owner.

The design assumes that healthy sandbox-manager and Gateway replicas share one authoritative
serving snapshot: the common Sandbox CR and Route view from which they answer requests and forward
traffic. A replica that is behind or has not completed its initial snapshot does not serve. This
proposal defines the target state and provides no degraded or mixed-version compatibility.

This proposal remains `provisional`.

## Background

Sandbox state affects pool candidate selection, completion of Create and Clone, Pause and Resume,
traffic forwarding, owner visibility, quota, and release. Flattening those questions into one
state conflates facts that are not interchangeable:

- the resource belongs to a user but delivery is incomplete;
- initial delivery completed but the workload is now pausing, resuming, or upgrading;
- the workload stopped but cleanup has not been committed;
- a deadline passed but the release mutation has not won its concurrent commit;
- release is irrevocably committed but the Recycle barrier is still converging.

The Sandbox CR remains the authoritative source of backend facts. State does not create a second
lifecycle store. It creates one interpretation boundary: a Sandbox CR mapper produces neutral
facts, Manager applies business policy, API performs authentication, authorization, and public
protocol mapping, and Route projects traffic state only.

Recycle retains the same Sandbox CR and UID while allowing the same object to be delivered to
different owners over time. A UID, name, or public ID therefore cannot identify one delivery by
itself. Without a delivery epoch and a complete isolation barrier, an old operation, credential, or
TrafficPolicy can cross the Recycle boundary and affect the next delivery.

### Goals

- Hide a Sandbox and reject traffic until its security delivery completes.
- Separate ownership, release, Pause/Resume, and workload capability.
- Keep Sandbox CR Phases, Conditions, annotations, and reasons out of Manager and API decisions.
- Use the same Sandbox CR mapper for Infra Observations and Route projection.
- After the first claim write, bind every delivery capability to an authorized DeliveryEpoch and
  backend object version.
- Prove that the current Pod matches its desired inputs with an effective workload digest.
- Reject traffic and operations that require safe state when the required facts are unknown,
  incomplete, or mismatched.
- Provide consistent visibility and Route serving snapshots across healthy replicas.

### Non-goals

- This proposal does not introduce SandboxRecord or another authoritative visibility store.
- It does not preserve visibility when the Sandbox CR is actually absent.
- It does not make `ShutdownTime` a strict wall-clock traffic cutoff or add a deadline to Route.
- It does not persist every delivery step or resume the same delivery execution after a process
  crash.
- It does not change the public E2B state set or established error categories.
- Except for storage facts explicitly named as part of a contract below, it does not specify
  concrete annotations, labels, RPCs, selectors, cache data structures, hash algorithms, or
  Recycle cleanup steps.
- It does not design legacy-object migration, mixed-version protocols, version negotiation, or
  degraded fallback.
- Other than delivery provenance and isolation, it does not change Checkpoint lifecycle or storage
  policy.

## Target Design

### 1. Boundaries and Preconditions

The dependency direction is fixed:

    Sandbox CR
        |
        | Sandbox CR mapper
        v
    neutral State + Observation
        |                              |
        | Infra capabilities           | Route projection
        v                              v
    Manager policy -> API       Manager/Gateway Route stores
                                         |
                                         v
                                Gateway traffic admission

The neutral State package defines State values, validation, and the MutationToken contract only. A
MutationToken is an opaque mutation credential returned by Infra; Manager must return it unchanged
and cannot parse it. The Sandbox CR-specific mapper interprets CR fields. Concrete Kubernetes
reads and writes remain in Sandbox CR Infra; Manager depends only on neutral Observations and
capabilities. Sandbox Controller is an independent operator and does not depend on Manager, API,
or a concrete Infra implementation.

The design depends on two target-state preconditions:

1. **Recycle isolation barrier.** Before old claim identity is cleared and the Sandbox re-enters the
   candidate pool, every old runtime, credential, long-lived connection, CSI state, Pod identity,
   TrafficPolicy match, Route, internal Checkpoint, and late writer that could affect the next
   delivery is ineffective. If completion cannot be proven, the Sandbox is deleted or isolated and
   cannot be claimed again. A standalone user Snapshot is not deleted, but it retains source-epoch
   provenance and is not active state for the next delivery.
2. **Consistent serving snapshot.** Every healthy Manager and Gateway serves from the same
   authoritative Sandbox CR snapshot and its Route projection. A replica that is behind,
   disconnected, restarting without a complete initial snapshot, or unable to reject an old peer
   event leaves readiness. The primary Lease selects a background cleanup worker only; it is not a
   single entry point for owner APIs.

The authoritative publisher exposes a monotonically advancing publication watermark. A ready
Kubernetes resourceVersion (RV) and its Route are common serving state once the watermark includes
them. A Manager or Gateway may report healthy only after it has caught up to that watermark;
joining and recovering replicas do not change what an already-started wait means because they
remain unready until caught up.

A consistent snapshot does not replace MutationToken or compare-and-swap (CAS). State may change
after a request reads the snapshot, so every mutation revalidates the object version and
DeliveryEpoch at the boundary where it takes effect. Local clocks can produce different `due`
Observations at the deadline boundary. Route ignores `due`, so this does not create Route
divergence.

### 2. State and Observation

| Dimension | Values | Question answered |
|---|---|---|
| Delivery | unclaimed / claimed / ready / reserved-failed | How far has this user delivery progressed? |
| Release | none / due / terminal / committed | Which release fact is currently observed? |
| PauseResume | none / pausing / resuming | Is an ordinary Pause or Resume in progress? |
| Workload | provisioning / ready / paused / unready / completed | Which workload capability is currently proven? |

Object absence is a `NotFound` result outside State. Absence is never represented as a State, and
an invalid State is never disguised as NotFound.

An Infra lookup returns one snapshot:

    Observation {
        State         State
        Owner         string
        MutationToken // opaque mutation credential
    }

MutationToken binds at least the Sandbox ObjectKey, UID, resourceVersion, claimed marker, owner,
public ID, current claim lock, quota reservation ID and generation, claim timestamp, and delivery
deadline.
Manager and API do not parse it.

#### Delivery

The mapper validates claim facts first, then derives Delivery in this order:

1. The claimed marker is absent or explicitly false, and owner, public ID, claim lock, quota
   reservation reference, and failure-retention facts are all absent: `unclaimed`. An old
   `DeliveryReady` or delivery deadline may remain, but has no effect without a current epoch.
2. The claimed marker is true, claim identity is complete, and failure-retention facts for the
   current epoch are complete: `reserved-failed`. A matching `DeliveryReady=True` for the same
   epoch makes the Observation invalid instead.
3. The claimed marker is true, claim identity is complete, and the current `DeliveryReady=True`
   Message parses and matches the current claim lock: `ready`.
4. The claimed marker is true, claim identity is complete, and no matching ready fact exists:
   `claimed`.
5. An unknown claimed-marker value, or any other missing, residual, malformed, or conflicting
   combination, makes the Observation invalid. Infra returns internal or unavailable, and Route
   rejects traffic.

`DeliveryReady` is a claim-scoped Condition:

- its `Type` is `DeliveryReady`;
- a successful commit uses `Status=True` and a stable completion reason;
- `Message` is JSON with separate `deliveryEpoch` and `diagnostic` fields;
- only `Status=True` with a `deliveryEpoch` equal to the current claim lock produces `ready`;
- a malformed, missing, or epoch-mismatched Condition grants neither traffic nor an operation that
  requires proven-safe state and remains hidden `claimed`;
- `ObservedGeneration` is not an epoch because claim metadata changes do not advance generation;
- the Condition may remain across Recycle; a new claim lock automatically invalidates the old
  Condition.

Sandbox CR Infra is the sole writer of `DeliveryReady`. Sandbox Controller does not set, clear, or
interpret it. Its informer may observe the update, but semantic filters on every Sandbox Controller
watch do not enqueue an update whose only meaningful change is `DeliveryReady`. A successful
second-stage commit therefore performs one Infra status write, causes no Sandbox Controller
reconcile, and causes no additional Controller-originated API-server write. Every status writer
uses an object-version precondition and preserves Conditions it does not own, so an in-flight old
writer cannot overwrite the new ready fact.

The four values mean:

| Delivery | Meaning | Visibility | Route |
|---|---|---|---|
| unclaimed | No user delivery | Hidden | available/creating/dead from pool workload |
| claimed | Identity committed; delivery in progress or outcome unknown | Hidden | dead |
| ready | Initial security delivery completed | Derived from Release | Derived from current capability |
| reserved-failed | Known failure retained by request policy for diagnosis | Hidden | dead |

`reserved-failed` exists only for `reserve-failed-sandbox-for`. Its persisted retention fact is
bound to the current epoch and contains either an absolute expiry or `forever`; marker, epoch, and
retention choice commit in one conditional write. Manager admits that write only from the current
`claimed` delivery when the matching quota generation is still binding or active. Infra then
requires matching RV and epoch, no matching `DeliveryReady=True`, and no committed cleanup. It
competes with ready and cleanup using the same CAS rule. If quota is already closed or cleanup
wins, retention cannot retry with a newer RV to rescue the delivery; if retention wins, ordinary
terminal cleanup honors its retention period. A known failure without retention commits cleanup
directly and never enters this value. Finite retention commits cleanup when it expires.
`forever` retains the Sandbox until administrator cleanup and continues charging quota. Retention
takes priority even if the workload becomes terminal; the ordinary terminal cleanup worker cannot
remove it early. A `reserved-failed` delivery can never become `ready` in the same epoch, so a retry
uses a new epoch. Final Recycle claim clearing also atomically clears the failure-retention fact.

`ready` proves initial delivery only, not perpetual workload service. Pause, Resume, upgrade, Pod
replacement, or failure changes PauseResume and Workload without regressing Delivery to claimed.

#### Release

The mapper derives Release by first match. A cleanup trigger is a persisted fact, bound to the
current DeliveryEpoch, that irrevocably commits release for that delivery:

1. DeletionTimestamp, a cleanup trigger for the current delivery, or Phase
   Recycling/Terminating: `committed`.
2. Phase Succeeded/Failed: `terminal`.
3. ShutdownTime exists and local `now` has passed it: `due`.
4. Otherwise: `none`.

`due` is an Observation-local, reversible deadline fact, not an irrevocable release commit. It
does not change owner visibility, public E2B state, quota, or Route. It does prevent a new claim and
admits only List, Describe, and Kill for owner APIs.

The write whose observed object version is still current wins a deadline race. A timeout update
and Controller cleanup both carry the resourceVersion and DeliveryEpoch they observed. If the
update commits first, stale cleanup conflicts; if cleanup commits first, the timeout update
conflicts. Time passing does not advance resourceVersion, so this proposal neither promises a
strict wall-clock cutoff nor promises that authorization obtained before the deadline can never
win CAS after the deadline.

`terminal` means the workload stopped but cleanup is not committed. It hides the Sandbox, rejects
traffic, and retains quota. Except for a `reserved-failed` delivery whose retention is still
active, the background cleanup worker eventually commits cleanup for the current epoch.

`committed` is monotonic within one delivery. Once the cleanup trigger persists, owner APIs hide
the Sandbox, Route is dead, and quota may be released asynchronously. The Recycle barrier governs
final claim clearing, pool re-entry, and a later claim. Barrier failure cannot restore the same
delivery to service.

#### PauseResume

PauseResume uses typed desired and observed pause facts, not whole-object generation:

1. Delivery is unclaimed, Release is terminal/committed, or Phase is
   Succeeded/Failed/Upgrading: `none`.
2. Resume is active, paused was observed while desired is running, or runtime re-initialization is
   incomplete: `resuming`.
3. Desired is paused but completion is not observed: `pausing`.
4. Otherwise: `none`.

An internal wake-up during Controller upgrade is not an ordinary Resume. A timeout-only spec update
cannot erase an active Pause or Resume.

#### Workload and Effective Revision

Workload freshness uses a content digest of the effective workload, not a hash of the
`templateRef` name alone. The digest covers:

- the resolved PodTemplate;
- VolumeClaimTemplates and PersistentContents;
- Runtimes and every other Sandbox-declared input that changes actual Pod/runtime serving
  capability.

Pure policy fields such as ShutdownTime and PauseTime are excluded. Global injection ConfigMaps,
feature gates, and other mutable external configuration may be excluded only when they are proven
not to change security or serving behavior. Every other such input has a persisted revision and is
included in the digest or in a separate serving-readiness check.

The authoritative desired digest becomes stale atomically with the desired inputs; it cannot rely
only on the last status value written asynchronously by Controller. An inline input change binds a
new digest to that Sandbox desired version. A `templateRef` either names an immutable,
content-addressed template revision, or its resolved revision is part of the Sandbox's
authoritative desired input. A model in which referenced content changes without changing the
Sandbox serving snapshot cannot produce `ready`.

After Controller observes that authoritative desired version, it writes the same digest to
`status.updateRevision` and copies the actual Pod `pod-template-hash` to
`status.podInfo.labels["pod-template-hash"]`. Sandbox, SandboxSet, and Controller use one digest
definition that excludes business-policy fields. The mapper does not read a mutable templateRef.
It requires the authoritative desired digest, the Controller-observed digest, and the Pod-applied
digest to match, and requires the observed desired version to identify the current Sandbox desired
version.

For a claimed Sandbox, the Sandbox CR also persists serving-readiness facts for the current Pod.
Those facts bind DeliveryEpoch, `status.podInfo.podUID`, and the applied digest, and separately
prove runtime initialization, delivery credential activation, CSI initialization when configured,
and TrafficPolicy data-plane protection for that Pod. A binding mismatch invalidates old facts.
Pod replacement, Resume, or upgrade establishes them again for the current Pod instead of relying
on the initial `DeliveryReady` fact.

Workload is derived by first match:

1. Phase Succeeded/Failed: `completed`.
2. Phase Paused with paused fact=True: `paused`.
3. Phase Running; all three digests match; Ready=True; PodUID and PodIP are non-empty; and the
   InplaceUpdate fact explicitly says that no update is active for the current Pod and digest, or
   that such an update succeeded: the base workload is ready. For Delivery=unclaimed this produces
   `ready`. For a claimed delivery, matching serving-readiness facts for the current epoch and Pod
   are also required before it produces `ready`.
4. Phase Pending, all three digests match, and `status.podInfo.podUID` identifies the current Pod:
   `provisioning`.
5. Otherwise: `unready`.

Ready missing, False, or Unknown; a missing or mismatched digest or desired version; missing PodUID
or PodIP; an InplaceUpdate fact that is absent, belongs to another Pod/digest, or reports failure;
incomplete serving-readiness facts for a claimed Sandbox; an unknown Phase; or any other incomplete
status cannot produce `ready`. CreationTimestamp is only a speculation-age threshold after
`provisioning` is already proven; age does not prove progress.

#### Validity Invariants

Mapper output satisfies:

- `claimed`, `ready`, and `reserved-failed` all have complete owner, public ID, epoch, and
  MutationToken, plus a valid claim timestamp, fixed delivery deadline, and quota reservation ID
  and generation bound to that epoch;
- `unclaimed` has no owner, public ID, claim lock, quota reservation reference, or
  failure-retention fact;
- `reserved-failed` cannot coexist with matching-epoch `DeliveryReady=True`;
- PauseResume is none for `Delivery=unclaimed` and Release terminal/committed;
- `Release=terminal` has `Workload=completed`;
- `Release=committed` may preserve any conservative workload snapshot but has
  `PauseResume=none`;
- Workload completed coexists only with Release terminal or committed;
- non-none PauseResume does not coexist with Workload provisioning or completed;
- Delivery ready may coexist with Workload paused, unready, or completed because delivery
  completion and current capability are different facts.

An unknown enum or a combination that cannot be normalized fails State validation. Infra returns
internal or unavailable, and Route is dead.

### 3. DeliveryEpoch and Backend Isolation Checks

The claim lock on the current claimed Sandbox CR is the authoritative DeliveryEpoch. It never
rotates within one delivery. Successful Recycle clears it when claim identity is finally cleared,
and that final transition also clears the quota reservation reference and failure-retention fact.
The next claim creates a new epoch. The epoch rules below apply to delivery operations and
results after the first claim write. An unclaimed pool object has no DeliveryEpoch. It can produce
only a non-forwarding `available` or `creating` Route, whose events are ordered by ObjectKey, UID,
and resourceVersion.

Every backend boundary follows the same protocol:

| Stage | Contract |
|---|---|
| Install | Persist and verify the new epoch identity and isolation data; failed installation remains unavailable |
| Activate | After runtime, credential, CSI, and TrafficPolicy serving facts hold for the current Pod, CAS DeliveryReady with current epoch and RV |
| Use | Requests, credentials, resources, and results match current epoch; reject missing or mismatched facts |
| Revoke | Cleanup stops traffic and operations that require proven-safe state; claim clears only after Recycle proves the old epoch ineffective |
| Restart | Recover from persisted authoritative snapshot; inability to recover current epoch remains unavailable |

The boundaries include:

- **Sandbox CR mutation:** validate ObjectKey, UID, RV, owner, public ID, claimed marker, and epoch.
  A conflict cannot transparently retry the original operation against a new delivery.
- **Runtime and credentials:** runtime installs current epoch and accepts only matching
  initialization, Browser credentials, and workload requests. Old credentials, long-lived
  connections, and late completions become ineffective within the Recycle barrier.
- **Gateway requests:** a public ID is an address, not an authorization credential. All traffic to
  a recyclable Sandbox carries a credential bound to the current epoch. Gateway verifies both the
  Route epoch and credential epoch before forwarding. Unauthenticated traffic cannot use the
  recyclable delivery path defined here.
- **Pod and TrafficPolicy:** both carry the same epoch. Policy CRUD matches public ID and epoch.
  Selector mismatch, missing Pod epoch, or missing policy makes the data plane deny by default.
- **Route:** a claimed Route carries ObjectKey, UID, RV, public ID, and epoch. Authoritative snapshot outranks peer
  deltas, and a non-current epoch event cannot update or delete a Route. An unclaimed event has no
  epoch and can update only the pool Route for the same ObjectKey and UID; it cannot overwrite a
  claimed public ID. Multiple objects claiming the same active public ID reject traffic as a
  whole; the last event cannot take ownership.
- **Connect:** after Resume, obtain a new Observation and connect only if epoch is unchanged and
  the new State still admits the operation.

Checkpoint distinguishes two epochs:

- source DeliveryEpoch proves which source delivery produced the Snapshot/Checkpoint; the producer
  validates it before starting and before completing;
- Clone validates source provenance and owner but creates a new target DeliveryEpoch for the target
  Sandbox;
- source epoch is not compared for equality with target epoch; target Pod, runtime, Route, and
  TrafficPolicy use only target epoch;
- the Recycle barrier isolates delivery-scoped internal Checkpoints, while a standalone Snapshot
  may outlive the source Sandbox.

### 4. Claim and Clone

A candidate satisfies:

| Candidate | Required facts |
|---|---|
| Normal | Delivery=unclaimed, Release=none, PauseResume=none, Workload=ready, target pool, unlocked |
| Speculative | Delivery=unclaimed, Release=none, PauseResume=none, Workload=provisioning, target pool, unlocked, speculation age elapsed |
| Ineligible | Any other Delivery; Release due/terminal/committed; paused/unready/completed; wrong pool; or locked |

Claim and Clone run in this order:

1. Manager validates the request and creates a persisted quota reservation with a fixed expiry,
   reservation ID, and generation. The pair of reservation ID and generation is the quota
   reservation generation. Closing it permanently invalidates that generation. It is distinct
   from DeliveryEpoch, MutationToken, and a traffic access token. Claim binding and expiry
   reclamation use CAS on the quota record, so exactly one can move it out of reserved state.
2. The winning claim binding moves the reservation generation into a quota-counting binding state.
   Infra's first claim write stores owner, public ID, claim lock, claimed marker,
   claim timestamp, reservation ID and generation, and a fixed absolute delivery deadline selected
   by the service. A write that races after the generation was closed is a stale orphan write: it
   stays hidden, can never pass ready admission, and is cleaned up. It cannot reactivate or reuse
   the closed quota generation.
3. Manager waits until the current Pod, PodUID, desired digest, applied digest, and Ready condition
   satisfy the base-workload prerequisites. It then installs runtime, credentials, CSI when
   configured, and TrafficPolicy for the current epoch, and persists serving-readiness facts bound
   to that epoch, PodUID, and digest.
4. Manager obtains a new Observation. It conditionally commits `DeliveryReady=True` with that
   Observation's RV only if Delivery=claimed, Release=none, Workload=ready, owner, public ID, and
   epoch still match; the matching quota allocation is active; and no cleanup or failure-retention
   fact exists. After a CAS conflict it must satisfy the complete predicate again; it cannot merely
   retry with a newer RV.
5. Create or Clone returns success only after the authoritative Route publication watermark
   includes the ready RV and its running Route. Every Manager and Gateway that reports healthy has
   caught up to that watermark; joining or recovering replicas remain unready until they do.

The delivery deadline is a fixed, server-selected abandonment-cleanup time. It is not user workload
ShutdownTime and is not renewed by a request heartbeat. It lets the background cleanup worker find
a claimed delivery that nobody is advancing, but it is not a strict activation cutoff. Expiry does
not advance resourceVersion; before cleanup commits, a ready write that still satisfies the full
predicate in step 4 may win CAS. The deadline may remain on the object and be ignored after ready,
avoiding a third cleanup write.

The Manager primary finds expired claimed deliveries from the authoritative snapshot. Its
background cleanup worker and the ready commit compete with the same RV and epoch: if ready commits
first, cleanup does not proceed; if the cleanup trigger commits first, the ready commit conflicts
and cannot rescue the delivery. Sandbox Controller executes committed cleanup only and does not
interpret the delivery deadline or DeliveryReady.

Failures behave as follows:

| Scenario | Result |
|---|---|
| Process crashes before quota binding | Expiry reclamation closes the reserved generation and releases quota |
| Process crashes after quota binding but before claim | Resolver closes the binding generation after its deadline; a late CR write stays hidden and is cleaned up |
| Quota reserved, claim commit definitely failed | Close the generation and release quota after authoritative confirmation that the epoch did not persist |
| Claim commit outcome unknown | Let the quota convergence worker inspect the quota reservation record and Sandbox CR; never guess and release quota |
| Known pre-ready failure without retention | Commit cleanup for the same epoch; retry with a new epoch |
| Known pre-ready failure with retention | CAS the epoch-bound marker and absolute expiry/forever fact; finite retention cleans up on expiry, forever requires administrator cleanup |
| Request cancellation | Use bounded cleanup detached from request cancellation; the background cleanup worker covers an uncertain outcome |
| Manager crashes before ready | Keep the claimed Sandbox hidden and retain quota; the background cleanup worker acts after the fixed deadline |
| Ready commit succeeds but Route publication or response fails | Do not roll back; return unavailable, and List/Describe can discover the ready Sandbox |

This proposal does not resume partial delivery in the same epoch. A retry after a crash or final
failure uses a new Sandbox delivery and epoch.

A traffic access token may exist only in the transient Create/Clone response. If ready commits but
Route publication times out, the workload loses ready while waiting, or the response is lost, the
token is not guaranteed recoverable and the committed delivery is not rolled back. The owner can
find the Sandbox through List/Describe, then Kill it and create another one. This proposal neither
persists the token nor adds an idempotent response store or token reissuance API.

### 5. Owner Visibility and Public API

Manager derives caller-independent visibility:

    ResourceVisible =
        Sandbox exists
        && Delivery == ready
        && Release in {none, due}

API then performs owner authorization:

    OwnerVisible = ResourceVisible && Observation.Owner == authenticated caller

List filters owner and OwnerVisible before pagination. Describe and every single-Sandbox API use
the same Observation. Route is not authoritative for existence or owner authorization. A
single-Sandbox API checks owner first and then applies State rows from top to bottom, so an owner
mismatch never reaches a later release row.

| Case | Non-Kill owner API | Kill |
|---|---|---|
| NotFound / unclaimed | HTTP 404 | HTTP 204, no-op |
| claimed / reserved-failed | HTTP 404 | HTTP 204, no-op |
| ready with owner mismatch | HTTP 404 | HTTP 204, no-op |
| ready + Release=none/due | Apply State admission | Commit release for current epoch |
| ready + Release=terminal | HTTP 404 | Commit cleanup for current epoch |
| Release=committed | HTTP 404 | HTTP 204 |
| Invalid Observation or backend unavailable | Map to internal/unavailable | Do not report a resource mutation that was not proven |

`reserved-failed=forever` exists for administrator diagnosis only. Owner APIs neither expose it nor
attach a cleanup side effect.

The public E2B state set remains minimal:

| OwnerVisible State | E2B state |
|---|---|
| PauseResume=none and Workload=ready | running |
| Otherwise | paused |

Therefore `Delivery=ready, Release=due, Workload=ready` remains publicly `running`, but does not
mean Connect is currently admitted. Only List, Describe, and Kill are admitted while due.

### 6. Operation Admission

An operation that uses the workload first requires OwnerVisible, a valid MutationToken, and a
current epoch match.
Release=due is an independent rejection condition.

| PauseResume and Workload | Pause | Resume | Connect |
|---|---|---|---|
| none + ready | Start Pause | No-op success | Connect |
| none + paused | No-op success | Start Resume | Re-observe and connect after Resume |
| pausing + any valid Workload | Join and wait | HTTP 409 | HTTP 400 |
| resuming + any valid Workload | HTTP 409 | Join and wait | Wait, re-observe, then connect |
| none + provisioning/unready | HTTP 409 | HTTP 409 | HTTP 500 |

Snapshot, Set timeout, Update network, and Browser operations require PauseResume=none and
Workload=ready.
When they are not admitted, established public error categories remain: HTTP 400 for Snapshot and
HTTP 500 for the other three, with no partial mutation.

Same-direction Pause/Resume joins the active operation; the opposite direction conflicts. After a
MutationToken conflict, Manager obtains a new Observation and repeats State admission and owner
authorization. It never retries old authorization against a new delivery.

### 7. Route

Route uses the same Sandbox CR mapper as Infra and carries ObjectKey, UID, resourceVersion, and
PodIP. A claimed Route also carries public ID and DeliveryEpoch. An unclaimed pool Route has
neither; it uses an internal pool key and cannot be addressed publicly through Gateway. Route does
not carry complete State or a deadline.

A delete event or reliable tombstone deletes Route. Other objects project by first match:

| State and Route facts | Route.State |
|---|---|
| Invalid State | dead |
| Release=terminal or committed | dead |
| Workload=completed | dead |
| Delivery=claimed/reserved-failed | dead |
| Delivery=ready, PauseResume=none, Workload=ready, IP exists | running |
| Delivery=ready, PauseResume=pausing or resuming | paused |
| Delivery=ready, PauseResume=none, Workload=paused | paused |
| Delivery=ready, Workload=provisioning | creating |
| Delivery=ready and Workload=unready | dead |
| Delivery=unclaimed, Workload=ready, IP exists | available |
| Delivery=unclaimed, Workload=provisioning | creating |
| Otherwise | dead |

The projection is identical for Release=none and due; due never changes an existing Route.
`unclaimed+due` is not a claim candidate but keeps the same Route projection. Route `available`
is not authoritative candidate eligibility or existence.

Gateway forwards only `running`. The ready commit must enter the authoritative Route publication
watermark before Create/Clone returns. Gateway forwards no traffic before completing its initial
snapshot after restart, and a peer event cannot overwrite a newer authoritative epoch/RV.

### 8. Quota and Background Convergence

Quota is not a State dimension. Its reservation record is the authority for reserved, binding,
active, and released quota. Claim binding and expiry reclamation CAS the same quota reservation
generation. The first claim write persists the reservation ID and generation with DeliveryEpoch.
A quota convergence worker that finds binding without a known write outcome activates it when the
matching claim exists, or closes the generation and releases it after the binding deadline when no
claim exists. A late CR write from a closed generation cannot reactivate quota or pass the ready
predicate; it remains hidden and is submitted for cleanup. This generation protocol prevents both
an orphan reservation and a visible delivery without quota without moving quota policy into Infra.
Once a matching claim exists, its binding or active generation does not expire independently. It
can close only after a persisted fact changes the Sandbox CR to `Release=committed`, so a
concurrent ready or retention CAS sees an RV conflict.

Quota uses the following priority from top to bottom:

| Condition | Quota |
|---|---|
| A claim-bound current epoch has Release=committed | May release asynchronously, regardless of Delivery |
| No matching claim exists, and (reservation is reserved before expiry or binding is before its binding deadline) | Retain |
| No matching claim exists and reservation remains reserved at expiry and reclaim wins CAS | Close its generation and release quota |
| Binding reaches its deadline | Resolve against the Sandbox CR: activate and retain a matching claim, otherwise close and release; a late CR write cannot become ready or reserved-failed |
| A current-epoch allocation or claim-bound reservation exists, and (Delivery=claimed/ready/reserved-failed or Release=due/terminal) | Retain |
| NotFound with no open reserved, binding, or active generation | Reconcile to released |

For a claim-bound current-epoch allocation, any persisted fact that maps Release to `committed`
permits quota release; a cleanup trigger is one such fact. An unbound reservation instead releases
when its expiry CAS closes the reservation generation. A quota backend update may fail and be
repaired by quota reconciliation. If the first claim write has an unknown outcome, the quota
convergence worker checks the quota reservation record and Sandbox CR before activating or closing
the generation; request failure alone never releases it. Finite reserved-failed explicitly extends
quota use. Forever retention explicitly consumes quota until administrator cleanup.

### 9. Layer Responsibilities

| Layer | Owns | Does not own |
|---|---|---|
| API | Authentication, owner authorization, protocol validation, HTTP/E2B mapping | CR status interpretation, Route existence, lifecycle policy |
| Manager | Visibility, candidates, quota, background cleanup, lifecycle and capability admission, orchestration after conflict | CR Phase/Condition/annotation, HTTP semantics |
| Infra | Observation, CR mapping, conditional backend capabilities, waiting, CAS, epoch isolation checks | Caller authentication, HTTP status, quota policy |
| Controller | Native CR/workload coordination, execution of cleanup and Recycle barrier | Manager/API policy, interpreting DeliveryReady, dependency on Manager/Infra implementation |
| Route/Gateway | Shared projection, authoritative snapshot, running traffic admission | Sandbox existence, owner authorization, Manager State |

## Implementation Notes

The safety semantics in this design may be enabled only after all of these prerequisites hold:

- Current Recycle cannot prove removal of every old delivery effect and may reject some Sandboxes.
  It does not yet satisfy the complete isolation barrier. Enablement requires deletion or
  isolation when the barrier cannot be proven, instead of returning the Sandbox to the pool.
- Current Manager and Gateway use process-local informer/Route caches and cannot guarantee one
  serving snapshot across every healthy replica. Enablement requires a common authoritative
  publication watermark and removal of a lagging replica from readiness.
- Current Sandbox Controller observes ordinary Sandbox status updates, and status writers do not
  guarantee optimistic CAS across multiple writers. Enablement requires DeliveryReady-only zero
  enqueue and preservation of Conditions owned by other writers.
- Current ShutdownTime cleanup does not validate RV and epoch together. Enablement requires every
  deadline mutation and cleanup write to follow the object-version winner contract in this design.
- Current quota reservation and claim do not share the reservation-generation protocol in this
  design. Enablement requires quota binding/reclamation CAS, closed-generation rejection, and an
  active matching quota allocation before ready or retained-failure commit.

New Manager, Gateway, Controller, quota backend, runtime, and TrafficPolicy/Pod data plane
semantics must not be enabled before these prerequisites hold. A claimed delivery with a missing
epoch, DeliveryReady,
required workload digest or desired version, or serving-readiness fact rejects traffic and
relevant operations, and never falls back to name, UID, public ID, or ownerReference. This proposal
does not support mixed-version operation or define legacy backfill or rollout migration steps.
