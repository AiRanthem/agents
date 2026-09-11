---
name: rebase-worktree
description: Safely rebase the current Git worktree onto a user-specified branch or ref while preserving committed and uncommitted state, resolving semantic conflicts, restoring local changes, and independently verifying the result. Use for existing-worktree rebase requests; exclude merge, cherry-pick, worktree creation, push, and PR workflows.
---

# Rebase Worktree

Rebase the current branch onto an exact target while preserving a recoverable pre-rebase state and demonstrating that the intended patch series and local work survive the rewrite.

## Keep authority and state explicit

A request to rebase authorizes the local safety branch, stash, history rewrite, conflict resolution consistent with confirmed intent, local-state restoration, and relevant non-destructive verification. Refresh only the applicable remote ref when the request requires its current remote state or repository instructions require the refresh. Push, force-push, PR changes, sign-off rewrites, and deletion of recovery refs require separate user authorization.

Follow all applicable repository instructions and remote/ref restrictions. Preserve unrelated work and configuration. Never infer a target, replay boundary, merge policy, or semantic conflict decision when multiple reasonable interpretations remain.

## Establish a stable operation

- Identify the repository and worktree, current branch and `HEAD`, target ref and exact target OID, configured upstreams, relevant worktrees, merge base or fork point, and the commits intended for replay. Use `--onto` only when the intended old base and replay range are established.
- Inspect staged, unstaged, untracked, ignored, and submodule state. Detect an in-progress rebase, merge, cherry-pick, revert, or bisect before changing refs or the index.
- Stop for a detached `HEAD`, ambiguous or missing target, unclear replay range, active Git operation, or another process changing the target. Continue after the user resolves the consequential choice or the operation returns to a stable state.
- Pin the target OID used by the rebase. If a permitted fetch changes the target, update the recorded OID and replay analysis before proceeding.
- If the current branch already has the required base and no commits need replay, report the established state without creating recovery refs or changing the worktree.

## Freeze the pre-rebase state

Create a collision-free local safety branch at the original `HEAD` and record its name and OID. Keep it outside the replayed branch. The eventual rebase must use `--no-update-refs` so configuration cannot move this safety branch.

For a dirty worktree, create a uniquely named stash with `--include-untracked` and record the stash commit OID rather than relying only on a positional name such as `stash@{0}`. Record the staged, unstaged, and untracked path sets without exposing file contents or secrets. The frozen state is the original-tip safety branch plus this stash object.

- Preserve ignored files only when they are relevant and the user authorizes including them; do not default to `--all`.
- Treat modified submodules and other state that stash cannot safely capture as unresolved until a concrete preservation method is approved.
- Do not create a WIP commit in the replayed history. Create a separate snapshot commit only when the user explicitly requests that representation and it cannot enter the rebase range.
- Verify that the safety branch still resolves to the original tip, the stash OID is readable when one was needed, and the primary worktree is clean before starting the rebase.

If any relevant state cannot be represented and recovered, stop before rewriting history.

## Rebase and resolve semantics

Choose ordinary rebase, `--onto`, or `--rebase-merges` from the established history and repository contract. Preserve meaningful merge topology and exclude unrelated commits. Run with `--no-autostash` and `--no-update-refs` so the recorded stash and safety branch remain under explicit control.

For each conflict, inspect the replayed commit, base stages, callers, tests, and both sides' current behavior. During rebase, do not assume `ours` and `theirs` mean the same thing as during a normal merge. Resolve mechanical conflicts that have one behavior-preserving result. When alternatives change behavior, ownership, compatibility, or scope, ask the user and summarize the resulting local code state and global system state for each viable option.

Do not skip, drop, combine, or accept an empty commit without evidence that its intended change is already present or intentionally superseded. Record every such decision. Abort with `git rebase --abort` when the safety snapshot becomes invalid or an essential conflict cannot be resolved; preserve the safety branch and stash for recovery.

After rebase completes, verify that the pinned target is an ancestor of the new tip and the safety branch still points to the recorded original tip before restoring local work.

## Restore the exact local state

Apply the recorded stash by OID with its index state so originally staged changes remain staged. Keep the stash object until the entire rebase has passed independent verification. If restoration conflicts, preserve the stash, resolve only semantically clear cases, and obtain the user's decision for changes that alter behavior or scope.

Compare the final staged, unstaged, and untracked path sets with the recorded state. Explain any intentional difference. An applied stash or clean command exit alone does not prove that local work was preserved.

## Require independent verification

Once the rebased tip and restored worktree are stable, dispatch one fresh read-only subagent that did not perform the rebase. Give it the repository/worktree path, original tip and base, safety branch and OID, stash OID when present, pinned target OID, new tip, conflict files and decisions, and verification already run. The subagent must not checkout branches, change refs or the index, apply a stash, resolve conflicts, or modify the shared worktree.

The subagent must independently:

- use `git range-diff` or equivalent commit-level evidence to account for every intended old commit in the new series, including reordered, split, combined, empty, or dropped commits;
- inspect each conflict resolution and distinguish upstream integration from lost branch behavior;
- verify the pinned target ancestry, unchanged safety ref, absence of unresolved conflict markers, and a stable final snapshot;
- compare the frozen stash state with the restored staged, unstaged, and untracked work for semantic preservation; and
- assess risk-appropriate tests, builds, formatting, generation, and static checks, running permitted read-only checks when existing evidence is insufficient.

The primary agent must validate material findings against the repository and resolve them before claiming success. If no qualifying subagent is available, complete safe local checks and report that the branch was rebased but correctness is Unable to conclude because the independent gate is missing.

## Report and retain recovery

Report the repository/worktree, current branch, exact original tip, old base, pinned target, new tip, safety branch, stash OID and restoration state, rebase mode, conflicts and resolutions, range comparison, verification commands and results, subagent identity when known, findings, and remaining uncertainty.

Use one of these outcomes: **Rebased and independently verified**, **Rebased but unable to conclude**, or **Aborted or blocked with recovery intact**. Claim the first only when the intended commits and local state are accounted for and all required checks pass.

Leave the safety branch and stash in place unless the user separately authorizes their deletion. End after reporting the exact cleanup candidates; do not push or publish the rewritten history.
