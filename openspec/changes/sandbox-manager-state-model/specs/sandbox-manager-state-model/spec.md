## ADDED Requirements

### Requirement: Provider exposes one total Manager-oriented state model
`pkg/sandboxprovider` SHALL define exactly `claimable`, `running`, `pausing`, `paused`, `resuming`,
`unready`, `terminating`, and `completed` as the manager-oriented Sandbox states. Observation SHALL
return one state plus a non-empty diagnostic reason for every Sandbox CR and SHALL NOT persist the
derived state or reason.

#### Scenario: Unsupported phase is safe
- **WHEN** a Sandbox has an empty or unsupported future phase and no higher-priority removal or
  completion fact
- **THEN** GetState returns `unready` with a non-empty diagnostic reason

#### Scenario: State is not persisted
- **WHEN** the provider derives a state
- **THEN** it does not write state or diagnostic reason into Sandbox spec, status, labels, or annotations

#### Scenario: Public response is separate
- **WHEN** Manager receives a provider observation
- **THEN** it returns a protocol-independent lifecycle outcome, and E2B applies public projection
  without treating the internal state or diagnostic reason as a public Sandbox state

### Requirement: State derivation is private and time deterministic
The provider Sandbox `GetState` method SHALL return `SandboxStateObservation`. The CR-backed
implementation SHALL delegate to an unexported sandboxcr derivation accepting observation time
explicitly. No exported free CR-to-state function SHALL exist. Manager SHALL use GetState; Gateway
SHALL obtain the observation only through GetRoute; Controller, SandboxSet, cache, and proxy MUST
NOT consume the eight-state type.

#### Scenario: Repeated explicit-time observation
- **WHEN** the same Sandbox and observation time are evaluated repeatedly
- **THEN** state and diagnostic reason are identical without reading a clock or external system
  inside the pure derivation

#### Scenario: Manager reads state
- **WHEN** Manager needs lifecycle policy
- **THEN** it uses the provider GetState capability rather than phase, conditions, cleanup metadata,
  reserved-failed metadata, or a free CR helper

#### Scenario: E2B needs lifecycle behavior
- **WHEN** E2B needs to project or reject a Sandbox lifecycle outcome
- **THEN** it calls the Manager interface and does not call GetState or import provider/infra

#### Scenario: Controller evaluates a pool member
- **WHEN** Controller, SandboxSet, or cache needs pool classification
- **THEN** it uses provider pool predicates and does not call GetState

#### Scenario: Gateway needs routing
- **WHEN** Gateway observes a Sandbox CR
- **THEN** it calls provider GetRoute and does not compare provider state values

### Requirement: Removal observations converge on terminating
Deletion timestamp, observation time strictly after shutdown time, phase Recycling, and phase
Terminating SHALL derive `terminating`. `terminating` SHALL describe removal in progress and SHALL
NOT be terminal. Cleanup request metadata alone SHALL NOT select `terminating`.

#### Scenario: Recycling is removal
- **WHEN** phase is Recycling
- **THEN** state is `terminating` without exposing the removal mechanism

#### Scenario: Cleanup request awaits Controller action
- **WHEN** cleanup and cleanup-enabled annotations both equal true but phase remains Running and no
  deletion timestamp exists
- **THEN** state is `unready` rather than `terminating`

#### Scenario: Deletion overrides completion
- **WHEN** phase is Succeeded or Failed and the Sandbox also has a deletion timestamp
- **THEN** state is `terminating`

#### Scenario: Shutdown boundary preserves current semantics
- **WHEN** observation time is strictly after `spec.shutdownTime`
- **THEN** state is `terminating`

#### Scenario: Shutdown equality is not expired
- **WHEN** observation time equals `spec.shutdownTime`
- **THEN** shutdown time alone does not select `terminating`

### Requirement: Completed is the only terminal state
A non-removing Sandbox in phase Succeeded or Failed SHALL derive `completed`. A Sandbox carrying the
reserved-failed label without a higher-priority removal fact SHALL also derive `completed`, including
forever retention without a shutdown deadline. Successful completion, failed completion, and a
permanently non-claimable failed-claim artifact MUST NOT produce different internal terminal states.

#### Scenario: Successful completion
- **WHEN** phase is Succeeded and no higher-priority removal fact applies
- **THEN** state is `completed`

#### Scenario: Failed completion
- **WHEN** phase is Failed and no higher-priority removal fact applies
- **THEN** state is `completed`

#### Scenario: Failed Sandbox is retained forever
- **WHEN** the reserved-failed label is present, no shutdown deadline has expired, and no deletion or
  recycling fact applies
- **THEN** state is `completed`

#### Scenario: Failed Sandbox reaches a finite retention deadline
- **WHEN** the reserved-failed label is present and observation time is strictly after its shutdown
  deadline
- **THEN** the higher-priority state is `terminating`

### Requirement: Pause and resume progress is explicit
The system SHALL derive `pausing`, `paused`, and `resuming` from phase, `spec.paused`, the Paused
condition, the Resumed condition, and post-resume RuntimeInitialized condition using the approved
priority.

