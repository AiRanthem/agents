# Restore a project session

Clone the configured storage repository's exact project branch into a dedicated workspace. Start the agent at that root, read `AGENTS.md`, and confirm `.project/project.json` matches the actual remote/ref. Install this dev-kit's shared project skills if missing; cloning project records does not install host tools. Use Git and Python 3; an enabled Aone backend also requires authenticated `a1`.

Run `project_runtime.py validate`, then a filtered `project_context.py list` and `context <id> --role <role>`. Rebuild `.project-local/index.json` when missing/stale; it contains no irreplaceable state. Read only the selected full requirement/spec and relevant handoff/evidence.

For a configured main workspace, follow [association and binding](main-workspace.md): restore or locate it separately, verify its identity and instructions, and write `.project-local/main-workspace.json`. Metadata queries work before it is available; dependent code/environment operations require the actual main-workspace inputs. A shared storage remote does not imply that the project branch includes the main branch's files, skills or environment.

## Code and active ownership

Use recorded code repository URL, branch/publishing ref and base commit to locate an existing local checkout or recover the published branch. Resolve `project_runtime.py worktree-path <id>` against the configured project/main-workspace base before filesystem operations. Inspect its real remote conventions and repository instructions. The tracked empty `worktrees/.gitkeep` retains the project's local directory, and code contents remain ignored. External directories are recreated only after binding and ownership checks. Never overwrite an occupied directory or infer permission to start another development from a new binding.

Cloning the project restores documents and references to published code, not dirty code, untracked files, local commits or an unpublished branch from another machine. Do not represent the recovered code tree as identical unless its recorded snapshot can actually be reproduced. Keep the original machine's worktree until the user has preserved or delivered it.

A recorded owner remains active until explicitly released; there is no age-based expiry or direct cross-session transfer during `developing`. A different machine may read and prepare readonly analysis, but must not start duplicate implementation. Same-session recovery verifies the token and pending operations. Cross-session/machine recovery requires confirmation that the old writer stopped, preservation of its code, and reconciliation of ambiguous backend writes. Complete all guarded business catch-up and handoff writes under the recorded old owner credentials, synchronize the final revisions and verify receipts, then release the owner; a new session may claim the preserved development through the normal gate after release. For a shared development, resolve every participating item together using the same recorded owner credentials and development identity; do not start shared writes until all items are available to the recovery checkpoint.

## Interrupted checkpoint

Inspect the selected remote commit and `.project/sync/<id>.json` before continuing. If a push response was lost, fetch only the configured ref and check whether the intended commit/content is present. If Aone's response was lost, reconcile its stable marker and real fields before retrying. Preserve pending/unknown state when the result cannot be proven; avoid recreating an item or releasing its owner prematurely. For shared development, inspect and reconcile each participating item's receipt independently before advancing or releasing any of their owners.

For a dirty local management checkout, preserve and inspect the exact diff; do not reset or stash automatically. Convert the intended edits into a guarded bundle against a verified snapshot once unrelated changes are resolved. For code worktrees, local uncommitted changes are user-owned recovery evidence, not cache.

Before resuming implementation, recheck current spec approval, relevant baseline and prerequisite delivery. A persisted `implementable` label does not remain valid across changes that invalidate its evidence. Report restored scope, current owner, synchronization state, available code and anything that still exists only on the original machine.
