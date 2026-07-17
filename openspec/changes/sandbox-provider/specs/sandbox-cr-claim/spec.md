## ADDED Requirements

### Requirement: Claim options are split by responsibility
Common claim input, result, admission, resource/update/runtime/CSI intent, lock classification,
failure records, and metrics SHALL live in `pkg/sandboxprovider`. SandboxClaim pointers,
RuntimeConfig CR values, CR metadata tracking, the narrow claim backend, pick cache, worker
semaphore, and create limiter SHALL live in sandboxcr execution options. Concrete clients and cache
MUST NOT appear in shared options. Manager infra MUST NOT define duplicate shared claim option or
result types.

#### Scenario: Manager requests a claim
- **WHEN** Manager calls its infrastructure port
- **THEN** it supplies only provider-neutral claim data and receives provider-owned result and metrics

#### Scenario: Manager CR adapter executes a claim
- **WHEN** the CR adapter handles the neutral request
- **THEN** it builds sandboxcr execution options with CR-only data and its Manager-infra backend

#### Scenario: SandboxClaim controller executes a claim
- **WHEN** a SandboxClaim reconcile needs a Sandbox
- **THEN** it constructs sandboxcr execution options with its Controller backend without importing
  Manager config or infra

#### Scenario: Shared options are inspected
- **WHEN** the parent and child claim option types are inspected
- **THEN** they contain no controller-runtime client, concrete cache, Manager, server, or Controller type

### Requirement: Defaults are explicit caller input
Manager and controller SHALL resolve their policy defaults before claim validation and side effects.
The shared claim implementation MUST NOT import Manager constants or silently select Manager/API
defaults. Omitted values SHALL preserve current behavior through explicit caller-provided defaults.

#### Scenario: Manager omits an optional value
- **WHEN** Manager receives a request without candidate, wait, claim, or failure-retention values
- **THEN** its adapter supplies the existing Manager default explicitly before validation

#### Scenario: Controller reserves a failed Sandbox forever
- **WHEN** SandboxClaim policy selects the existing forever retention behavior
- **THEN** Controller supplies that value without importing a Manager constant

#### Scenario: Validation rejects an invalid request
- **WHEN** resolved options omit required identity/template data or contain invalid update/runtime/CSI
  combinations
- **THEN** validation returns before `TryClaimSandbox` performs admission, create, or update side effects

### Requirement: TryClaimSandbox preserves candidate and lock behavior
The shared CR `TryClaimSandbox` SHALL orchestrate through the supplied narrow backend and preserve
current candidate count, current-revision preference,
available-before-speculative ordering, speculation duration, create-on-no-stock, Pod-IP checks,
resource-version expectations, pick-cache exclusion, worker semaphore, create limiter, optimistic
locking, retry classification, and context cancellation behavior.

#### Scenario: Updated available candidate exists
- **WHEN** updated and old available candidates are both valid
- **THEN** claim attempts an updated candidate first under the existing randomized selection rules

#### Scenario: No available candidate exists
- **WHEN** speculation is enabled and an eligible creating candidate exists
- **THEN** claim attempts the speculative candidate before creating a new Sandbox

#### Scenario: No stock may be created
- **WHEN** no candidate is usable and create-on-no-stock is true
- **THEN** claim materializes a Sandbox from the selected SandboxSet and asks the component backend
  to create it under the existing limiter and error rules

#### Scenario: Context is canceled
- **WHEN** cancellation occurs while waiting for a worker, limiter, candidate, readiness, or retry
- **THEN** the operation stops through the existing cancellation path and releases acquired resources

### Requirement: Admission acquire and release remain paired
Admission SHALL remain an optional provider callback. Each retry requiring admission SHALL use the
approved lock identity, acquire before the Sandbox write, retain admission after a successful claim,
and release it on the existing rejected-write or failed-cleanup paths with the existing bounded
release context.

