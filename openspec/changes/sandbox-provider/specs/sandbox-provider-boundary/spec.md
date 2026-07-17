## ADDED Requirements

### Requirement: Shared Sandbox contracts have a neutral owner
The system SHALL place cross-provider Sandbox capabilities, manager-oriented observation types,
common claim inputs and results, explicit defaults, admission callbacks, resource/update intent,
and claim metrics in `pkg/sandboxprovider`. Production code in this package MUST NOT import
controller, sandbox-manager, servers, or Sandbox CR implementation packages.

#### Scenario: Manager consumes a neutral Sandbox
- **WHEN** sandbox-manager business logic receives a Sandbox from its infra port
- **THEN** it uses provider-owned capabilities without receiving an `agentsv1alpha1.Sandbox`, client,
  cache, or CR-specific option

#### Scenario: Future provider implements the contract
- **WHEN** a non-CR Sandbox implementation is added
- **THEN** it can implement the provider contract without importing `pkg/sandboxprovider/sandboxcr`

### Requirement: Sandbox CR algorithms have one shared implementation
`pkg/sandboxprovider/sandboxcr` SHALL own Sandbox CR observation, pure pool predicates, SandboxSet
materialization, CR-specific claim options, a narrow claim backend contract, and shared claim
orchestration. Its production dependency closure MUST NOT include `pkg/controller`,
`pkg/sandbox-manager`, `pkg/servers`, concrete Kubernetes clients, or the concrete cache package.

#### Scenario: Controller reuses a CR mechanic
- **WHEN** Controller needs pool classification, SandboxSet materialization, or claim execution
- **THEN** it calls the shared CR provider without importing sandbox-manager

#### Scenario: Shared package needs SandboxSet construction
- **WHEN** claim creates a Sandbox from a SandboxSet
- **THEN** it uses provider-owned materialization rather than importing the SandboxSet controller

#### Scenario: Shared claim needs Kubernetes I/O
- **WHEN** TryClaimSandbox needs a pool read, CR write, wait, runtime call, identity operation, or
  cleanup persistence
- **THEN** it invokes the narrow backend supplied by the component adapter without obtaining a
  concrete client or cache

#### Scenario: Shared package records CSI claim metadata
- **WHEN** claim persists the CSI mount configuration required by the CR lifecycle
- **THEN** it uses a CR-owned annotation key rather than importing an E2B model

### Requirement: Read-only observation is separated from mutation
The CR provider SHALL expose a read-only Sandbox view backed only by a Sandbox CR. The view SHALL
provide metadata, `GetState`, and `GetRoute` and SHALL NOT provide cache, client, pause, resume,
delete, timeout, checkpoint, runtime, CSI, or other mutation capabilities.

#### Scenario: Gateway observes a Sandbox
- **WHEN** Gateway receives a Sandbox from its informer
- **THEN** it constructs the read-only view without supplying a cache or client

#### Scenario: Gateway attempts mutation
- **WHEN** code using the Gateway view is compiled
- **THEN** no mutating Sandbox method is available through that view

#### Scenario: Manager needs mutation
- **WHEN** the Manager CR adapter constructs a mutable Sandbox
- **THEN** it remains in Manager infra/sandboxcr, delegates observation to the read-only view, and
  owns its concrete client/cache dependencies

### Requirement: State and route are accessed only through methods
Raw CR-to-state derivation SHALL remain unexported inside sandboxcr. Consumers requiring the
manager-oriented observation SHALL call `GetState`. `GetRoute` SHALL call `GetState` and SHALL be
the only CR-to-route path used by Manager and Gateway. No exported free CR-to-state or CR-to-route
function SHALL remain.

#### Scenario: Manager evaluates lifecycle policy
- **WHEN** Manager needs a Sandbox state
- **THEN** it calls `GetState` rather than inspecting phase, conditions, cleanup metadata, or a free
  helper

#### Scenario: Gateway produces a route
- **WHEN** Gateway observes a Sandbox CR
- **THEN** it calls `GetRoute` and does not inspect raw lifecycle or serviceability facts

