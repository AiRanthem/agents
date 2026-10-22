---
name: cleanup-worktree
description: Verify that a worktree is clean and its committed work is recoverable from retained remote refs, then remove the authorized local worktree and branches, including recoverable rebase safety branches. Use for local worktree cleanup, regardless of development or merge status; exclude general Git pruning and remote branch deletion.
---

# Clean Up a Recoverable Worktree

Remove the selected local worktree and authorized local branches after proving that all non-ignored files are committed and pushed, the worktree is clean, and its committed state can be restored from retained remote refs. Preserve those remote refs and unrelated resources.

## Project workitems

When the target is a schema-v2 project work item, load [the shared project context](../manage-workitems/references/project-context.md) for binding and evidence rules. Cleanup eligibility uses the same cleanliness and remote-recovery criteria below, independently of the item's delivery status. Cleanup has separate user authorization from delivery. After authorized cleanup succeeds, record its actual result through `begin cleanup-record ID` and the returned command workflow; the program writes project records, including YAML. Ordinary cleanup preserves development metadata; only explicit user authorization to discard an unfinished implementation permits `--cleanup-status done --discard-development --approval-source SOURCE` after verified removal. This preserves requirement/design documents and records the old development snapshot, while invalidating prior base-bound review/waiver evidence; current implementation gates must be satisfied again. Ordinary cleanup does not edit project YAML directly. If recording or recovery scripts block, use [user-authorized manual recovery](../manage-workitems/references/recovery.md#user-authorized-manual-recovery) for concrete approved state/file correction and script repair; record cleanup only as actually performed. Ordinary non-project cleanup follows the workflow below.

Use the project program's returned development location. Associated main-workspace worktrees may be outside the project root. Preserve that main workspace, its shared repositories and sibling projects; an unavailable or conflicting binding prevents removing the affected worktree.

## Establish exact scope

Identify the absolute worktree path, local branch or detached `HEAD`, current OID, upstream, remote repository and full recovery ref, and a surviving worktree for execution. Inspect fetch/push URLs, refspec mappings, branch configuration, and worktree use; do not assume `origin`, identical branch names, or a single remote. Restrict remote reads to repository-authorized namespaces.

Use the conversation and available memory to find publication destinations, branch renames, and any `rebase-worktree` report; verify candidates live. Identify safety branches by that report's exact full ref and original `HEAD` OID, never by a naming pattern. Include a safety branch only if its current OID matches the report and independently meets the remote-recovery gate.

Scope cleanup to local resources. Retain remote branches and tags as recovery sources, together with unrelated local refs, stashes, worktrees, and configuration. A target worktree can be removed while retaining its local branch. Exclude default, protected, release, established shared/base branches, and branches checked out by surviving worktrees from local branch deletion.

## Verify cleanliness and remote recovery

Cleanup is eligible when:

- `git status --porcelain=v1 --untracked-files=all --ignore-submodules=none` in the target is empty: no staged, unstaged, or non-ignored untracked files remain;
- no unfinished Git operation or nested repository/worktree with local-only work would be lost;
- the target `HEAD` and every local branch OID proposed for deletion are available through a retained live remote ref, with a usable repository URL and full ref recorded for recovery; and
- the exact local deletions are within repository rules and the user's authorization.

Verify the remote ref directly, for example with `git ls-remote <remote> <full-ref>`, rather than relying on cached tracking refs or a past push result. Fetch the exact ref as needed and verify that the fetched tip matches the observed live OID. Equal OIDs prove publication; a descendant remote tip also qualifies when `git merge-base --is-ancestor <local-oid> <remote-oid>` succeeds. Merely equivalent patches, a known commit hash without a retained remote ref, or a local-only backup do not prove remote recoverability.

For submodules and nested repositories that will be removed with the target, verify their non-ignored state and remote recovery separately; a clean superproject alone does not prove their commits were pushed. Preserve or exclude any local-only contents. Do not commit, push, or alter files merely to pass the gate unless separately authorized.

Ignored files do not need to be committed or pushed and do not make the worktree dirty for this gate. Inventory their paths and include their removal or preservation in the cleanup manifest. Apply existing authorization; otherwise obtain their disposition with the same cleanup confirmation. Preserve requested files outside the target before removal. Do not force worktree removal to bypass unresolved contents.

Merge status is not a cleanup criterion. Do not require PR/MR discovery or status queries, trunk integration, merge ancestry, patch-ID comparison, or range-diff evidence. Open, draft, closed, unknown, or absent PRs/MRs do not block local cleanup when cleanliness and remote recovery are verified.

## Present the cleanup manifest

Report the cleanliness evidence; exact worktree path; local branch refs/OIDs to remove or retain; remote repository URLs, full refs and observed OIDs to retain; ignored-file dispositions; and related administrative metadata. Provide concrete recovery commands using the verified repository/ref and recorded local OID, including how to recreate the worktree at that OID if the remote branch has advanced.

Apply explicit cleanup authorization already given in the conversation. Ask for confirmation only for deletions or file dispositions not covered by that authorization. Inspection alone does not authorize deletion, and authorization for ignored files alone does not authorize branch or worktree deletion. Keep unsafe or uncertain resources outside the manifest.

Complete one initial audit and one refresh immediately before mutation. Reuse evidence while the relevant inputs are unchanged; repeat only affected checks. A change in local OIDs, contents, recovery availability, or deletion scope requires an updated report and any newly needed authorization. A remote advance that still preserves the recorded OIDs, or an unrelated background fetch, does not itself expand deletion scope.

## Execute and verify

Operate from a surviving worktree. Immediately before mutation, refresh exact recovery refs and repeat cleanliness, OID, repository-operation, protection, and worktree-use checks. Stop before deletion if recovery or an authorized item can no longer be verified.

- Remove the registered worktree with `git worktree remove`; do not use `rm -rf`, `git clean`, or forced worktree removal for unresolved contents.
- Delete only authorized local branches after the worktree is removed. Use `git branch -d` when it succeeds; `git branch -D` is allowed for an exact authorized ref/OID whose remote recovery was verified, even when Git's local deletion check refuses it. Recheck the branch OID before deletion.
- Remove only administrative metadata made stale by these exact local deletions. Keep every remote recovery ref and unrelated resource intact.
- If an operation fails or remaining cleanup safety changes, stop and report the partial result and recovery commands. Do not broaden deletion or recreate resources automatically.

Completion requires confirming that the target path and worktree registration are absent, authorized local refs were removed, retained recovery refs remain live and contain the recorded OIDs, and surviving worktrees and retained candidate refs remain intact. Report removed, retained, and failed items plus the concrete remote recovery instructions. Command exit codes alone do not prove completion.

For program-owned collection of registered internal project resources under an adopted policy, use the managed [resource lifecycle](../manage-workitems/references/resource-lifecycle.md) and its exact typed manifest. That program owns inspections and removal; report blockers without repeating Git checks or broadening the target. Ordinary development worktrees and remote branch deletion remain governed by their separate scopes.
