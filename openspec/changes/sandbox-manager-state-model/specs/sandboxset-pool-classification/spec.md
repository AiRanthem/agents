## ADDED Requirements

### Requirement: Sandbox CR provider owns pool predicates
`pkg/sandboxprovider/sandboxcr` SHALL provide pure explicit-time pool creating and available
predicates. They SHALL preserve the legacy five-state helper's creating/available semantics and MUST
NOT return or depend on the manager-oriented eight-state observation. The provider MUST NOT import
Controller to implement them.

#### Scenario: Pending is creating
- **WHEN** a non-terminal Sandbox has phase Pending
- **THEN** creating is true and available is false

#### Scenario: Controlled ready member is available
- **WHEN** a non-terminal SandboxSet-controlled Sandbox is not Pending and Ready is true
- **THEN** available is true and creating is false

#### Scenario: Controlled unready member is creating
- **WHEN** a non-terminal SandboxSet-controlled Sandbox is not Pending and Ready is absent or not true
- **THEN** creating is true and available is false

#### Scenario: Terminal observation is neither pool state
- **WHEN** deletion is set, observation time is after shutdown time, or phase is Succeeded, Failed,
  or Terminating
- **THEN** both predicates return false

#### Scenario: Shutdown equality is not terminal
- **WHEN** observation time equals shutdown time and no other terminal fact applies
- **THEN** shutdown time alone does not force both predicates false

### Requirement: Available preserves claim preconditions
The available predicate MUST NOT add Pod-IP, lock, claim-label, update-revision, or candidate-validity
requirements. Those safeguards SHALL remain in shared sandboxcr claim selection.

#### Scenario: Ready member lacks Pod IP
- **WHEN** a SandboxSet-controlled member is Ready but has no Pod IP
- **THEN** available may be true but claim selection excludes it from immediately available candidates

#### Scenario: Candidate lock is unavailable
- **WHEN** available is true but the candidate cannot acquire its claim lock
- **THEN** claim selection applies existing retry/failure behavior rather than changing pool classification

#### Scenario: Candidate revision is old
- **WHEN** available is true but another candidate matches the current SandboxSet update revision
- **THEN** claim selection preserves its updated-before-old preference

#### Scenario: Claimed label is present
- **WHEN** the legacy available facts are true and the claimed label is present
- **THEN** the pool predicate itself does not add a new claimed-label exclusion

### Requirement: Controller and cache preserve local behavior
SandboxSet grouping, event handling, pool indexing, active counting, and waiters SHALL migrate away
from the shared state helper without changing existing behavior. These consumers MUST NOT call
provider GetState, import Manager infra, or compare manager-oriented state values.

#### Scenario: Pool index retains creating and available
- **WHEN** a Sandbox matches existing creating or available pool rules and has a template
- **THEN** the pool index continues to include it

#### Scenario: Available transition enqueues reconciliation
- **WHEN** a SandboxSet member changes from creating to available
- **THEN** the event handler preserves existing enqueue and ready-cost logging behavior

#### Scenario: Used member remains used
- **WHEN** a SandboxSet-controlled member is claimed and its purpose-specific Controller grouping
  classifies it as used
- **THEN** it is not moved into creating or available merely because Manager GetState is not used

#### Scenario: Active count remains behavior compatible
- **WHEN** active Sandbox counting runs after migration
- **THEN** it preserves existing reserved-failed and legacy-dead exclusion policy without adding a
  claimed-only requirement

#### Scenario: Quota policy remains independent
- **WHEN** API-key quota liveness is evaluated
- **THEN** existing deletion, terminating, recycling, and cleanup policy remains unchanged and does
  not consume Manager state

### Requirement: Waiters retain operation-specific facts
Cache waiters SHALL use required CR conditions, generation, Pod IP, and operation-specific failure
signals directly. They MUST NOT consume Manager state, and migration SHALL preserve success,
fast-failure, retry, timeout, and cancellation behavior.

#### Scenario: Startup failure still fails fast
- **WHEN** Ready reports StartContainerFailed
- **THEN** readiness waiter returns its existing fast failure

#### Scenario: Ordinary unready observation waits
- **WHEN** generation is observed but Ready is not true and no terminal operation-specific failure exists
- **THEN** readiness waiter continues under its current timeout and retry policy

#### Scenario: In-place update still waits
- **WHEN** existing InplaceUpdate reason is InplaceUpdating
- **THEN** readiness waiter does not report success until existing convergence rules are satisfied

#### Scenario: Pause and resume waiters preserve purpose
- **WHEN** pause or resume operation-specific conditions are still converging
- **THEN** the corresponding waiter uses those facts rather than the Manager state to determine completion

### Requirement: Manager claimable reuses only the available fact
The CR provider's Manager GetState derivation MAY call the same pool available predicate after all
higher-priority Manager state rules. It MUST NOT treat the separate pool creating predicate as a
Manager state or use `claimable` as proof that an atomic claim will succeed.

#### Scenario: Available becomes claimable
- **WHEN** pool available is true and no higher-priority Manager state applies
- **THEN** GetState returns `claimable`

#### Scenario: Creating remains Manager unready
- **WHEN** pool creating is true and no higher-priority Manager state applies
- **THEN** GetState falls through to `unready`

#### Scenario: Claimable candidate later fails a safeguard
- **WHEN** GetState returns claimable but Pod IP, freshness, lock, or revision selection prevents claim
- **THEN** TryClaimSandbox preserves existing retry or failure behavior
