## ADDED Requirements

### Requirement: Exhaustive pure Sandbox lifecycle derivation
The system SHALL provide a lifecycle derivation that returns exactly one of `creating`, `available`, `running`, `pausing`, `paused`, `resuming`, `upgrading`, `recycling`, `terminating`, `succeeded`, or `failed` plus a non-empty diagnostic reason for every Sandbox CR observation. Derivation MUST use a supplied observation time and MUST NOT return legacy `dead` or an `unknown` state.

#### Scenario: All declared phases are covered
- **WHEN** a Sandbox uses any declared `SandboxPhase` value or an empty phase
- **THEN** derivation returns one concrete state and a non-empty diagnostic reason

#### Scenario: Unsupported phase is conservative
- **WHEN** a Sandbox contains a non-empty phase string that is not declared
- **THEN** derivation returns `creating` with a diagnostic that identifies the unsupported phase

#### Scenario: Derivation is time deterministic
- **WHEN** the same Sandbox and explicit observation time are evaluated repeatedly
- **THEN** the state and diagnostic are identical without reading a clock or external system

#### Scenario: Legacy wrapper is not activated by the foundation
- **WHEN** this foundation change is deployed before its adoption change
- **THEN** existing callers of `pkg/utils.GetSandboxState` retain the pre-existing five-state behavior

### Requirement: Lifecycle verification and short-ID routing gate route activation
The exhaustive lifecycle and Controller failure-stage test suites SHALL pass before the canonical derivation is placed on any production route or forwarding decision path in the infrastructure change. That activation SHALL also require the approved short-ID Projector, ObjectKey/UID/resourceVersion-fenced Store, conditional peer mutations, component-owned feeders, and targeted Repairer. It MUST NOT activate canonical state through legacy `GetRouteFromSandbox` or an independent registry.

#### Scenario: Part 1 verification fails
- **WHEN** any declared-phase, precedence, persistent-condition, mutation-stage, or Ready re-synchronization test fails
- **THEN** `2-prepare-sandbox-lifecycle-infrastructure` MUST NOT activate canonical route projection

#### Scenario: Short-ID routing foundation is not present
- **WHEN** Part 1 passes but the production path still uses legacy route projection, sandboxcr-owned periodic reconciliation, independent registries, or unconditional peer deletes
- **THEN** `2-prepare-sandbox-lifecycle-infrastructure` MUST NOT activate canonical route projection until the short-ID foundation is integrated

### Requirement: Terminal and recycling precedence
Termination, terminal phase, and recycling rules SHALL precede converging and serving rules. Deletion, shutdown expiry, and `Terminating` phase MUST take precedence over `Succeeded` and `Failed`.

#### Scenario: Deletion overrides completion
- **WHEN** a Sandbox has phase `Succeeded` or `Failed` and also has a deletion timestamp
- **THEN** its derived state is `terminating`

#### Scenario: Shutdown deadline is reached
- **WHEN** the observation time is equal to or later than `spec.shutdownTime`
- **THEN** its derived state is `terminating`

#### Scenario: Successful completion is distinct
- **WHEN** a non-deleting Sandbox has phase `Succeeded` and its shutdown deadline has not been reached
- **THEN** its derived state is `succeeded`

#### Scenario: Failed completion is phase based
- **WHEN** a non-deleting Sandbox has phase `Failed` and its shutdown deadline has not been reached
- **THEN** its derived state is `failed`

#### Scenario: Accepted recycle request precedes phase update
- **WHEN** both `AnnotationCleanup` and `AnnotationCleanupEnabled` equal `True` before phase changes to `Recycling`
- **THEN** its derived state is `recycling`

### Requirement: Pause and resume progress is explicit
The system SHALL distinguish `pausing`, `paused`, and `resuming` using phase, `spec.paused`, the Paused condition, the Resumed condition, and runtime initialization.

