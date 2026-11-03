# Project source and resource lifecycle

Record actual source repositories, branches, worktrees and preserved implementations in current state/context. A change in execution mode does not move or discard source. Continue useful work and retain original contributor attribution.

When an authorized task replaces an implementation or baseline, identify current work and preserve source needed for continued work or recovery. Record the new location and the disposition of the previous source. Keep historical review evidence associated with the work it assessed.

Cleanup/deletion requires authorization covering the selected resources. Use exact paths and refs, inspect actual contents and recovery locations, and preserve unrelated worktrees and shared roots. Do not infer ownership from prefixes or erase uncommitted work because a record calls it obsolete.

Use [cleanup-worktree](../../cleanup-worktree/SKILL.md) for local Git worktree removal and [delete-project](../../delete-project/SKILL.md) for selected project removal. Record actual results directly and commit/push the project records. Remote ref deletion and external history removal remain separately scoped actions.
