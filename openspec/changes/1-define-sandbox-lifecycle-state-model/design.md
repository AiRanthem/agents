## Context

`pkg/utils.GetSandboxState` currently returns only `creating`, `available`, `running`, `paused`, or `dead`. Its inputs already contain enough information for a richer derived view: phase, Ready and operation conditions, `spec.paused`, shutdown time, cleanup annotations, claim label, Pod IP, and deletion timestamp.

Two persistent conditions require exact gates. `InplaceUpdate` and `Upgrading` retain `Succeeded` after the operation, and `SandboxResumed` remains after resume until the next pause. Treating condition presence as active progress would therefore misclassify healthy Sandboxes forever.

The current in-place Controller writes one `Failed` reason at materially different stages:

- a QoS or capability rejection before any Pod mutation;
- an API mutation failure whose effect may be partial or uncertain;
- a kubelet convergence failure after the target Pod mutation was submitted.

Those outcomes cannot share one availability policy. The current `InPlaceUpdateControl.Update` result `(changed bool, err error)` also cannot report whether resource resize was accepted before a later image/metadata patch failed. This first change therefore establishes both the source facts and a pure model without activating it through the legacy wrapper. The follow-up infrastructure change is the first production route consumer of the model, but it activates through the neutral `Projector` and ObjectKey/UID/resourceVersion-fenced Store defined by `docs/specs/2026-07-10-short-sandbox-id-design.md`, never through legacy `GetRouteFromSandbox`. The final adoption change switches all other consumers atomically.

## Goals / Non-Goals

**Goals:**

- Define exactly one internal lifecycle state for every Sandbox CR observation.
- Make lifecycle derivation pure for an explicit `now` and independent from callers.
- Make in-place update failure stage an explicit Controller-owned contract.
- Preserve an actually healthy old workload after a proven pre-mutation failure.
- Exclude persistent success conditions from active resume and upgrade classification.
- Provide exhaustive tests before any consumer cutover.
- Make mutation-stage evidence explicit instead of inferring it from an error string or broad error wrapper.

**Non-Goals:**

- Switching `pkg/utils.GetSandboxState` or migrating SandboxSet, cache, manager, route, or E2B consumers.
- Adding a persisted lifecycle field or changing the CRD schema.
- Redesigning recreate-upgrade phases, retry backoff, or Pod update mechanics.
- Treating condition-level operation failure as global Sandbox `failed`.
- Changing quota liveness or public E2B state and error behavior.
- Choosing Sandbox IDs, constructing Routes, changing Store/peer freshness semantics, or owning route feeders and repair; those seams belong to the approved short-ID design.

## Decisions

### 1. Extend the existing pure lifecycle boundary without activating the legacy wrapper

The canonical function lives in the existing `pkg/utils/lifecycle` package, depends only on API types, accepts `now time.Time` explicitly, and returns a concrete state plus a non-empty diagnostic reason. The package already owns shared Sandbox lifecycle predicates; its `AGENTS.md` is extended so pure CRD normalization is an explicit responsibility. It does not read a clock, cache, route table, feature gate, or external system.

The fixed typed vocabulary is owned by `pkg/utils/lifecycle` rather than added to the CRD API package:

`creating`, `available`, `running`, `pausing`, `paused`, `resuming`, `upgrading`, `recycling`, `terminating`, `succeeded`, and `failed`.

There is no `unknown` result. Empty and unsupported phases conservatively map to `creating` with distinct diagnostics. Every declared `SandboxPhase` constant is covered by a maintenance test. The five existing `api/v1alpha1.SandboxState*` string constants remain temporarily for the legacy wrapper and callers; no new derived-state vocabulary is added to the serialized API package. Existing `dead` remains available for later peer-wire compatibility but is never returned by the canonical function. The short-ID route foundation owns the full/ID-only peer payload and conditional-delete state machine; lifecycle code later supplies `dead` only as a copy-only outgoing compatibility state.

`pkg/utils.GetSandboxState` remains behaviorally unchanged in this part. Tests invoke the canonical function directly. This makes the foundation independently deployable and prevents partial consumer migration.

### 2. Apply deterministic first-match precedence

Ready means `SandboxConditionReady=True`. A routable address means `status.podInfo.podIP` is non-empty. The first matching row wins:

