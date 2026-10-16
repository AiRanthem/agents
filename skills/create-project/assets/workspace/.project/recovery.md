# Recover this workspace

Restore the dedicated branch `{{STORAGE_BRANCH}}` from `{{STORAGE_URL}}` and start the agent at this project's management root. Read its generated `AGENTS.md`. If shared skills are missing, install the dev-kit from `{{DEVKIT_SOURCE}}` using its installation contract. Credentials and unpublished code are not restored by cloning project records.

Use installed `manage-workitems/scripts/project.py status`. Report its facts; for `partial`, run only the returned resume command. `published` or `no_op` ends the operation; `blocked` permits only the returned begin command for `code: stale_ticket`; expired tickets carrying authorization or review evidence return `code: stale_evidence` without a continuation command; otherwise report its listed blockers or missing facts. Keep local identity/recovery data; no timeout or new session authorizes takeover.

Use `upgrade-project` for deterministic migration and generated instruction refresh. Project documents contain only current effective instructions and knowledge; Git retains prior versions. Preserve current approval, delivery and unresolved recovery credentials. Required original main-workspace instructions and code-worktree paths come from the program; read the originals before dependent work. Missing bindings, originals or unpublished code must be restored through the stated inputs rather than guessed.
