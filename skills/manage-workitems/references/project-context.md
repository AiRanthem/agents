# Project context and routing

Project mode applies only when the current management Git root contains a valid regular `.project/project.json` with `schema_version: 1`. Run helpers from this root. A nested code repository, an arbitrary directory with a similarly named file, and a linked code worktree do not activate project management. `create-project` and `delete-project` may operate from outside the workspace on an explicitly selected root.

Keep agent sessions rooted at the project, including delegated sessions. Pass the project root, item ID, task role, permitted writes and relevant code workdir to a subagent; do not copy the entire workspace into its prompt. Read the code repository's applicable instructions before using its worktree. A code checkout's instructions govern its code, while the project protocol governs project records.

When the project declares `main_workspace`, read `.project/main-workspace.md` and follow [main-workspace association](main-workspace.md). Resolve the local binding, explicitly load the required main-workspace instructions, then load business context and skill bodies only for the task. Supply these roots and required instruction paths to subagents. Do not assume physical nesting or a shared storage remote automatically loads the business context.

## Load only what the task needs

Project and item creation end at metadata, necessary background and requirement skeletons. Supplied requirements do not authorize design. Keep incomplete requirement details unresolved; do not load source code or automatically route to splitting, design or development to fill them. Enter design only when the user explicitly requests it.

Read root `AGENTS.md` and `.project/context.md`, then resolve the item with `project_context.py`. Its queries describe the local clone, not a live cross-machine view. When current remote state matters, fetch only the configured branch and inspect that revision; label any local-only snapshot. Never infer that an unowned local item is unclaimed remotely. Publication always refreshes the authority and verifies guards. Read the complete selected requirement and current spec when designing, reviewing or implementing. The index supplies paths, not replacement contracts.

| Task | Load next |
| --- | --- |
| Create/edit an item or dependency | `manage-workitems`; [schema](schema.md); [persistence](persistence.md) before writing |
| Design, split, implement or complete | [workflow](workflow.md) and the relevant skill |
| Reuse or produce repository evidence | [evidence](evidence.md) |
| Enabled Aone backend | [aone](aone.md) only when configuring or synchronizing |
| Clone, interrupted sync or machine handoff | [recovery](recovery.md) |
| Associated main workspace, external worktree layout or context restoration | [main-workspace association](main-workspace.md) |

The shared helper entrypoints are `scripts/project_context.py` and `scripts/project_runtime.py` relative to this skill directory. Resolve the installed skill's physical location; do not assume a machine-specific absolute path. Both require Python 3 and Git on macOS/Linux. Run a helper's `--help` before an unfamiliar command. Do not copy installed skills into every project.

known-limit: local serialization uses Unix `flock`; native Windows is unsupported in this version. A Windows port needs equivalent cross-process locking and the same concurrency tests before publication is enabled.

## Ownership of records

- `.project/project.json` identifies the project, storage authority, backends, code repositories and optional main-workspace association/layout. `.project/context.md` is the overall background; `.project/main-workspace.md` routes associated business constraints and skills.
- `workitems/<id>/requirement.md` is the current abstract requirement. `spec.md` is the sole full design; its `design_status` frontmatter carries `draft`, `review-pending` or `implementable`.
- `decisions.md` captures approved choices, requirement changes and unresolved questions; `reviews/` holds review evidence and findings; `handoff.md` records current progress and next actions. Keep superseded process out of the spec.
- `evidence/` holds concise reusable source evidence. `.project-local/` contains ignored indexes, pending drafts and machine/worktree bindings. The tracked empty `worktrees/.gitkeep` retains the directory; its other contents are ignored code managed by their own repositories. Configured main-workspace worktrees live in their dedicated external location. Use the runtime's `worktree-root`/`worktree-path` commands to resolve destinations.

Native Plan mode remains read-only: return the intended handoff and pending changes without creating records, claims, commits or remote writes. In Agent mode, authorized project metadata checkpoints may be committed and pushed. Code commits and code pushes after branch creation remain user actions unless separately requested.

Stop the affected operation for a missing/invalid project marker, conflicting owner, invalid dependency graph, stale implementation approval, or unresolved persistence outcome. Continue independent read-only work when useful and report precisely what is pending.