#### Scenario: Pause requested from Running
- **WHEN** phase is `Running` and `spec.paused=true` without a higher-priority rule
- **THEN** the derived state is `pausing`

#### Scenario: Pause has not completed
- **WHEN** phase is `Paused` and the Paused condition is absent or not true
- **THEN** the derived state is `pausing`

#### Scenario: Pause is complete
- **WHEN** phase is `Paused`, `spec.paused=true`, and the Paused condition is true
- **THEN** the derived state is `paused`

#### Scenario: Resume requested after completed pause
- **WHEN** phase is `Paused`, the Paused condition is true, and `spec.paused=false`
- **THEN** the derived state is `resuming`

#### Scenario: Resume phase is explicit
- **WHEN** phase is `Resuming`
- **THEN** the derived state is `resuming`

#### Scenario: Post-resume initialization is incomplete
- **WHEN** phase is `Running`, `SandboxResumed=True`, and an existing `RuntimeInitialized` condition has status other than True
- **THEN** the derived state is `resuming`

#### Scenario: Missing runtime initialization condition is not resume progress
- **WHEN** phase is `Running` and `SandboxResumed=True` but `RuntimeInitialized` is absent
- **THEN** the Sandbox falls through to Ready and Pod-IP evaluation instead of deriving `resuming`

### Requirement: Serving and pool availability require readiness and address
The system SHALL require Ready true and a non-empty `status.podInfo.podIP` for `running` or `available`. An unclaimed SandboxSet member SHALL use `available`; a claimed or standalone Sandbox SHALL use `running`.

#### Scenario: Claimed Sandbox is serving
- **WHEN** a claimed or standalone Sandbox is in phase `Running`, Ready is true, Pod IP is non-empty, and no higher-priority rule matches
- **THEN** its derived state is `running`

#### Scenario: Pool Sandbox is available
- **WHEN** an unclaimed SandboxSet-controlled Sandbox is in phase `Running`, Ready is true, and Pod IP is non-empty
- **THEN** its derived state is `available`

#### Scenario: Running phase is not usable
- **WHEN** phase is `Running` but Ready is not true or Pod IP is empty and no transition-specific rule matches
- **THEN** its derived state is `creating`

### Requirement: In-place update stage controls availability
The Controller-owned `InplaceUpdate` condition SHALL report failures that enter the in-place lifecycle as `PreUpdateFailed`, `UpdatePodFailed`, or `PostUpdateFailed` according to the proven mutation stage. In-place update execution SHALL expose whether no Pod write was accepted, a mutation may have been accepted, or mutation was submitted and convergence later failed. New Controller code MUST NOT write legacy `Failed`. Lifecycle derivation SHALL use exact declared reasons, SHALL interpret historical `Failed` conservatively, and SHALL treat unsupported status/reason combinations as unsafe to serve.

#### Scenario: Proven pre-mutation failure preserves a healthy workload
- **WHEN** phase is `Running`, `InplaceUpdate=False/PreUpdateFailed`, Ready is true, and Pod IP is non-empty
- **THEN** the derived state is `running` and the Controller preserves or re-synchronizes Ready from the current Pod

#### Scenario: Ready was cleared before a proven pre-mutation failure
- **WHEN** the handler cleared Sandbox Ready before executing the update, execution proves no Pod write was accepted, and the current Pod Ready condition is true
- **THEN** the Controller writes `PreUpdateFailed` and re-synchronizes Sandbox Ready to true from that Pod observation before persisting status

#### Scenario: Pre-mutation re-synchronization does not force readiness
- **WHEN** execution proves no Pod write was accepted but the current Pod Ready condition is false or absent
- **THEN** the Controller writes `PreUpdateFailed` without forcing Sandbox Ready true and lifecycle derives `creating`

#### Scenario: Missing resize subresource and deterministic fallback rejection
- **WHEN** the resize subresource returns NotFound and the fallback resource patch is definitively rejected before write acceptance
- **THEN** the update outcome may be classified as no-mutation and the Controller writes `PreUpdateFailed`

