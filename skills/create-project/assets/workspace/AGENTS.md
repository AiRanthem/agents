# {{PROJECT_NAME}}

This directory is the management workspace for project `{{PROJECT_ID}}`. Start all project agents here. Read `.project/context.md` for background and `.project/project.json` for the authoritative repository/ref and backend configuration.

If `main_workspace` is configured, read `.project/main-workspace.md`, resolve the local binding, and explicitly read its required original instructions. Load associated business context and skills by the task's routes; pass the verified main root and necessary instructions to subagents.

Use the installed project skills: `manage-workitems` for abstract requirements, `split-workitem` for decomposition, `develop-workitem` for design/implementation, and `complete-workitem` for delivery/cleanup. Their shared `manage-workitems/references/project-context.md` defines the protocol. Read only the selected role/item context; the full selected requirement and spec remain authoritative.

Project and item creation produce metadata, necessary background and requirement skeletons. Record supplied requirements as `new` items and leave missing details unresolved. Finish creation after persistence; enter design only on an explicit user request. Do not automatically start decomposition, source-code investigation or design because a requirement was supplied.

Resolve code locations from the configured worktree base using the runtime's `worktree-root`/`worktree-path` commands. Keep `worktrees/.gitkeep` tracked and its code contents ignored; each code repository owns its Git state. Run code commands with an explicit workdir and read that repository's instructions. Keep local bindings, caches and drafts under ignored `.project-local/`. One item has one writer. Check current remote ownership before writes, and publish the `developing` claim before implementing. Project metadata checkpoints must synchronize every enabled backend and verify the final remote push. Code remains uncommitted for the user's final inspection unless the user requests submission.

Use `.project/workflow.md` for the project-specific development entrypoint and `.project/recovery.md` after cloning or interruption. Never treat a cached index, stale review label or elapsed owner age as authority to start work.
