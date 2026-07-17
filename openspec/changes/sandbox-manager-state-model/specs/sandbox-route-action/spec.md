## ADDED Requirements

### Requirement: Core Route uses an explicit action
Core Route SHALL contain a typed Action with exactly `allow`, `deny`, or `delete` and SHALL NOT
contain lifecycle state. Route identity, IP, owner, UID, resource version, access token, freshness,
and redaction behavior SHALL remain unchanged.

#### Scenario: Valid active route is represented
- **WHEN** the provider produces an Allow or Deny route
- **THEN** core Route contains metadata and Action without lifecycle state

#### Scenario: Missing action is invalid
- **WHEN** compatibility decoding produces no valid Action
- **THEN** route mutation is rejected and forwarding is not enabled

#### Scenario: Unknown action is invalid
- **WHEN** a route contains an action other than allow, deny, or delete
- **THEN** route mutation is rejected and existing route state is not replaced

### Requirement: Shared CR GetRoute is the only state-to-action policy
`pkg/sandboxprovider/sandboxcr` GetRoute SHALL call GetState exactly once and SHALL map `running` to
Allow; `claimable`, `pausing`, `paused`, `resuming`, and `unready` to Deny; and `terminating` and
`completed` to Delete. Manager, proxy, and Gateway MUST NOT implement another raw CR or state-to-
action mapping.

#### Scenario: Healthy running Sandbox forwards
- **WHEN** GetState returns `running`
- **THEN** GetRoute returns Allow

#### Scenario: Live non-serving Sandbox is retained
- **WHEN** GetState returns `claimable`, `pausing`, `paused`, `resuming`, or `unready`
- **THEN** GetRoute returns Deny

#### Scenario: Removal or completion deletes
- **WHEN** GetState returns `terminating` or `completed`
- **THEN** GetRoute returns Delete

#### Scenario: Route uses one observation
- **WHEN** GetRoute evaluates a Sandbox
- **THEN** metadata and Action are produced from one GetState call without independently re-reading
  lifecycle facts for action selection

### Requirement: New Manager and Gateway use the same GetRoute
Manager route reconciliation and Gateway informer reconciliation SHALL construct provider-backed
Sandboxes and call the same sandboxcr GetRoute method. Gateway SHALL NOT inspect phase, Ready, Pod
IP serviceability, paused flags, RuntimeInitialized, InplaceUpdate, cleanup, reserved-failed,
shutdown, or completion facts to choose an action.

#### Scenario: Same CR and time reach both components
- **WHEN** new Manager and Gateway evaluate the same Sandbox CR snapshot at the same observation time
- **THEN** they produce identical Route metadata and Action

#### Scenario: Resume initialization is incomplete
- **WHEN** phase is Running, Resumed is true, and RuntimeInitialized exists and is not true
- **THEN** both Manager and Gateway obtain Deny from GetRoute

#### Scenario: In-place update is active
- **WHEN** phase is Running and InplaceUpdate reason is InplaceUpdating or Failed
- **THEN** both Manager and Gateway obtain Deny from GetRoute

#### Scenario: Unknown phase is observed
- **WHEN** no higher rule applies and phase is empty or unsupported
- **THEN** both Manager and Gateway obtain Deny from GetRoute

#### Scenario: Shutdown boundary is crossed
- **WHEN** observation time changes from equal to shutdown time to strictly after shutdown time
- **THEN** both components use the same strict-after rule and the route changes according to the
  provider observation

### Requirement: Route storage and forwarding obey Action
Allow and Deny SHALL be eligible for resource-version-aware route storage. Only Allow SHALL forward
data-plane requests. Delete SHALL remove the active route and SHALL retain only a non-forwarding
decision tombstone containing route identity, UID, resource version, and action rank. Delete MUST
NOT be returned by active-route List or data-plane lookup.

#### Scenario: Allowed route forwards
- **WHEN** a current Allow route is resolved by the data plane
- **THEN** forwarding uses its existing IP and access-token behavior

#### Scenario: Denied route remains visible but does not forward
- **WHEN** a newer Deny route is applied
- **THEN** the active record is updated but data-plane lookup rejects forwarding

#### Scenario: Delete removes route
- **WHEN** a Delete route is applied
- **THEN** the active route is removed, no Delete record is visible to the data plane, and a decision
  tombstone preserves deletion freshness

#### Scenario: Existing freshness rules remain
- **WHEN** an older Allow, Deny, or Delete update for the same UID is received
- **THEN** resource-version comparison prevents it from overriding a newer active decision or tombstone

### Requirement: Equal resource version is ordered fail-closed
For the same Sandbox UID and equal resource version, action strength SHALL be Delete greater than
Deny greater than Allow. A stronger decision SHALL replace a weaker decision, and a weaker decision
MUST NOT replace a stronger decision. A Delete tombstone SHALL reject Allow or Deny with the same or
older resource version. A strictly newer resource version for the same UID or a new UID for the same
route ID MAY replace the tombstone.

#### Scenario: Slow Allow follows deadline Delete
- **WHEN** one observer produces Delete after shutdown expiry and a slower observer later produces
  Allow for the same UID and resource version