#### Scenario: Broad resize wrapper is not sufficient evidence
- **WHEN** a fallback resource patch error is wrapped as resize-not-supported but the API outcome does not prove that no write was accepted
- **THEN** the Controller MUST NOT classify it as `PreUpdateFailed` and uses `UpdatePodFailed`

#### Scenario: Pre-mutation failure does not hide independent unready state
- **WHEN** phase is `Running` and `InplaceUpdate=False/PreUpdateFailed` but Ready is not true or Pod IP is empty
- **THEN** the derived state is `creating`

#### Scenario: Mutation failure is unsafe to serve
- **WHEN** phase is `Running` and `InplaceUpdate=False/UpdatePodFailed`
- **THEN** the derived state is `upgrading` and Controller reconciliation retries the mutation

#### Scenario: Resize succeeds before metadata patch fails
- **WHEN** resource resize was accepted and the subsequent image or metadata patch fails
- **THEN** the explicit update outcome records possible or actual mutation and the Controller writes `UpdatePodFailed`

#### Scenario: Mutation acceptance is uncertain
- **WHEN** any Pod update API response leaves it uncertain whether the write was accepted
- **THEN** the Controller writes retryable `UpdatePodFailed` rather than `PreUpdateFailed`

#### Scenario: Post-mutation convergence failure is unsafe to serve
- **WHEN** phase is `Running` and `InplaceUpdate=False/PostUpdateFailed`
- **THEN** the derived state is `upgrading` and the observed attempt is terminal pending remediation

#### Scenario: Historical ambiguous failure is conservative
- **WHEN** phase is `Running` and `InplaceUpdate=False/Failed`
- **THEN** the derived state is `upgrading`

#### Scenario: In-place success is not active progress
- **WHEN** phase is `Running` and `InplaceUpdate=True/Succeeded`
- **THEN** the condition does not trigger `upgrading` and Ready plus Pod IP determine the state

#### Scenario: Unsupported in-place reason is conservative
- **WHEN** phase is `Running` and the InplaceUpdate condition has an undeclared reason or unsupported status/reason combination
- **THEN** the derived state is `upgrading` with a diagnostic identifying the unsupported condition

### Requirement: Recreate upgrade is phase-gated
Phase `Upgrading` SHALL derive `upgrading` regardless of its current upgrade-step reason. A persisted Upgrading condition SHALL NOT independently trigger `upgrading` after phase returns to `Running`.

#### Scenario: Recreate upgrade step is active
- **WHEN** phase is `Upgrading` with reason `PreUpgrade`, `UpgradePod`, or `PostUpgrade`
- **THEN** the derived state is `upgrading`

#### Scenario: Recreate upgrade step failed
- **WHEN** phase is `Upgrading` with reason `PreUpgradeFailed`, `UpgradePodFailed`, or `PostUpgradeFailed`
- **THEN** the derived state is `upgrading` and not global `failed`

#### Scenario: Persistent recreate success is ignored
- **WHEN** phase is `Running` and the Upgrading condition remains `True/Succeeded`
- **THEN** the condition does not trigger `upgrading` and Ready plus Pod IP determine the state

### Requirement: Operation outcomes do not imply global failure
The system MUST derive global `failed` only from `status.phase=Failed`. Startup and recycling operation outcomes SHALL remain in their applicable lifecycle state with diagnostic context.

#### Scenario: Container startup failure remains creation outcome
- **WHEN** phase is `Running`, Ready is false, and Ready reason is `StartContainerFailed`
- **THEN** the derived state is `creating` and the diagnostic preserves the startup failure

#### Scenario: Recycling failure remains recycling
- **WHEN** phase is `Recycling` and the Recycling condition reports failure or timeout
- **THEN** the derived state is `recycling` and not global `failed`
