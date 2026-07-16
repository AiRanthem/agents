## Why

The current five-value Sandbox state helper collapses controller progress, normal completion, failure, and temporary unready observations into a small vocabulary dominated by `dead`. Before consumers can safely change behavior, the repository needs an explicit lifecycle contract and Controller signals that distinguish whether an in-place update failed before, during, or after Pod mutation.

## What Changes

- Add the internal lifecycle vocabulary `creating`, `available`, `running`, `pausing`, `paused`, `resuming`, `upgrading`, `recycling`, `terminating`, `succeeded`, and `failed`. Retain `dead` only as a deprecated compatibility value.
- Add a pure lifecycle derivation function with an explicit observation time, deterministic precedence, exhaustive declared-phase coverage, and no persisted CRD state field.
- Extend the Controller-owned `InplaceUpdate` condition reasons with `PreUpdateFailed`, `UpdatePodFailed`, and `PostUpdateFailed`. New Controller code stops writing the ambiguous `Failed` reason while continuing to interpret it conservatively on historical CRs.
- Refactor the in-place update result so the Controller can distinguish no accepted Pod write, an uncertain/partial mutation, and post-mutation convergence failure. Preserve traffic for a proven pre-mutation failure only after Ready is preserved or re-synchronized from the current Pod; keep uncertain, partial, and post-mutation failures non-serving.
- Define exact resume and upgrade gates so persistent `SandboxResumed`, `InplaceUpdate`, and `Upgrading` success conditions do not leave healthy Sandboxes in transitional states.
- Extend the existing `pkg/utils/lifecycle` package responsibility from shared predicates to CRD lifecycle normalization, and add exhaustive table-driven tests. Do not switch `pkg/utils.GetSandboxState` or any existing production consumer in this change.
- Make the exhaustive Part 1 test suite a release gate for Part 2, because Part 2 is the first change that places canonical derivation on the production route/data-plane decision path. Part 2 also independently requires the approved short-ID `Projector`/fenced-Store routing foundation; Part 1 does not create or modify competing route machinery.

## Capabilities

### New Capabilities

- `sandbox-lifecycle-state-model`: Controller failure-stage signals and the pure, exhaustive Sandbox lifecycle derivation contract.

### Modified Capabilities

None. This repository has no archived OpenSpec capability specifications.

## Impact

- `api/v1alpha1/sandbox_types.go` condition-reason constants and `pkg/utils/lifecycle` internal-state vocabulary; no new serialized status field.
- Sandbox Controller in-place update condition handling and readiness synchronization.
- The existing responsibility-specific lifecycle package under `pkg/utils/lifecycle`, including updates to its package guidance.
- Generated API artifacts as required by repository policy, lifecycle/controller unit tests, and `docs/proposals/20260715-sandbox-lifecycle-state-model.md`.
- This is part 1 of 3. `2-prepare-sandbox-lifecycle-infrastructure` depends on both this change's passing implementation and the routing/cache/infra foundation defined by `docs/specs/2026-07-10-short-sandbox-id-design.md`, followed by `3-adopt-sandbox-lifecycle-state-model`. Part 1 and short-ID may proceed independently; neither routes through the other.