#### Scenario: Foundation behavior is observed
- **WHEN** callers migrate before the dependent state-model change
- **THEN** `GetState` preserves the existing lifecycle values while `GetRoute` preserves the legacy
  wire shape and applies the approved conservative route-safety baseline

### Requirement: Controller uses pool predicates instead of manager state
Controller, SandboxSet, and cache MUST NOT consume the manager-oriented `GetState` observation.
Pool creating and available/claimable facts SHALL be explicit-time pure predicates in sandboxcr and
SHALL preserve existing pool behavior.

#### Scenario: Pool member is classified
- **WHEN** SandboxSet or cache evaluates a member
- **THEN** it uses the provider pool predicates without comparing manager states

#### Scenario: Manager derives claimable later
- **WHEN** the dependent state-model derives its `claimable` observation
- **THEN** its sandboxcr implementation may reuse the same pool available predicate internally

#### Scenario: Controller remains self-contained
- **WHEN** the controller production import closure is inspected after migration
- **THEN** it contains no `pkg/sandbox-manager` or `pkg/servers` package

#### Scenario: E2B remains above Manager
- **WHEN** E2B needs Sandbox behavior after provider extraction
- **THEN** it calls the Manager interface and does not import sandboxprovider or Manager infra

### Requirement: Manager infra remains the concrete adapter boundary
`pkg/sandbox-manager/infra` SHALL remain the Manager infrastructure port, and
`pkg/sandbox-manager/infra/sandboxcr` SHALL retain Manager-specific assembly, lifecycle mutation,
clone, checkpoint, volume, quota-source, error mapping, Kubernetes clients, informer cache,
API-reader access, CR queries, and persisted mutations. It SHALL implement the shared claim backend
and delegate reusable observation and orchestration rather than duplicating them.

#### Scenario: Manager constructs CR infrastructure
- **WHEN** sandbox-manager starts its Kubernetes infrastructure
- **THEN** its existing infra/sandboxcr builder adapts the shared provider behind the Manager port

#### Scenario: Shared logic changes
- **WHEN** CR observation or claim mechanics are updated
- **THEN** Manager and controller use the one provider implementation rather than independent copies

#### Scenario: Manager claim performs a CR write
- **WHEN** shared claim orchestration requests create, update, refresh, or delete on the Manager path
- **THEN** the operation is implemented inside `pkg/sandbox-manager/infra/sandboxcr`

### Requirement: Legacy routing establishes a safe mixed-version baseline
Manager/proxy and Gateway route stores SHALL retain a deletion decision tombstone containing route
identity, Sandbox UID, and resource version after removing an active route. The tombstone SHALL
reject updates for the same UID with an equal or older resource version, SHALL NOT appear in active
Route List or data-plane lookup, and MAY be replaced by a strictly newer resource version for the
same UID or by a different UID for a reused route ID.

Each receiver SHALL maintain an authoritative local Sandbox observation and SHALL remain non-ready
for peer route mutation and data-plane forwarding until its informer/cache has synchronized. On
startup it SHALL rebuild current decisions through GetRoute. A peer update SHALL be accepted only
when route identity, UID, and resource version are consistent with the current local observation and
the update does not weaken the locally derived same-version decision. A stronger same-version peer
decision MAY apply. Ahead-of-cache updates SHALL be deferred or rejected until convergence, and
absent, stale, or superseded updates SHALL be rejected.

A tombstone MAY be garbage-collected after the synchronized local observation proves its UID absent,
a new UID owns the route ID, or a strictly newer active Allow/Deny record for the same UID has been
installed. A newer Delete SHALL replace the older tombstone. The authoritative acceptance gate or
newer active record SHALL continue to reject delayed records for the collected decision, so restart
and collection MUST NOT reopen stale forwarding.