#### Scenario: Admission rejects a candidate
- **WHEN** admission acquire returns an error
- **THEN** no Sandbox write occurs and the error follows the existing retry classification

#### Scenario: Kubernetes write is rejected
- **WHEN** admission succeeds but the create or update is conclusively rejected
- **THEN** the matching admission is released exactly once

#### Scenario: Claim succeeds
- **WHEN** the Sandbox is locked and all post-processing succeeds
- **THEN** admission remains held for the caller's live Sandbox accounting

### Requirement: Claim mutation and post-processing remain equivalent
The shared orchestration and component backend SHALL preserve owner/lock metadata, claim time,
user metadata tracking,
in-place image/resource update, runtime configuration, runtime initialization, identity token
processing, CSI annotation and mounts, readiness waits, and their existing ordering.

#### Scenario: Runtime and CSI are requested
- **WHEN** resolved options request both operations
- **THEN** shared orchestration invokes backend runtime initialization and identity processing before
  backend CSI mounts using the existing ordering and error behavior

#### Scenario: User metadata is applied
- **WHEN** labels or annotations are added during claim
- **THEN** the CR records the same metadata and cleanup ownership information as before extraction

#### Scenario: In-place resources are requested
- **WHEN** valid request or limit updates are supplied
- **THEN** the first workload container receives the same supported resource changes as before

### Requirement: Failed claim cleanup remains equivalent
Failed claims SHALL direct the component backend to retain, delay-delete, or immediately delete
their Sandbox according to the resolved retention option. Cleanup SHALL preserve the reserved-failed
marker, shutdown deadline, fallback deletion, admission release, timeout, and NotFound handling.

#### Scenario: Failed Sandbox is reserved forever
- **WHEN** retention selects forever
- **THEN** the Sandbox receives the reserved-failed marker without replacing an existing earlier
  shutdown upper bound

#### Scenario: Failed Sandbox is retained temporarily
- **WHEN** retention is a positive duration
- **THEN** the Sandbox is marked reserved and receives the corresponding shutdown deadline

#### Scenario: Reservation write fails
- **WHEN** the provider cannot persist failed-Sandbox reservation
- **THEN** it attempts the existing fallback deletion and releases admission only when removal is
  confirmed or already complete

### Requirement: Errors and policy are mapped at caller boundaries
The CR provider SHALL return provider or Kubernetes errors and MUST NOT import Manager domain errors,
web errors, E2B models, authorization, or quota policy. Manager and controller SHALL preserve their
existing caller-specific error mapping and reconciliation behavior.

Concrete Kubernetes clients, cache reads, CR writes, waits, runtime/CSI calls, identity operations,
and cleanup persistence SHALL be implemented inside Manager infra/sandboxcr on the Manager path and
inside the SandboxClaim Controller adapter on the Controller path.

#### Scenario: No Sandbox is available
- **WHEN** shared claim exhausts eligible candidates and creation is disabled or impossible
- **THEN** it returns the provider no-availability error and each caller applies its existing mapping

#### Scenario: Kubernetes rejects a write
- **WHEN** create or update returns a terminal Kubernetes error
- **THEN** the provider preserves its cause and the caller maps it without string or type assertion

#### Scenario: Quota is enforced
- **WHEN** Manager claim requires quota admission
- **THEN** Manager supplies admission callbacks and the provider remains unaware of quota policy or
  public API error codes

### Requirement: Claim metrics preserve meaning
Provider-owned claim metrics SHALL preserve retries, total and phase durations, lock type, final
error, and aggregated candidate failures. Moving the type MUST NOT change when a metric is recorded
or how repeated candidate failures are grouped.

#### Scenario: Candidate fails repeatedly
- **WHEN** retries fail for the same candidate and normalized reason
- **THEN** the failure record count is aggregated exactly as before extraction

#### Scenario: Claim completes
- **WHEN** claim returns success or failure
- **THEN** timing fields, retries, lock classification, and final error describe the same execution
  stages as before
