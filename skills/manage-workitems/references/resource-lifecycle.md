# Source generations and internal resource lifecycle

The typed lifecycle workflow below governs ordinary operations. For script blockers or defects, use the separate [user-authorized manual recovery](recovery.md#user-authorized-manual-recovery) contract.

Use the typed `project.py lifecycle` commands in [commands](commands.md). The program owns generation identity, resource relationships, exact manifests, repository inspection and publication. Lifecycle policy is explicit authorization for preservation-ref publication and collection of registered internal resources. Ordinary development/PR/release refs retain their separate submission and cleanup boundaries.

## Approval and execution mode

The design author completes the shared [approval handoff](../../advance-project/references/discussion-and-authorization.md#design-approval-handoff) before formal spec publication; publication records its approval binding so the versioned spec can enter an authorized independent review. `show.workflow_gates` distinguishes independent review and implementation gates. A successful query or published draft does not establish implementation eligibility.

Any local session may continue these operations from existing artifacts and operation records within their user authorization and actual permissions. Use `lifecycle handoff` for an authorized manual/autonomous mode change: retain contract, source, reviews and recovery evidence, archive current execution authorization, and preserve actual prerequisite gates. It requires covering user instructions and grants no archive-publication or GC policy. For a changed contract or prerequisite baseline, use `lifecycle replan`. Complete or recover the current project operation before the next. The current agent manages native tasks while preserving current local source, artifacts and evidence.

`lifecycle replan` stores an unreviewed preservation checkpoint and the intended manual/autonomous mode, retires the current generation and invalidates affected review/acceptance evidence. An unresolved transition retains its original identity. `lifecycle prepare` requires actual accepted prerequisite delivery in either mode, then creates a fresh isolated baseline. Migrate only the source item's own delta. Assess design applicability against the replacement under the [coverage-reuse rules](../../review-design/references/implementable-gate.md#reuse-independent-coverage), independently reviewing invalidated scope or conducting the first full review when no valid basis exists. The replacement requires current independent implementation review or explicit human acceptance through the accepted-target checkpoint in the command contract. `retained_sources` and generation records identify source to preserve and assess.

Preservation stores working and staged trees in immutable reachable commits without changing source HEAD, staging or working files. It captures nonignored source only. Ignored files, nested repositories and unfinished Git operations require their own disposition; never silently upload or delete them. A preservation checkpoint provides recovery, not independent approval or delivery.

Unsupported nonempty operational or retained-generation state blocks mutation until explicit recovery. Preserve the recorded source, resource locators and evidence; never drop unknown fields to make an item appear ready. Read-only diagnostic data is not permission to resume source writes or collect resources.

## References and retention

Resources are exact registered worktrees, internal preservation refs and retained caches. Each has an item/repository association, stable identity, expected OID or development descriptor, state and retention reasons. Physical manifests bind the registered local resource, Git common directory and exact path. Replacement source uses verified preserved content and the bound local repository. Unknown resources are never claimed by name or prefix.

Undisposed retired source, pending preservation publication, current development and required physical recovery keep resources live. Semantic migration/discard does not release the last recovery ref until worktree removal is recorded. Superseded preservation checkpoints remain protected while their generation lacks an actual disposition. Audit history alone does not retain physical copies forever.

Use `lifecycle adopt --worktree RELATIVE_PATH` to refresh preservation for an exact registered retained source. `dispose --disposition migrated` requires actual migration evidence bound to the independently reviewed unchanged replacement; `discarded` requires the user's explicit authorization for that exact unique generation. Dirty or ignored source still blocks physical removal and consumes capacity. Ordinary development worktrees retain separately authorized `cleanup-worktree` boundaries.

The default adopted policy is seven days of grace for unused remote refs, two retained source generations/worktrees and twenty resident preservation checkpoints per item. Typed policy arguments configure these limits. Capacity exhaustion blocks creation; it never permits deleting a live ref or unique source. Status reports retention reasons, pending operations and cleanup blockers. At quiescent stage boundaries or on capacity blockage, the controller may maintain resources within an already adopted policy; no unattended daemon is required.

Historical runtime caches may contain the only unpublished report and remain protected without an independent archival verifier. Unknown files and externally allocated stage directories are not disposable merely because a stage completed.

## Collection and recovery

`lifecycle plan` publishes exact deletion intent under guarded project state. `collect` accepts only its returned intent/digest under current input and retention guards. The digest binds the manifest, not authorization. Recheck current retention requirements, source identity and publication outcomes before deletion. A blocked collection retains its continuation for the same intent; an uncertain archive publication resumes its original transition. Any local session may continue the exact intent after checking current inputs, source identity and applicable authorization.

Remote deletion is conditional on the recorded OID; unsupported conditional deletion fails closed. Local ref deletion also compares its OID and requires verified remote recovery. Collection orders local refs before worktrees and remote refs. Worktree removal rechecks the exact registered resource, repository identity, clean/ignored state, unfinished Git state and exact recovery, using ordinary Git worktree removal. Partial deletion retains the same manifest: an absent exact target may finish, while a divergent or recreated target is preserved. Settle metadata publication recovery before continuing the outer lifecycle operation.

Project removal inventories current and retained worktrees, blocks unsettled lifecycle operations and retains the resource registry with its project-remote recovery commit. Default remote retention remains explicit in that manifest; local project removal does not erase the surviving registry. Ref deletion does not guarantee immediate Git object reclamation.

known-limit: discovery covers registered resources in bound repositories, not unknown external stage directories or cross-project consumers. Extending collection needs explicit resource registration, retention and deletion boundaries. Refreshing retained source after new commits creates another preservation checkpoint and resets disposition. Dirty source remains visible and protected; preservation never authorizes force-removal.
