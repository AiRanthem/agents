---
name: create-worktree
description: Create a Git branch and worktree for a briefly described task, publish its corresponding remote branch with upstream tracking, and follow the repository's established naming and remote-mapping conventions. Do not use to move, remove, or repair existing worktrees.
---

# Create Worktree and Track Remote

Create one local branch and linked worktree for the user's task, publish the corresponding remote branch, and configure upstream tracking as part of the same operation. Leave existing worktrees unchanged.

- Inspect the repository's remotes, fetch and push mappings, tracking and default branches, existing worktrees, related branch names, and sibling directory names. Infer the upstream base, publishing remote and destination, branch name, and worktree location from the task and established conventions; do not assume `origin`, `main`, or a fixed directory layout.
- Fetch and prune the chosen upstream remote, then base the new branch directly on its refreshed remote-tracking branch. Do not pull, rebase, or reset an existing worktree.
- Refuse to overwrite a colliding path, local branch, or remote destination branch. Ask one concise question only when a material choice remains ambiguous.
- Create the branch and worktree with `git worktree add`, then push only that new branch to the corresponding destination resolved from any configured remote namespace or push refspec, and set the resulting remote branch as upstream. Never force-push.
- Completion requires verifying the selected branch, base commit, clean status, resolved absolute path, matching local and remote branch commits, and upstream configuration. If publishing or tracking fails, report the partial result and preserve the created local branch and worktree.
- Report the branch, upstream base, and tracked remote branch briefly, ending with the absolute worktree directory. Do not commit unless separately requested.
