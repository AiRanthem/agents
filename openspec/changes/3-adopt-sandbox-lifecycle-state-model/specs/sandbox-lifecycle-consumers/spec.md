## ADDED Requirements

### Requirement: Manager-path lifecycle semantics stop at the infra boundary
Sandboxcr SHALL translate Sandbox CR phase, conditions, claim/cleanup metadata, and Controller reasons into the normalized infra lifecycle/owner/capability contract. Sandbox-manager and E2B lifecycle decisions SHALL consume that contract and MUST NOT reconstruct Kubernetes lifecycle semantics or use route presence/owner as a substitute. The approved short-ID boundary SHALL remain separate: manager/Gateway adapters supply neutral projection input to `pkg/sandboxroute`, while infra exposes neither Sandbox ID nor Route selection.

#### Scenario: Manager gets lifecycle and owner
- **WHEN** Sandbox-manager authorizes or orchestrates an operation for a claimed Sandbox
- **THEN** it uses infra lifecycle, owner, and capability accessors without reading raw phase, conditions, or ownership annotations

#### Scenario: E2B applies HTTP policy
- **WHEN** E2B projects state or maps an unavailable Sandbox to an HTTP response
- **THEN** it uses normalized infra state and diagnostic reason without importing CRD lifecycle constants or inspecting Controller conditions

#### Scenario: Recycle decision preserves behavior below the boundary
- **WHEN** Sandbox-manager deletes a cleanup-enabled Sandbox whose current CR facts satisfy the existing recycle gate
- **THEN** it uses infra recycle eligibility rather than the raw `Phase()` and split annotation check

#### Scenario: Controller dependency remains one-way
- **WHEN** consumer migration is complete
- **THEN** Controller, cache lifecycle, and canonical lifecycle packages do not import infra, Sandbox-manager, web, or E2B packages

#### Scenario: Short-ID infra boundary remains intact
- **WHEN** tuple state and raw phase compatibility methods are removed
- **THEN** `GetSandboxID()` and `GetRoute()` remain absent, ID resolution remains above infra, and the manager feeder continues supplying normalized state through the neutral Projector

#### Scenario: Routing dependency remains separate
- **WHEN** canonical lifecycle state is stored in a Route
- **THEN** component adapters choose lifecycle disposition and `pkg/sandboxroute` remains unaware of CRD conditions, lifecycle precedence, infra, Sandbox-manager policy, and E2B policy

### Requirement: All state consumers use the canonical lifecycle boundary
The compatibility state helper and every Sandbox state consumer SHALL use the canonical lifecycle derivation. Local CR observations MUST NOT derive legacy `dead`, and consumers MUST explicitly handle all eleven internal states without independently reconstructing resume or upgrade progress.

#### Scenario: Compatibility wrapper delegates
- **WHEN** a caller invokes `pkg/utils.GetSandboxState` after the adoption change
- **THEN** it returns the canonical lifecycle state using the wrapper-supplied observation time

#### Scenario: Transitional state is not dead
- **WHEN** a claimed Running Sandbox is unready or is pausing, resuming, or upgrading
- **THEN** each consumer receives the applicable converging state rather than `dead`

#### Scenario: Legacy dead remains wire-only
- **WHEN** local state is derived from a Sandbox CR
- **THEN** `dead` is never returned and is used only on a copied peer deletion payload handled by short-ID's full/ID-only conditional Store APIs

### Requirement: Pool grouping follows lifecycle and claim identity
SandboxSet grouping and pool indexes SHALL evaluate `agents.kruise.io/sandbox-claimed=true` separately from lifecycle state. Only unclaimed SandboxSet-controlled `creating` and `available` objects SHALL contribute pool capacity.

#### Scenario: Unclaimed creation is pool capacity
- **WHEN** an unclaimed SandboxSet-controlled Sandbox is `creating`
- **THEN** it is eligible for the speculative pool index and capacity group

#### Scenario: Unclaimed ready member is available
- **WHEN** an unclaimed SandboxSet-controlled Sandbox is `available`
- **THEN** it is eligible for the available pool index and capacity group

#### Scenario: Claimed creation is used
- **WHEN** a Sandbox has the claimed label and state `creating`
- **THEN** SandboxSet classifies it as used and the pool index excludes it

#### Scenario: Terminal states enter garbage collection
- **WHEN** a SandboxSet member is `terminating`, `succeeded`, or `failed`
- **THEN** it enters the existing Dead garbage-collection group without duplicate deletion of an already-deleting object

#### Scenario: Recycling is not pool capacity or terminal
- **WHEN** a SandboxSet member is `recycling`
- **THEN** it enters the explicit ignored/non-capacity group and is excluded from pool indexes and terminal garbage collection

#### Scenario: Future unexpected state does not abort reconciliation
- **WHEN** SandboxSet grouping receives a state outside the vocabulary handled by its current exhaustive switch
- **THEN** it logs state and diagnostic reason, places the object in the ignored/non-capacity group, and does not return an error for the whole reconcile

### Requirement: Active claimed accounting remains distinct from quota
`CountActiveSandboxes` SHALL require the claimed label, exclude reserved-failed objects, and count exactly `creating`, `running`, `pausing`, `paused`, `resuming`, and `upgrading`. `IsLiveForQuota` MUST retain its independent policy.

#### Scenario: Claimed converging state is active
- **WHEN** a non-reserved claimed Sandbox is in any of the six active/converging states
- **THEN** active claimed accounting includes it

#### Scenario: Unclaimed pool member is not active claim
- **WHEN** a SandboxSet-controlled Sandbox lacks the claimed label even if it is `creating` or `available`
- **THEN** active claimed accounting excludes it

#### Scenario: Recycling and terminal states are not active
- **WHEN** a claimed Sandbox is `recycling`, `terminating`, `succeeded`, or `failed`
- **THEN** active claimed accounting excludes it

#### Scenario: Claim recovery uses claimed-only actual count
- **WHEN** SandboxClaim self-healing compares status count with actual active count
- **THEN** actual count uses the claimed-only state contract and recovery continues using the maximum of the two counts

#### Scenario: Claim owner and claimed label are committed together
- **WHEN** a claim create or update succeeds
- **THEN** the owner/lock metadata and `agents.kruise.io/sandbox-claimed=true` were written on the same Sandbox object in the same Kubernetes create/update operation

#### Scenario: Quota liveness does not use active count states
- **WHEN** API-key quota liveness is evaluated
- **THEN** the existing deletion, terminating, recycling, and cleanup policy is applied independently

### Requirement: Waiters preserve operation-specific outcomes
Lifecycle waiters SHALL use canonical state for convergence while preserving diagnostic-specific success, retry, and fast-failure behavior.

#### Scenario: Startup failure still fails fast
- **WHEN** lifecycle state is `creating` and the diagnostic identifies `StartContainerFailed`
- **THEN** the applicable readiness waiter returns its existing fast failure instead of retrying indefinitely

#### Scenario: Ordinary creation keeps waiting
- **WHEN** lifecycle state is `creating` without an operation-specific terminal diagnostic
- **THEN** the readiness waiter continues according to its existing timeout and retry policy

#### Scenario: Upgrade convergence remains explicit
- **WHEN** lifecycle state is `upgrading`
- **THEN** update/claim waiters apply the Controller condition's retry or terminal outcome rather than treating the Sandbox as absent