| Priority | State | Facts |
|---|---|---|
| 1 | `terminating` | deletion timestamp is set, shutdown time is at or before `now`, or phase is `Terminating` |
| 2 | `succeeded` | phase is `Succeeded` |
| 3 | `failed` | phase is `Failed` |
| 4 | `recycling` | phase is `Recycling`, or both `AnnotationCleanup` and `AnnotationCleanupEnabled` equal `True` |
| 5 | `pausing` | phase is `Running` with `spec.paused=true`, or phase is `Paused` before the Paused condition is true |
| 6 | `paused` | phase is `Paused`, `spec.paused=true`, and the Paused condition is true |
| 7 | `resuming` | phase is `Resuming`; or a completed pause has `spec.paused=false`; or the exact post-resume initialization gate matches |
| 8 | `upgrading` | phase is `Upgrading`, or an exact active/unsafe in-place reason matches while phase is `Running` |
| 9 | `available` | an unclaimed SandboxSet member is `Running`, Ready, and has a Pod IP |
| 10 | `running` | a claimed or standalone Sandbox is `Running`, Ready, and has a Pod IP |
| 11 | `creating` | empty, Pending, unsupported, or otherwise not yet usable |

Claim identity comes from `agents.kruise.io/sandbox-claimed=true`. A SandboxSet-controlled object lacking that label is pool-eligible; other objects use the claimed-or-standalone serving rule.

Deletion and shutdown override terminal phases. Pause precedes resume and update signals because the Controller handles a pause request before update work. Post-resume initialization precedes in-place update because initialization gates later work.

### 3. Make post-resume classification require both companion conditions

A `Running` Sandbox is `resuming` after resume only when all of these facts hold:

- `SandboxResumed` exists with `Status=True`;
- `RuntimeInitialized` exists;
- `RuntimeInitialized.Status != True`.

An absent `RuntimeInitialized` condition does not imply resume progress. The object falls through to Ready and Pod-IP evaluation, which keeps legacy CRs from becoming permanently `resuming`. `RuntimeInitialized=False/Pending` and `False/Failed` remain `resuming` and non-serving because runtime initialization is incomplete.

An explicit `Resuming` phase always maps to `resuming`. A completed Paused observation with `spec.paused=false` also maps to `resuming`.

### 4. Split in-place update failure by mutation stage

The `InplaceUpdate` condition uses these exact reasons:

| Reason | Meaning | Terminal for the current attempt | Availability effect |
|---|---|---:|---|
| `InplaceUpdating` | update is active | no | `upgrading` |
| `PreUpdateFailed` | Controller proved no Pod mutation occurred | yes | fall through to Ready and Pod-IP evaluation |
| `UpdatePodFailed` | Pod mutation failed with partial or uncertain effect | no; reconcile retries | `upgrading` |
| `PostUpdateFailed` | mutation was submitted but kubelet convergence failed | yes | `upgrading` |
| `Succeeded` | update completed | yes | does not trigger `upgrading` |
| legacy `Failed` | stage is unknown on an older CR | yes | conservatively `upgrading` |

New Controller code never writes legacy `Failed`. An undeclared reason or unsupported status/reason combination conservatively derives `upgrading` with a diagnostic. Only exact `PreUpdateFailed` and `Succeeded` outcomes fall through to Ready and Pod-IP evaluation. Declared-reason coverage forces deliberate support for future constants.

The Controller writes `PreUpdateFailed` only when non-mutation is proven. The QoS precheck runs before Ready is changed and is inherently pre-mutation. For update execution, the result must explicitly prove that no Pod write was accepted, for example a missing resize subresource followed by a deterministic fallback-patch rejection before write acceptance. The existing `ResizeNotSupportedError` wrapper alone is not sufficient evidence because it currently wraps broad fallback patch failures, including outcomes whose write acceptance may be uncertain.

`InPlaceUpdateControl.Update` is refactored to return an explicit mutation outcome in addition to changed/error information. If resource resize succeeded and the later image/metadata patch failed, or if any API response leaves write acceptance uncertain, the Controller writes retryable `UpdatePodFailed`. The Controller leaves Ready false and retries. A terminal error returned while checking an already-submitted update, such as resize Infeasible, Deferred, or Error, uses `PostUpdateFailed` and remains non-serving.