The shared legacy GetRoute SHALL emit `running` only when the observation satisfies every safety
fact required by the dependent state-model Allow action. It SHALL emit a non-running legacy value
for incomplete post-resume initialization, unsafe in-place update, cleanup request, reserved
failure, missing Pod IP, and every other observation that the dependent change will Deny or Delete.
It SHALL NOT add Action or change the legacy Route wire shape.

#### Scenario: Same-version route arrives after delete
- **WHEN** an active route is deleted and a route for the same UID and resource version arrives later
- **THEN** the update is rejected and the route remains absent from forwarding

#### Scenario: Older route arrives after delete
- **WHEN** a route for the same UID with an older resource version arrives after delete
- **THEN** the tombstone rejects it

#### Scenario: Newer route arrives after delete
- **WHEN** a route for the same UID with a strictly newer resource version arrives
- **THEN** it may replace the tombstone under existing validation rules

#### Scenario: Route ID is reused
- **WHEN** a new Sandbox with a different UID uses the same route ID
- **THEN** the old tombstone does not block the new Sandbox

#### Scenario: Tombstone is queried
- **WHEN** active routes are listed or resolved by the data plane
- **THEN** the tombstone is not returned and cannot forward traffic

#### Scenario: Receiver restarts
- **WHEN** a Manager/proxy or Gateway receiver restarts and its in-memory tombstones are empty
- **THEN** it does not accept peer routes or forward traffic until local Sandbox cache sync and
  GetRoute rebuilding complete

#### Scenario: Delayed route follows restart
- **WHEN** a delayed peer route names a UID that the synchronized local observation does not contain
- **THEN** the receiver rejects it even though no tombstone survived the restart

#### Scenario: Peer is ahead of local cache
- **WHEN** a peer route has a resource version newer than the receiver's local Sandbox observation
- **THEN** the receiver defers or rejects it without enabling forwarding until local observation
  converges

#### Scenario: Peer weakens the local decision
- **WHEN** a peer Allow has the same UID and resource version as a locally derived Deny or Delete
- **THEN** the receiver rejects it even if no older process tombstone exists

#### Scenario: Tombstone is collected
- **WHEN** synchronized local observation proves the UID absent, a new UID owns the route ID, or a
  newer active Allow/Deny record for the same UID is installed
- **THEN** the receiver may remove its tombstone while continuing to reject delayed records for that
  old decision through authoritative validation or the newer active record

#### Scenario: Delete advances resource version
- **WHEN** the same UID produces Delete at a strictly newer resource version
- **THEN** the receiver replaces the older tombstone with the newer tombstone rather than collecting
  deletion freshness

#### Scenario: Legacy producer observes a future Deny fact
- **WHEN** resume initialization is incomplete, an in-place update is unsafe, cleanup is requested,
  or another later Deny gate applies
- **THEN** GetRoute emits a non-running legacy state

#### Scenario: Legacy producer observes a future Delete fact
- **WHEN** deletion, expired shutdown, reserved failure, or completion applies
- **THEN** GetRoute does not emit legacy `running`

#### Scenario: Baseline is deployed
- **WHEN** the dependent state-model starts Action production
- **THEN** every supported Manager, proxy, and Gateway route producer and receiver already runs the
  tombstone and conservative legacy-running baseline

### Requirement: Provider extraction preserves external behavior except route safety
The provider change SHALL NOT alter public APIs, CRD schemas, generated clients, Route wire shape,
claim results, lifecycle values, default values, retries, timeouts, quota policy, metrics semantics,
or E2B responses. It SHALL intentionally reject same-or-older same-UID route resurrection after
deletion and SHALL replace known unsafe legacy `running` decisions with non-running decisions.

#### Scenario: Existing behavior is compared
- **WHEN** focused tests run before and after the extraction with the same inputs
- **THEN** externally observable outputs, writes, errors, retries, and metrics are equivalent except
  for the specified route-safety hardening

#### Scenario: State-model change begins
- **WHEN** `sandbox-manager-state-model` changes state and Route semantics
- **THEN** every supported route producer and receiver already runs the complete provider route-
  safety prerequisite
