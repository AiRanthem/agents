---
name: delete-project
description: Inspect and remove an explicitly selected local project and its authorized local resources, preserving remote branches, external history and unrelated work. May run outside a project; does not delete individual work items or prune unrelated Git state.
---

# Delete Project

Identify the exact project root and local resources covered by the user's request. Read its configuration and actual Git/worktree state. Account for item-owned worktrees, retained source and unpublished files, including ignored content. Preserve the main workspace, shared roots, environments, source checkouts, sibling projects and unrelated worktrees.

Complete already-authorized preservation before removal. Verify that committed work remains recoverable from retained remote refs; preserve unpublished work unless its discard is explicitly authorized. Use [cleanup-worktree](../cleanup-worktree/SKILL.md) for authorized worktree removal. A local project deletion does not authorize deleting remote refs or external project history.

Apply existing authorization to the identified targets. Ask only if the actual target, disposal of unique content or scope is unresolved. Remove only the authorized local paths using the appropriate filesystem and Git tools. If an operation fails, preserve the remaining files and report what was actually removed and what remains.

Report removed and retained resources and where retained project/source history can be recovered. Retain facts about external resources that still need attention; do not report their deletion merely because local project files were removed.