#### Scenario: Pause requested from Running
- **WHEN** phase is Running and `spec.paused=true`
- **THEN** state is `pausing`

#### Scenario: Pause is incomplete
- **WHEN** phase is Paused and the Paused condition is absent or not true
- **THEN** state is `pausing`

#### Scenario: Pause is complete
- **WHEN** phase is Paused, `spec.paused=true`, and Paused is true
- **THEN** state is `paused`

#### Scenario: Resume is requested after pause
- **WHEN** phase is Paused, Paused is true, and `spec.paused=false`
- **THEN** state is `resuming`

#### Scenario: Resume phase is explicit
- **WHEN** phase is Resuming
- **THEN** state is `resuming`

#### Scenario: Post-resume initialization is incomplete
- **WHEN** phase is Running, Resumed is true, and an existing RuntimeInitialized condition is not true
- **THEN** state is `resuming`

#### Scenario: Unfinished resume precedes a new pause observation
- **WHEN** phase is Running, Resumed is true, RuntimeInitialized exists and is not true, and
  `spec.paused=true`
- **THEN** state remains `resuming` until post-resume initialization completes

#### Scenario: Missing initialization condition is not resume progress
- **WHEN** phase is Running, Resumed is true, and RuntimeInitialized is absent
- **THEN** observation falls through to the other serviceability rules

### Requirement: Unready covers live non-serving observations
The system SHALL derive `unready` for non-removing, non-completed observations that are neither an
explicit pause/resume state nor serviceable/claimable. Phase Upgrading and existing InplaceUpdate
reasons InplaceUpdating or Failed SHALL be `unready`; InplaceUpdate Succeeded SHALL fall through to
serviceability evaluation. No new Controller update reason SHALL be introduced.

#### Scenario: Recreate upgrade is unavailable
- **WHEN** phase is Upgrading
- **THEN** state is `unready`

#### Scenario: In-place update is active
- **WHEN** phase is Running and InplaceUpdate reason is InplaceUpdating
- **THEN** state is `unready`

#### Scenario: Existing in-place failure remains unavailable
- **WHEN** phase is Running and InplaceUpdate reason is Failed
- **THEN** state is `unready`

#### Scenario: Successful in-place update continues evaluation
- **WHEN** phase is Running and InplaceUpdate reason is Succeeded
- **THEN** Ready, Pod IP, pause/resume, and higher-priority facts determine the state

#### Scenario: Running is not serviceable
- **WHEN** a non-pool Running Sandbox is not paused but Ready is not true or Pod IP is empty
- **THEN** state is `unready`

### Requirement: Serving and pool observations are distinct
After higher-priority rules, the provider pool-available predicate SHALL produce `claimable`. A
non-pool Sandbox SHALL be `running` only when phase is Running, it is not paused, Ready is true, and
Pod IP is non-empty. Every other live observation SHALL fall back to `unready`.

#### Scenario: Pool member is claimable
- **WHEN** the provider pool-available predicate is true and no higher-priority state applies
- **THEN** state is `claimable`

#### Scenario: Claimed or standalone Sandbox serves
- **WHEN** phase is Running, the Sandbox is not pool-available, it is not paused, Ready is true, Pod
  IP is non-empty, and no higher rule applies
- **THEN** state is `running`

#### Scenario: Claimable does not replace claim safeguards
- **WHEN** a pool Sandbox is observed as `claimable`
- **THEN** shared claim selection still applies Pod-IP, resource-version expectation, candidate,
  lock, speculation, and update-revision checks

#### Scenario: Pending falls back safely
- **WHEN** a live Sandbox is Pending and no higher-priority fact applies
- **THEN** Manager state is `unready` even if the separate pool-creating predicate is true

### Requirement: Recycle eligibility hides raw phase
The provider Sandbox SHALL expose `IsRecyclable` instead of raw `Phase` plus `IsRecycleEnabled` to
Manager. The CR implementation SHALL return true when cleanup is enabled, phase is Running, and
known Controller recycle preconditions pass, including absence of persistent-volume claims.
Manager SHALL preserve trigger metrics when recycling is attempted and SHALL use direct deletion
when IsRecyclable is false or triggering fails.

#### Scenario: Running cleanup-enabled Sandbox
- **WHEN** cleanup is enabled, phase is Running, and no known recycle rejection fact exists
- **THEN** IsRecyclable returns true without exposing phase to Manager

#### Scenario: Non-running, disabled, or PVC-backed Sandbox
- **WHEN** cleanup is disabled, phase is not Running, or the Sandbox uses persistent-volume claims
- **THEN** IsRecyclable returns false

#### Scenario: Cleanup has been requested
- **WHEN** Manager successfully triggers the recycle flow
- **THEN** GetState reports `unready` until phase becomes Recycling or deletion starts

#### Scenario: Controller rejects a requested recycle
- **WHEN** a cleanup request becomes ineligible before Controller starts Recycling
- **THEN** Controller starts direct deletion so the accepted Delete request converges to
  `terminating` and absence
