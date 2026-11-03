# Actual delivery and cleanup

Read the current requirement, design, acceptance and declared delivery obligations. Inspect actual source and external evidence, then update the item's existing records and metadata directly. Commit and push completed project updates under [persistence](../../manage-workitems/references/persistence.md). Source publication, deployment and cleanup require covering authorization.

Record each obligation with its actual evidence and result. Remote-trunk inclusion differs from source-branch publication, PR creation, build, release, deployment and end-to-end behavior. Report the observed fact and any unverified portion. Set the item's status from these facts; a project commit alone is not delivery.

## Human final drafts

During human acceptance, preserve the user's final code and design, including intentional behavior, interface and constraint changes. Record the actual final-edit source; file differences alone do not prove authorship or acceptance. Keep the work in acceptance/delivery unless the user requests a return to ordinary development.

Record an explicit acceptance conclusion for the actual current implementation. Reuse an existing conclusion that covers subsequent finalization, preserving its real source. Without a covering conclusion, report acceptance as pending. Keep independent review records attached to the targets actually reviewed; human acceptance must not be relabeled as an independent review.

Compare the accepted implementation with this item's current spec. Preserve user-finalized design text and align remaining outdated descriptions only where the user left them for reconciliation. Record the accepted code target, inspected scope, user source, intentional differences and remaining delivery obligations. This factual alignment needs no additional approval or independent review when covered by the user's acceptance. Downstream items retain their designs and assess relevant prerequisite changes in their own work.

A PR, tests or an AI pass do not establish human acceptance. For an aggregate, assess evidence against every original acceptance criterion. A defect or unfinished prerequisite affects the obligations that actually depend on it; retain the original delivery history and describe the outstanding work explicitly.

## Cleanup

Use [cleanup-worktree](../../cleanup-worktree/SKILL.md) for requested local source cleanup. Identify the actual item worktree and verify its exact authorization, cleanliness and remote recovery before removal. Preserve main-workspace roots, shared environments, repositories and sibling worktrees.

Record the actual removal result and retained recovery references directly in the project. Preserve requirement/design documents and source history. If the user discards an unfinished implementation, record that decision and its actual source rather than claiming successful implementation or delivery. Failed cleanup leaves completed delivery intact. Project removal and remote deletion retain their own scope.

Use [resource preservation](../../manage-workitems/references/resource-lifecycle.md) for snapshots, caches and replacement workspaces. Inventory actual resources and retain unique or unpublished work; acceptance does not itself authorize their removal.
