## ADDED Requirements

### Requirement: SandboxSet owns creating and available predicates
`pkg/controller/sandboxset` SHALL provide pure, explicit-time `IsSandboxCreating` and `IsSandboxAvailable` predicates. They SHALL preserve the current five-state helper's creating/available semantics and MUST NOT return or depend on sandbox-manager state.

#### Scenario: Pending is creating
- **WHEN** a non-terminal Sandbox has phase `Pending`
- **THEN** `IsSandboxCreating` is true and `IsSandboxAvailable` is false

#### Scenario: Controlled ready member is available
- **WHEN** a non-terminal SandboxSet-controlled Sandbox is not Pending and Ready is true
- **THEN** `IsSandboxAvailable` is true and `IsSandboxCreating` is false

#### Scenario: Controlled unready member is creating
- **WHEN** a non-terminal SandboxSet-controlled Sandbox is not Pending and Ready is absent or not true
- **THEN** `IsSandboxCreating` is true and `IsSandboxAvailable` is false

#### Scenario: Terminal observation is neither pool state
- **WHEN** deletion is set, shutdown time has expired, or phase is `Succeeded`, `Failed`, or `Terminating`
- **THEN** both predicates return false

### Requirement: Available preserves existing claim preconditions
The available predicate MUST NOT add Pod-IP, lock, claim-label, update-revision, or candidate-validity requirements. Those safeguards SHALL remain in sandboxcr claim selection.

#### Scenario: Ready member lacks Pod IP
- **WHEN** a SandboxSet-controlled member is Ready but has no Pod IP
- **THEN** the available predicate may be true but claim selection excludes it from immediately available candidates

#### Scenario: Candidate lock is unavailable
- **WHEN** the available predicate is true but the candidate cannot acquire its claim lock
- **THEN** claim selection applies its existing retry/failure behavior rather than changing pool classification

### Requirement: SandboxSet and cache preserve local behavior
SandboxSet grouping, event handling, pool indexing, active counting, and waiters SHALL migrate away from the shared state helper without changing their existing behavior. These consumers MUST NOT import `pkg/sandbox-manager/infra` or compare sandbox-manager states.

#### Scenario: Pool index retains creating and available
- **WHEN** a Sandbox matches the existing creating or available pool rules and has a template
- **THEN** the pool index continues to include it

#### Scenario: Available transition enqueues reconciliation
- **WHEN** a SandboxSet member changes from the local creating classification to the local available classification
- **THEN** the event handler preserves the existing enqueue and ready-cost logging behavior

#### Scenario: Active count remains behavior compatible
- **WHEN** active Sandbox counting runs after migration
- **THEN** it preserves the existing reserved-failed and legacy-dead exclusion policy without adding a claimed-only requirement

#### Scenario: Quota policy remains independent
- **WHEN** API-key quota liveness is evaluated
- **THEN** the existing deletion, terminating, recycling, and cleanup policy remains unchanged and does not consume manager state

### Requirement: Waiters retain operation-specific facts
Cache waiters SHALL use their required CR conditions, generation, Pod IP, and operation-specific failure signals directly. They MUST NOT import manager state, and migration MUST preserve current success, fast-failure, retry, timeout, and cancellation behavior.

#### Scenario: Startup failure still fails fast
- **WHEN** the Ready condition reports `StartContainerFailed`
- **THEN** the readiness waiter returns its existing fast failure

#### Scenario: Ordinary unready observation waits
- **WHEN** generation is observed but Ready is not yet true and no terminal operation-specific failure exists
- **THEN** the readiness waiter continues according to its current timeout and retry policy

#### Scenario: In-place update still waits
- **WHEN** the existing InplaceUpdate reason is `InplaceUpdating`
- **THEN** the readiness waiter does not report success until the existing convergence rules are satisfied
