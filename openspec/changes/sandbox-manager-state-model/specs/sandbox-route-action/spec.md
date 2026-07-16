## ADDED Requirements

### Requirement: Route uses producer-selected action
The core Route SHALL contain a typed Action with exactly `allow`, `deny`, or `delete` and SHALL NOT contain lifecycle state. Sandbox-to-route metadata projection MUST NOT derive Action; every producer SHALL explicitly select Action before route mutation or synchronization.

#### Scenario: Manager selects action
- **WHEN** sandbox-manager pushes a Route
- **THEN** it maps its `SandboxStateObservation` to the specified Action without placing the internal state in Route

#### Scenario: Gateway selects action
- **WHEN** Gateway observes a Sandbox CR
- **THEN** it selects Action from its local serving/removal facts without importing sandbox-manager state

#### Scenario: Missing action is invalid
- **WHEN** compatibility decoding produces no valid Action
- **THEN** the route mutation is rejected and forwarding is not enabled

### Requirement: Manager state maps to one route action
Sandbox-manager SHALL map `running` to Allow; `claimable`, `pausing`, `paused`, `resuming`, and `unready` to Deny; and `terminating` and `completed` to Delete.

#### Scenario: Healthy running Sandbox forwards
- **WHEN** the manager observation is `running`
- **THEN** the produced Route action is Allow

#### Scenario: Live non-serving Sandbox is retained
- **WHEN** the manager observation is `claimable`, `pausing`, `paused`, `resuming`, or `unready`
- **THEN** the produced Route action is Deny

#### Scenario: Removal or completion deletes
- **WHEN** the manager observation is `terminating` or `completed`
- **THEN** the produced Route action is Delete

### Requirement: Gateway owns a CR-local route policy
Gateway SHALL select Delete for deletion, expired shutdown, reserved-failed, accepted cleanup, or phase `Recycling`, `Terminating`, `Succeeded`, or `Failed`. It SHALL select Allow only for a non-SandboxSet-controlled phase `Running` Sandbox that is not paused, has Ready true, has a non-empty Pod IP, and has no known active unsafe update marker. Every other live observation SHALL select Deny.

#### Scenario: Gateway sees a serviceable Sandbox
- **WHEN** all Gateway Allow facts are satisfied
- **THEN** Gateway selects Allow

#### Scenario: Gateway sees a live transition
- **WHEN** the Sandbox is live but the Allow facts are not all satisfied and no Delete fact applies
- **THEN** Gateway selects Deny

#### Scenario: Gateway sees accepted cleanup
- **WHEN** cleanup and cleanup-enabled annotations both equal true
- **THEN** Gateway selects Delete before the phase changes to Recycling

### Requirement: Route storage and forwarding obey action
Allow and Deny SHALL be eligible for resource-version-aware route storage. Only Allow SHALL forward data-plane requests. Delete SHALL invoke route removal and MUST NOT be stored as an active Route.

#### Scenario: Denied route remains visible but does not forward
- **WHEN** a newer Deny Route is applied
- **THEN** the active route record is updated but data-plane lookup rejects forwarding

#### Scenario: Delete removes route
- **WHEN** a Delete Route is applied
- **THEN** the route is removed and no Delete record remains active

#### Scenario: Existing freshness rules remain
- **WHEN** an older Allow or Deny Route is received
- **THEN** the existing resource-version comparison prevents it from replacing a newer record

### Requirement: Route wire supports mixed-version rollout
A compatibility wire adapter SHALL emit both Action and a legacy top-level state field. It SHALL encode Allow as `running`, Deny as `paused`, and Delete as `dead`. A valid received Action SHALL be authoritative; when Action is absent, each component SHALL apply its approved legacy policy before validation and mutation.

#### Scenario: New receiver gets both fields
- **WHEN** a payload contains a valid Action and a conflicting legacy state
- **THEN** the receiver uses Action and ignores legacy state for behavior

#### Scenario: Manager receives an old running route
- **WHEN** Action is absent and legacy state is `running`
- **THEN** manager/proxy decodes Allow

#### Scenario: Manager receives an old non-running route
- **WHEN** Action is absent and legacy state is `dead`
- **THEN** manager/proxy decodes Delete

#### Scenario: Manager receives another old state
- **WHEN** Action is absent and legacy state is neither `running` nor `dead`
- **THEN** manager/proxy decodes Deny

#### Scenario: Gateway receives an old non-running route
- **WHEN** Action is absent and legacy state is not `running`
- **THEN** Gateway decodes Delete, preserving its current peer-refresh behavior

### Requirement: Compatibility state is wire only
The legacy state field MUST NOT be copied into core Route, stored as lifecycle state, used by data-plane filters, or used as proof of Sandbox existence or ownership. Existing route identity, peer membership, reconciliation ownership, freshness comparison, and access-token redaction SHALL remain unchanged.

#### Scenario: Data plane receives normalized route
- **WHEN** a legacy payload has been decoded
- **THEN** the data plane evaluates only the normalized Action

#### Scenario: Route is logged
- **WHEN** a Route with an access token is formatted for logs
- **THEN** the existing token redaction remains in effect