The current handler sets Ready false before calling `Update`. Consequently, every execution path classified as `PreUpdateFailed` after that point must re-read the current Pod readiness and synchronize the Sandbox Ready condition from the Pod before status is persisted. It may restore Ready true only when the observed Pod is actually Ready; otherwise the canonical state falls through to `creating`. This requirement does not apply to the earlier QoS precheck because Ready has not yet been cleared there.

This three-stage contract is preferred over inspecting error-message text in the lifecycle function. The Controller knows the mutation point; downstream consumers should use its explicit reason.

### 5. Recreate upgrade is phase-gated

`status.phase=Upgrading` always derives `upgrading`, including `PreUpgradeFailed`, `UpgradePodFailed`, and `PostUpgradeFailed` while that phase persists.

When phase is `Running`, the persistent `Upgrading` condition does not independently trigger upgrade state. In particular, `Upgrading=True, Reason=Succeeded` is ignored. This prevents every successfully recreate-upgraded Sandbox from remaining unavailable.

### 6. Keep global failure phase-based

Only `status.phase=Failed` derives global `failed`. `StartContainerFailed` remains `creating` with its diagnostic preserved. Recreate step failures remain `upgrading` while phase is `Upgrading`. Recycling failures remain `recycling` while phase is `Recycling`.

This separates workload lifecycle from operation outcome and leaves waiters free to fail fast using diagnostic reasons after the final adoption change.

## Risks / Trade-offs

- **[Risk] A failure is incorrectly labeled pre-mutation and serves a partially changed Pod.** -> Allow `PreUpdateFailed` only for explicit validation or typed errors that prove no mutation; treat every uncertain case as `UpdatePodFailed`.
- **[Risk] Resource resize succeeds but a later metadata/image patch fails.** -> Return an explicit mutation outcome from `Update`; classify this path as `UpdatePodFailed` rather than relying on its single returned error.
- **[Risk] A proven pre-mutation failure is still unavailable because Ready was cleared before `Update`.** -> Re-synchronize Ready from the current Pod on the post-clear `PreUpdateFailed` path and test Ready true, false, and absent observations.
- **[Risk] Historical `Failed` conditions cannot reveal their stage.** -> Interpret them conservatively as non-serving `upgrading`.
- **[Risk] New reason values persist across a rollback to an older Controller.** -> No schema migration is required, but Controller rollback may re-evaluate an unrecognized reason; document this operational limitation and keep messages diagnostic.
- **[Risk] The new function drifts before activation.** -> Cover every declared phase, condition reason, precedence conflict, and time boundary directly. Part 2 MUST NOT supply the function's result to short-ID `ProjectionInput.State` until this exhaustive suite passes.
- **[Risk] Part 2 is implemented against legacy route code and later replaced by short-ID.** -> Make the short-ID routing/cache/infra foundation an independent hard prerequisite; Part 1 contains no route implementation and supports no temporary `GetRouteFromSandbox` activation.
- **[Trade-off] Unsupported phases appear as `creating`.** -> This avoids false terminal behavior while the diagnostic and declared-phase coverage expose the missing mapping.

## Migration Plan

1. Add the architecture proposal, lifecycle vocabulary, and Controller reason contract.
2. Refactor the in-place update result to expose mutation stage, then update Controller handling and focused table-driven tests, including Ready re-synchronization for proven pre-mutation failure.
3. Extend the existing pure lifecycle package, its guidance, declared-phase invariant documentation, and exhaustive tests.
4. Keep `pkg/utils.GetSandboxState` and all production consumers on the existing five-state implementation.
5. Require all Part 1 lifecycle and Controller tests to pass before implementing or deploying the route activation in `2-prepare-sandbox-lifecycle-infrastructure`; independently verify that the approved short-ID Projector/Store/Repairer and feeder ownership are present before that activation.

Rollback requires no CRD or stored-data migration. New condition reasons may remain on CRs and are preserved as diagnostic strings; an older Controller may re-evaluate them as described in Risks.

## Open Questions

None. The vocabulary, precedence, failure-stage contract, resume gate, upgrade gate, short-ID-neutrality boundary, and activation gates are fixed.
