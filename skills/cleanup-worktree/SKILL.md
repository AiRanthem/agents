---
name: cleanup-worktree
description: Audit every pull or merge request associated with a completed development worktree across all relevant remotes and hosting providers, then remove only the exact worktree and branch resources the user confirms after every request is verified merged. Use for post-development cleanup; do not use for abandoning unmerged work or general Git pruning.
---

# Clean Up a Completed Worktree

Prove that a development worktree is fully merged everywhere it was proposed, present the live evidence and exact cleanup set, and perform the approved deletion without losing local work or touching unrelated refs.

## Discover the complete review surface

- Identify the target worktree, local branch, `HEAD`, upstream, fork point, and every corresponding remote branch. Inspect all configured fetch and push remotes, URLs, refspec mappings, worktrees, and branch configuration; do not assume `origin`, matching local and remote names, one remote, or one hosting provider.
- Search the conversation and available persistent memory for earlier pull requests, merge requests, change requests, remote names, forks, mirrors, branch renames, and publication destinations. Use remembered data only to discover candidates and then verify each candidate live.
- Query every relevant hosting service through an authoritative CLI or API. Search by source repository and branch, source commit when supported, and remembered request identifiers. A branch can have multiple old and current requests on one provider and requests on several providers; enumerate all of them. Absence from one provider or from local Git refs does not prove that no other request exists.
- If a relevant service, repository, or request cannot be queried reliably, report that gap and stop. Do not infer request state from a remote ref, merge commit message, browser search result, or stale memory.

## Build the cleanup gate

List every discovered request with its provider, repository, number or stable identifier, URL, source and target branches, source commit when available, and live state. Distinguish merged from open, draft, closed or declined without merge, and unknown.

Cleanup is eligible only when all of these are true:

- at least one associated request exists, and every discovered request is authoritatively reported as merged; closed, declined, abandoned, draft, open, or unknown does not pass, even when a later request superseded it;
- the current local and remote branch tips contain no changes newer than, divergent from, or otherwise outside the verified merged request heads;
- the target has no staged, unstaged, untracked, ignored, submodule, linked-worktree, or in-progress Git state that could be lost;
- no target branch is a default, protected, release, base, or shared branch, checked out by another worktree, or still needed by another active request; and
- each proposed deletion is allowed by the repository instructions and can be named by exact path or full ref and current OID.

When squash or rebase merging prevents ordinary ancestry from proving safety, account for every branch-only commit through a stable patch comparison such as range-diff or patch IDs, and verify that the resulting tree changes are present in the merged target. Provider status alone is insufficient. If unique work cannot be accounted for, preserve the candidate.

## Present one exact confirmation boundary

Before deleting anything, report the full request-status list, the evidence for each eligibility condition, and one cleanup manifest containing the exact worktree paths, local branches and OIDs, remote names, full remote refs and OIDs, and any related administrative metadata proposed for removal. List unsafe or uncertain items separately and exclude them from the manifest.

Stop after this read-only report and ask the user to confirm that exact manifest. A request to inspect, check, or list status is not cleanup authorization. Any change to a request state, branch OID, worktree contents, or manifest invalidates the confirmation and requires a refreshed report and confirmation.

## Execute and verify the confirmed cleanup

Immediately before mutation, re-query every request and remote ref and repeat the local safety checks. Stop without partial cleanup if any gate changed.

- Operate from a surviving worktree. Delete only confirmed remote source refs, using their resolved remote mappings and never force-pushing. Verify each exact remote ref is absent before removing its local recovery copy.
- Remove each registered worktree with `git worktree remove`; never substitute `rm -rf`, `git clean`, or forced worktree removal for unresolved contents. Delete its local branch normally when Git ancestry supports it. Use forced local branch deletion only when the confirmed provider state, commit-by-commit patch comparison, and merged target tree jointly prove that a squash or rebase merge preserved all work.
- Prune only metadata made stale by these exact deletions. Do not delete tags, stashes, safety branches, other worktrees, provider requests, repository configuration, or unrelated remote-tracking refs unless they were separately listed and confirmed.
- If an operation fails, stop, preserve everything not yet deleted, and report the partial state and recovery options. Never broaden the cleanup to make a command succeed.

Completion requires re-enumerating worktrees and branches, checking target path absence, querying every deleted remote ref, confirming the surviving worktrees are unchanged, and reporting each removed, retained, or failed item. Do not claim successful cleanup from command exit codes alone.
