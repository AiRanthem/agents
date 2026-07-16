## ADDED Requirements

### Requirement: Sandbox-manager owns one total internal state model
The system SHALL define exactly `claimable`, `running`, `pausing`, `paused`, `resuming`, `unready`, `terminating`, and `completed` as the sandbox-manager internal Sandbox states. Derivation SHALL return one of these states plus a non-empty diagnostic reason for every Sandbox CR observation and SHALL NOT persist the derived state in the CRD.

#### Scenario: Unsupported phase is safe
- **WHEN** a Sandbox has an empty or unsupported future phase and no higher-priority removal or completion fact
- **THEN** sandbox-manager observes `unready` with a non-empty diagnostic reason

#### Scenario: State is not persisted
- **WHEN** sandbox-manager derives a state
- **THEN** it does not write that state into Sandbox spec, status, labels, or annotations

### Requirement: State derivation is private and time deterministic
`infra.Sandbox.GetState()` SHALL return a `SandboxStateObservation`. The CR-backed implementation SHALL delegate to an unexported sandboxcr function that accepts the observation time explicitly. Controller, SandboxSet, cache, proxy, and Gateway MUST NOT call the derivation or consume the sandbox-manager state type.

#### Scenario: Repeated explicit-time observation
- **WHEN** the same Sandbox and observation time are evaluated repeatedly
- **THEN** the state and diagnostic reason are identical without reading a clock or external system inside the pure function

#### Scenario: Upper layer reads state
- **WHEN** sandbox-manager or its E2B server needs lifecycle policy
- **THEN** it uses `infra.Sandbox.GetState()` rather than phase, conditions, cleanup metadata, or a shared CR state helper

### Requirement: Removal observations converge on terminating
Deletion timestamp, an expired shutdown time, the reserved-failed label, accepted cleanup, phase `Recycling`, and phase `Terminating` SHALL derive `terminating`. `terminating` SHALL describe removal in progress and SHALL NOT be terminal.

#### Scenario: Recycling is removal
- **WHEN** phase is `Recycling` or both cleanup and cleanup-enabled annotations equal true
- **THEN** the observed state is `terminating` without exposing the removal mechanism

#### Scenario: Reserved failed waits for deletion
- **WHEN** a Sandbox carries the reserved-failed label
- **THEN** the observed state is `terminating` regardless of its otherwise-derived state

#### Scenario: Deletion overrides completion
- **WHEN** phase is `Succeeded` or `Failed` and the Sandbox also has a deletion timestamp
- **THEN** the observed state is `terminating`

#### Scenario: Shutdown boundary preserves current semantics
- **WHEN** the observation time is strictly after `spec.shutdownTime`
- **THEN** the observed state is `terminating`

### Requirement: Completed is the only terminal state
A non-removing Sandbox in phase `Succeeded` or `Failed` SHALL derive `completed`. Successful and failed completion MUST NOT produce different internal terminal states.

#### Scenario: Successful completion
- **WHEN** phase is `Succeeded` and no higher-priority removal fact applies
- **THEN** the observed state is `completed`

#### Scenario: Failed completion
- **WHEN** phase is `Failed` and no higher-priority removal fact applies
- **THEN** the observed state is `completed`

### Requirement: Pause and resume progress is explicit
The system SHALL derive `pausing`, `paused`, and `resuming` from the declared phase, `spec.paused`, the Paused condition, the Resumed condition, and post-resume RuntimeInitialized condition using the approved narrow gates.

#### Scenario: Pause requested from Running
- **WHEN** phase is `Running` and `spec.paused=true`
- **THEN** the observed state is `pausing`

#### Scenario: Pause is incomplete
- **WHEN** phase is `Paused` and the Paused condition is absent or not true
- **THEN** the observed state is `pausing`

#### Scenario: Pause is complete
- **WHEN** phase is `Paused`, `spec.paused=true`, and the Paused condition is true
- **THEN** the observed state is `paused`

