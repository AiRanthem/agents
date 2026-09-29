---
name: rebase-worktree
description: Rebase the current Git worktree onto a user-specified branch or ref, using a direct path when no conflict risk is known and recovery plus independent verification when evidence suggests conflicts. Use for existing-worktree rebase requests; exclude merge, cherry-pick, worktree creation, push, and PR workflows.
---

# Rebase Worktree

Rebase the current branch onto an exact target. Use the full recovery and verification flow only when concrete evidence suggests replay or local-state restoration may conflict, or when a conflict actually occurs.

## Keep authority and state explicit

A request to rebase authorizes the local history rewrite, preservation and restoration of local work, conflict resolution consistent with confirmed intent, a safety branch when the full flow applies, and relevant non-destructive verification. Refresh only the applicable remote ref when the request requires its current remote state or repository instructions require the refresh. Push, force-push, PR changes, sign-off rewrites, and deletion of recovery refs require separate user authorization.

Follow all applicable repository instructions and remote/ref restrictions. Preserve unrelated work and configuration. Never infer a target, replay boundary, merge policy, or semantic conflict decision when multiple reasonable interpretations remain.

## Establish the operation and choose the path

- Identify the repository and worktree, current branch and original `HEAD` OID, target ref and exact target OID, and commits intended for replay. Establish the old base before using `--onto`; preserve meaningful merge topology when required.
- Check staged, unstaged, untracked, ignored, and submodule state, and whether a rebase, merge, cherry-pick, revert, or bisect is in progress. Stop for a detached `HEAD`, ambiguous or missing target, unclear replay range, active Git operation, or state that cannot be preserved safely.
- Pin the target OID used by the rebase. If a permitted fetch changes the target, update the recorded OID and risk assessment before proceeding; stop if another process changes the target during the operation. If the branch already has the required base and no commits need replay, report that state without changing the worktree.
- Assess conflict risk from the intended replay and local restoration with a small inspection of changed paths and relevant history. Overlap between upstream and replayed changes, semantic dependencies across files, or overlap between saved local changes and the resulting tree calls for the full flow. A dirty worktree alone does not. Do not treat the mere possibility inherent in every rebase as evidence of a conflict.

When none of those risks is known, rebase directly. Do not prepare an extra worktree or safety branch, run a trial rebase, or require a range diff, independent review, or broad test suite for this path.

<!-- known-limit: Changed-path overlap is a heuristic and cannot rule out every per-commit or semantic conflict. If new evidence or a conflict appears, use the full flow. -->

## Preserve local work and rebase

For a dirty worktree on either path, create a uniquely named stash with `--include-untracked`; record its commit OID and the staged, unstaged, and untracked path sets. Preserve ignored files only when relevant and authorized; do not default to `--all`. Treat modified submodules and other state that stash cannot safely capture as unresolved until a concrete preservation method is established. Verify that the stash OID is readable and the worktree is clean before rebasing. Do not create a WIP commit in the replayed history.

On the full path, first create a collision-free local safety branch at the recorded original `HEAD`, outside the replayed branch, and verify its OID. Keep its name and OID for recovery. On the direct path, the recorded original `HEAD` OID and any stash OID are sufficient until a conflict occurs.

Choose ordinary rebase, `--onto`, or `--rebase-merges` from the established history and repository contract. Use `--no-autostash` and `--no-update-refs` so Git does not move other branches or take control of the recorded stash. Do not skip, drop, combine, or accept an empty commit without evidence that its intended change is already present or intentionally superseded.

If a direct rebase stops on a conflict, preserve the original `HEAD` and stash OIDs, abort the rebase, and verify that the original branch tip is restored. Then create the safety branch at that recorded original OID and continue under the full flow. If abort does not restore a stable state, stop with the original OID and stash recorded; never create a purported original-tip backup from the current conflicted `HEAD`.

After a successful rebase, verify that the pinned target is an ancestor of the new tip. Restore any stash by its recorded OID with its index state, preserving originally staged changes. Compare the final staged, unstaged, and untracked path sets with the recorded state and explain intentional differences. Confirm no rebase remains in progress and the index has no unresolved entries. Keep the stash object until verification is complete. If restoration conflicts on the direct path, create the safety branch at the recorded original OID, preserve the stash, and use the full flow's conflict resolution and verification for the already rebased tip.

## Full flow when conflict risk exists

Before rebasing on this path, confirm that the safety branch points to the original tip and the worktree is clean after any stash. If state cannot be represented and recovered, stop before rewriting history. A separate snapshot commit is allowed only when the user explicitly requests it and it cannot enter the rebase range.

For each replay or restoration conflict, inspect the replayed commit, base stages, callers, tests, and both sides' current behavior. During rebase, `ours` and `theirs` have different roles from a normal merge. Resolve mechanical conflicts with one behavior-preserving result. When alternatives change behavior, ownership, compatibility, or scope, ask the user and summarize each viable option's local code and system behavior. Abort when an essential replay conflict cannot be resolved, preserving the safety branch and stash. Record decisions about any skipped, dropped, combined, or empty commits.

Verify that the pinned target is an ancestor of the new tip and the safety branch still points to the original tip. Compare old and new series with `git range-diff` or equivalent commit-level evidence, accounting for every intended old commit, including reordered, split, combined, empty, or dropped commits. Verify the restored staged, unstaged, and untracked work semantically, including conflict resolutions, and check for unresolved conflict markers. Run risk-appropriate checks for the affected behavior.

Dispatch a fresh read-only subagent that did not perform the rebase for independent verification of the stable final snapshot, recovery refs, commit accounting, conflict resolutions, and local-state restoration. Give it the original tip and base, safety branch and OID, stash OID when present, pinned target and new tip, and the evidence already collected. It must not change refs, index, stash, or worktree. Resolve material findings before claiming independent verification. If no qualifying subagent is available, complete safe local checks and report that the rebase succeeded but correctness cannot be concluded without the independent gate.

## Report and retain recovery

For either path, report the worktree, branch, original tip, pinned target, new tip, rebase mode, local-state restoration, stash OID when present, checks and results, exact cleanup candidates, and any uncertainty. For the full path also report the safety branch, conflict decisions, commit comparison, and independent verifier. Do not claim independent verification unless it occurred. Leave any safety branch and stash in place unless the user separately authorizes deletion. Do not push or publish the rewritten history.