- **THEN** the Delete tombstone rejects Allow and the route remains non-forwarding

#### Scenario: Deny strengthens Allow
- **WHEN** Deny arrives after Allow for the same UID and resource version
- **THEN** Deny replaces Allow and forwarding stops

#### Scenario: Allow cannot weaken Deny
- **WHEN** Allow arrives after Deny for the same UID and resource version
- **THEN** Allow is rejected and forwarding remains denied

#### Scenario: Newer CR reverses an expired decision
- **WHEN** a strictly newer resource version for the same UID extends shutdown time and produces
  Allow or Deny
- **THEN** it may replace the older Delete tombstone

#### Scenario: Sandbox ID is reused
- **WHEN** a route ID is reused by a Sandbox with a different UID
- **THEN** the old UID tombstone does not prevent the new Sandbox route from being applied

### Requirement: Route wire supports mixed-version rollout
A compatibility wire adapter SHALL emit both Action and a legacy top-level state field. It SHALL
encode Allow as `running`, Deny as `paused`, and Delete as `dead`. A valid Action SHALL be
authoritative; when Action is absent, each component SHALL apply its approved legacy fallback before
validation and mutation.

#### Scenario: New receiver gets both fields
- **WHEN** a payload contains a valid Action and conflicting legacy state
- **THEN** the receiver uses Action and ignores legacy state for behavior

#### Scenario: Manager receives old running
- **WHEN** Action is absent and legacy state is `running`
- **THEN** Manager/proxy decodes Allow

#### Scenario: Manager receives old dead
- **WHEN** Action is absent and legacy state is `dead`
- **THEN** Manager/proxy decodes Delete

#### Scenario: Manager receives another old state
- **WHEN** Action is absent and legacy state is neither `running` nor `dead`
- **THEN** Manager/proxy decodes Deny

#### Scenario: Gateway receives old running
- **WHEN** Action is absent and legacy state is `running`
- **THEN** Gateway decodes Allow

#### Scenario: Gateway receives old non-running
- **WHEN** Action is absent and legacy state is not `running`
- **THEN** Gateway decodes Delete, preserving its existing refresh behavior

### Requirement: Mixed-version differences remain fail-closed
Old and new components MAY retain different records for a live non-running Sandbox during rolling
upgrade, but no compatibility path SHALL translate a non-running or unknown legacy value into Allow.
Compatibility decoding SHALL occur before freshness and equal-version action ordering, so a legacy
Delete creates the same tombstone. Existing local CR and peer reconciliation SHALL remain able to
restore the current canonical route.

Every route producer and receiver participating in the supported mixed-version window SHALL already
implement the deletion tombstone and conservative legacy-running baseline from the
`sandbox-provider` prerequisite, including authoritative cache-sync readiness, restart rebuilding,
peer-update validation, and safe tombstone collection. A baseline producer SHALL NOT emit legacy
`running` for an observation this change maps to Deny or Delete. Components older than that baseline
MUST be upgraded before Action production is enabled.

#### Scenario: New Deny reaches old Gateway
- **WHEN** a new sender encodes Deny with legacy state `paused` and an old Gateway receives it
- **THEN** the old Gateway may remove the route but does not forward it

#### Scenario: Old non-running reaches new Gateway
- **WHEN** an old sender emits a non-running legacy state without Action
- **THEN** new Gateway removes the route and does not forward it

#### Scenario: Old non-running reaches new Manager
- **WHEN** an old sender emits a non-dead non-running legacy state without Action
- **THEN** new Manager retains a Deny route and does not forward it

#### Scenario: Baseline sender observes a new Deny fact
- **WHEN** a baseline sender without Action observes incomplete resume initialization, unsafe
  in-place update, cleanup request, or another fact the new model denies
- **THEN** it emits a non-running legacy state and no supported receiver enables forwarding

#### Scenario: Canonical observation follows mixed-version update
- **WHEN** a new component later observes the current Sandbox CR
- **THEN** it reapplies canonical GetRoute subject to existing resource-version and ownership rules

#### Scenario: Pre-baseline component is present
- **WHEN** any Manager, proxy, or Gateway route producer or receiver lacks the complete route-safety
  baseline
- **THEN** rollout does not enable the new state-to-Action production

### Requirement: Compatibility state is wire only
The legacy state field MUST NOT be copied into core Route, stored as lifecycle state, used by data-
plane filters, or used as proof of Sandbox existence or ownership. Existing route identity, peer
membership, reconciliation ownership, freshness comparison, and access-token redaction SHALL remain
unchanged.

#### Scenario: Data plane receives normalized route
- **WHEN** a legacy payload has been decoded
- **THEN** the data plane evaluates only normalized Action

#### Scenario: Route is logged
- **WHEN** a Route with an access token is formatted for logs
- **THEN** existing token redaction remains in effect

#### Scenario: Compatibility window ends
- **WHEN** all supported peers understand Action and a later cleanup change is approved
- **THEN** the wire-only legacy field may be removed without changing core Route or GetRoute policy
