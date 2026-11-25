---
name: create-worktree
description: Create a Git branch and worktree for a briefly described task, publish its corresponding remote branch with upstream tracking, and follow the repository's established naming and remote-mapping conventions. Do not use to move, remove, or repair existing worktrees.
---

# Create Worktree and Track Remote

Create one local branch and linked worktree for the user's task, publish the corresponding remote branch, and configure upstream tracking as part of the same operation. Leave existing worktrees unchanged.

## Project workitems

For a project work item, read its recorded source location, main-workspace constraints and original repository instructions. Reuse a suitable worktree or create one within scope. Record the actual repository, branch, base, worktree path and publication result. If called by a project workflow, return these facts to its record owner. Otherwise update the existing metadata and publish it under [project publication](../manage-workitems/references/persistence.md).

- Resolve the base ref, publishing repository and full destination ref, local branch name and absolute path from the task, repository instructions and configured mappings. Inspect existing worktrees and related branches for naming and placement. Ask only when a material choice remains ambiguous.
- Refresh only the required upstream ref within the repository's allowed namespace, and fix its observed commit as the base. Leave existing worktrees and unrelated refs unchanged.
- Reject local path and branch collisions. Create the worktree with `git worktree add -b` at the fixed base. Publish only the intended commit to the resolved destination, using an operation that creates the remote ref only if absent. Use a remote create-only capability or, if repository policy permits, Git's exact empty lease `--force-with-lease=<full-ref>:`. Verify that the remote reports creation. A separate existence check and ordinary push can still update a ref created in between. If no permitted create-only operation is available, retain the local result and report the publication blocker. Never force-update an existing remote ref.
- Set tracking to the created remote branch. After a failed or uncertain step, verify the local path, branch and expected OID and read the exact remote ref before retrying. Resume only work demonstrably belonging to this attempt. If publication already succeeded, complete tracking and verification. Treat `up to date` or a matching OID alone as insufficient proof that this attempt created the branch.
- Verify the selected branch, base commit, clean status, absolute worktree path, matching local and live remote branch commits, and upstream configuration. If a step remains blocked, report the actual partial result and preserve the created local branch and worktree.
- Briefly report the branch, upstream base, and tracked remote branch, ending with the absolute worktree directory. Source commits require a separate request.
