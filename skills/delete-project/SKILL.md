---
name: delete-project
description: Inspect and remove an explicitly selected local managed project workspace while preserving its remote branch and Aone history. May run outside the project. Use for project removal, not work-item deletion or general Git cleanup.
---

# Delete Project

Default to deleting only the selected machine's workspace. Read [project recovery and removal](../manage-workitems/references/recovery.md). Resolve the exact project marker and real path; a directory name or an arbitrary `AGENTS.md` is not proof of project identity.

Before deletion, establish that active writers have stopped, all project updates and backend outcomes are recoverable, and local code contains no unpublished work that would be lost. Include staged, unstaged, untracked, ignored, stash, in-progress Git and linked-worktree state. An unresolved Aone outcome or local-only receipt must be resolved or explicitly preserved before removal.

Prepare one exact manifest containing the workspace, item-owned worktrees resolved against their configured base (including main-workspace locations), local clones, retained external source repositories and preservation destinations. Load [main-workspace association](../manage-workitems/references/main-workspace.md) when configured. Preserve the main workspace, shared skills/environments and other projects; never remove a shared worktree directory recursively. Missing or ambiguous external bindings leave those removals pending. Show unpublished or unverified state rather than deleting it. Keep remote project branches, remote code branches and Aone records outside the default manifest. A separate request to delete remote resources needs its own exact scope and evidence.

Ask for confirmation of the concrete deletion manifest unless that same manifest is already authorized. This skill does not infer permission to discard uncommitted code from a request to remove a project. Perform already-authorized preservation before the final confirmation.

Remove linked worktrees with Git from a surviving repository; preserve external source repositories and unrelated registrations. Do not route project removal through `cleanup-worktree` in a way that deletes remote branches. Remove the project root only after every local resource, including external item worktrees, has an accounted-for disposition, and verify surviving resources and retained remote refs. Report partial failures without broadening deletion.
