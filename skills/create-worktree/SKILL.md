---
name: create-worktree
description: Create a Git branch and worktree for a briefly described task, after refreshing the appropriate upstream remote and inferring the repository's established branch and worktree naming conventions. Do not use to move, remove, or repair existing worktrees.
---

# Create Worktree

Create one branch and linked worktree for the user's task while leaving existing worktrees unchanged.

- Inspect the repository's remotes, tracking and default branches, existing worktrees, related branch names, and sibling directory names. Infer the upstream base, branch name, and worktree location from the task and established conventions; do not assume `origin`, `main`, or a fixed directory layout.
- Fetch and prune the chosen upstream remote, then base the new branch directly on its refreshed remote-tracking branch. Do not pull, rebase, or reset an existing worktree.
- Refuse to overwrite a colliding path or branch. Ask one concise question only when a material choice remains ambiguous.
- Create the branch and worktree with `git worktree add`, then verify the selected branch, base commit, clean status, and resolved absolute path.
- Report the branch and upstream base briefly, ending with the absolute worktree directory. Do not commit or push unless separately requested.
