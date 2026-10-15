# Recover this workspace

Clone branch `{{STORAGE_BRANCH}}` from `{{STORAGE_URL}}` into a dedicated directory and start the agent there. Read root `AGENTS.md` and `.project/context.md`; verify `.project/project.json` against the selected remote/ref.

If shared skills are missing, install the project's dev-kit from `{{DEVKIT_SOURCE}}` using its installation instructions. Do not copy credentials into this repository. Python 3 and Git are required; configured Aone also requires authenticated `a1`.

Run the installed `manage-workitems/scripts/project_runtime.py validate`, then select an item with `project_context.py`. Its local index can be rebuilt. Follow `manage-workitems/references/recovery.md` for claims, backend reconciliation and worktree recovery.

Use `upgrade-project` when this project's management prompts need to follow updated shared skills. It preserves project-specific facts and constraints; data and work-item identity migrations are separate operations.

When a main workspace is configured, use `.project/main-workspace.md` to restore or locate it and save a verified local binding before main-dependent operations. Load its original instructions and required skills; cloning this project restores their references, not its environment or repositories.

Resolve each code location through the runtime's `worktree-path` command, then restore its recorded repository and published branch there. The tracked `worktrees/.gitkeep` retains the project directory while code contents stay ignored. Uncommitted or unpublished code remains on its original machine. Existing ownership must be explicitly handed off; no automatic takeover occurs after a timeout. Recheck relevant review evidence and dependency delivery before resuming implementation.