#### Scenario: Resume is requested after pause
- **WHEN** phase is `Paused`, the Paused condition is true, and `spec.paused=false`
- **THEN** the observed state is `resuming`

#### Scenario: Resume phase is explicit
- **WHEN** phase is `Resuming`
- **THEN** the observed state is `resuming`

#### Scenario: Post-resume initialization is incomplete
- **WHEN** phase is `Running`, Resumed is true, and an existing RuntimeInitialized condition is not true
- **THEN** the observed state is `resuming`

#### Scenario: Unfinished resume precedes a new pause observation
- **WHEN** phase is `Running`, Resumed is true, RuntimeInitialized exists and is not true, and `spec.paused=true`
- **THEN** the observed state remains `resuming` so Pause applies the opposite-direction conflict policy until resume initialization completes

#### Scenario: Missing initialization condition is not resume progress
- **WHEN** phase is `Running`, Resumed is true, and RuntimeInitialized is absent
- **THEN** the observation falls through to the other serviceability rules

### Requirement: Unready covers non-paused non-serving progress
The system SHALL derive `unready` for non-removing, non-completed observations that are neither an explicit pause/resume state nor serviceable/claimable. Phase `Upgrading` and existing in-place reasons `InplaceUpdating` or `Failed` SHALL be `unready`; in-place `Succeeded` SHALL fall through to serviceability evaluation. The change MUST NOT add new Controller update reasons.

#### Scenario: Recreate upgrade is unavailable
- **WHEN** phase is `Upgrading`
- **THEN** the observed state is `unready`

#### Scenario: In-place update is active
- **WHEN** phase is `Running` and the InplaceUpdate reason is `InplaceUpdating`
- **THEN** the observed state is `unready`

#### Scenario: Existing in-place failure remains unavailable
- **WHEN** phase is `Running` and the InplaceUpdate reason is `Failed`
- **THEN** the observed state is `unready`

#### Scenario: Running is not serviceable
- **WHEN** a non-pool phase `Running` Sandbox is not paused but Ready is not true or Pod IP is empty
- **THEN** the observed state is `unready`

### Requirement: Serving and pool observations are distinct
After higher-priority rules, `sandboxset.IsSandboxAvailable` SHALL produce `claimable`. A non-pool Sandbox SHALL be `running` only when phase is `Running`, it is not paused, Ready is true, and Pod IP is non-empty. Every other live observation SHALL fall back to `unready`.

#### Scenario: Pool member is claimable
- **WHEN** the SandboxSet available helper returns true and no higher-priority manager rule applies
- **THEN** the observed state is `claimable`

#### Scenario: Claimed or standalone Sandbox serves
- **WHEN** phase is `Running`, the Sandbox is neither paused nor pool-available (`claimable`), Ready is true, Pod IP is non-empty, and no higher rule applies
- **THEN** the observed state is `running`

#### Scenario: Claimable does not replace claim safeguards
- **WHEN** a pool Sandbox is observed as `claimable`
- **THEN** claim selection still applies its independent Pod-IP, resource-version expectation, candidate, lock, and update-revision checks

### Requirement: Recycle eligibility hides raw phase
`infra.Sandbox` SHALL expose `IsRecyclable()` instead of `IsRecycleEnabled()` and `Phase()`. The CR-backed implementation SHALL return true exactly when cleanup is enabled and raw phase is `Running`; sandbox-manager SHALL preserve the existing trigger, metrics, and fallback-to-delete flow.

#### Scenario: Running cleanup-enabled Sandbox
- **WHEN** cleanup is enabled and phase is `Running`
- **THEN** `IsRecyclable()` returns true without exposing phase to sandbox-manager

#### Scenario: Non-running or disabled Sandbox
- **WHEN** cleanup is disabled or phase is not `Running`
- **THEN** `IsRecyclable()` returns false
