---
name: complete-workitem
description: Verify a work item's declared delivery, update dependent readiness, and track optional worktree cleanup only inside a managed project workspace. Use after code merge, release, or another declared delivery outcome. Does not equate implementation or review success with delivery, and does not operate outside a managed project.
---

# Complete Work Item

Read [project context](../manage-workitems/references/project-context.md) and [workflow](../manage-workitems/references/workflow.md). Query only the current item and affected dependents; load additional delivery evidence as needed.

Default delivery is inclusion of the actual development work in the configured remote trunk. Verify the source identity, target and inclusion; a local merge or source-branch push is insufficient. Honor extra release/deployment obligations recorded in `delivery.required`, and distinguish merged code, built artifacts and deployed behavior. Record concrete, accessible evidence for each obligation.

When all obligations are met, set delivery to `delivered` and the item to `done`; retain cleanup separately. User-declared acceptance or verification is delivery evidence, not delivery: when the user asks to mark an item complete but a `delivery.required` obligation (merge, release, deployment) is still unmet, record the acceptance evidence, keep the item at `awaiting_delivery`, and wait for the actual delivery trigger rather than forcing `done`. Synchronize all configured backends and publish the checkpoint before treating downstream readiness as durable. A delivered-but-cancelled item does not automatically satisfy a dependency. Aggregate completion also requires the agreed coverage of the original requirement; completed prerequisites alone do not prove an omitted acceptance criterion.

Delivery unlocks dependent items for formal design review and subsequent implementation. Pending worktree cleanup does not block them. Update the affected aggregate/dependent records through the shared publication path with current byte preconditions; do not overwrite an item owned by another writer. An authorized later checkpoint may complete a roll-up that could not be written now.

Run `cleanup-worktree` only for requested cleanup and preserve its exact-manifest approval and safety gates. Resolve the item's recorded worktree against the configured base; include main-workspace locations in the exact manifest while preserving shared roots, environments and sibling worktrees. Cleanup evidence is separate from delivery evidence: verify non-ignored files are committed and pushed, the worktree is clean, and the recorded state is recoverable from retained remote refs. Delivery or PR/MR status does not determine cleanup eligibility. Set `cleanup: done` only after actual removal is verified; failed cleanup leaves the successful delivery intact.

For an aggregate without a worktree use `cleanup: not_applicable`. For a cancelled or unfinished development, requested cleanup uses the same cleanliness, remote-recovery and authorization gates; retain its actual delivery status.
