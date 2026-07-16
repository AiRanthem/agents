## 1. Architecture and API Contract

- [ ] 1.1 Add `docs/proposals/20260715-sandbox-lifecycle-state-model.md` describing the three-change rollout, state precedence, failure-stage contract, opaque lookup boundary, short-ID Projector/Store/Repairer prerequisite, component route policy, consumer cutover, and accepted residual risks.
- [ ] 1.2 Add the typed eleven-state internal vocabulary to `pkg/utils/lifecycle`; retain the existing five `api/v1alpha1.SandboxState*` strings temporarily for legacy callers and `dead` peer compatibility; add only `PreUpdateFailed`, `UpdatePodFailed`, and `PostUpdateFailed` serialized condition-reason constants to `api/v1alpha1`.
- [ ] 1.3 Run `make generate manifests` after the `api/v1alpha1` edits and verify that no serialized lifecycle field or unintended CRD schema change is introduced.

## 2. Controller Failure-Stage Signals

- [ ] 2.1 Refactor `InPlaceUpdateControl.Update` so its result records whether no Pod write was accepted, a resize/patch may have been accepted, or mutation was submitted; do not infer stage from error-message text or the broad existing `ResizeNotSupportedError` wrapper alone.
- [ ] 2.2 Map QoS validation and update outcomes that definitively prove no accepted Pod write to `PreUpdateFailed`; when Ready was already cleared, re-read the Pod and synchronize Ready from its actual condition without forcing it true.
- [ ] 2.3 Map uncertain or potentially partial Pod mutation errors, including resize success followed by image/metadata patch failure, to retryable `UpdatePodFailed`, leaving Ready false and preserving the reconcile error.
- [ ] 2.4 Map terminal kubelet convergence errors after target mutation to `PostUpdateFailed`; keep reading legacy `Failed` as a terminal ambiguous outcome and stop writing it in new Controller paths.
- [ ] 2.5 Add or refactor focused table-driven Controller tests covering all three stages, resize-success/metadata-patch-failure, definite versus uncertain fallback errors, Ready true/false/absent re-synchronization, retry/terminal classification, legacy `Failed`, `Succeeded` persistence, and error messages using `expectError string`.

## 3. Pure Lifecycle Model

- [ ] 3.1 Implement the explicit-time, side-effect-free derivation under `pkg/utils/lifecycle` with the approved precedence and exact annotation, resume, in-place update, and recreate-upgrade gates.
- [ ] 3.2 Add lifecycle predicates needed by later changes without importing cache, manager, server, route, or controller policy into the package.
- [ ] 3.3 Extend the existing `pkg/utils/lifecycle/AGENTS.md` so pure CRD lifecycle normalization, exhaustive state handling, and declared-phase/reason maintenance are explicit responsibilities; verify the existing sibling `CLAUDE.md` still contains only `@./AGENTS.md`.
- [ ] 3.4 Keep `pkg/utils.GetSandboxState` behavior unchanged and add a guard test proving this foundation does not activate the consumer cutover.
- [ ] 3.5 Add exhaustive table-driven lifecycle tests for every declared phase, empty and unsupported phases, all precedence conflicts, explicit-time boundaries, claim identity, Ready/Pod-IP combinations, persistent success conditions, all in-place failure reasons, and unsupported status/reason combinations.

## 4. Verification

- [ ] 4.1 Run focused Go tests only for changed packages under `pkg/`; do not run tests under `test/` and use a writable temporary `GOCACHE` if needed.
- [ ] 4.2 Run the repository-approved static checks for the changed Controller and lifecycle packages.
- [ ] 4.3 Re-run strict OpenSpec validation for this change, confirm no task activates production consumers, and record both passing Part 1 lifecycle/Controller tests and the independently implemented short-ID routing/cache/infra foundation as mandatory gates before Part 2 supplies canonical `ProjectionInput.State`.
