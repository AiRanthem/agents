# Association with a business main workspace

A main workspace owns reusable business context, repository conventions and local skills. A project owns its requirements, designs, claims and delivery records in a separate Git repository. Association is optional and does not turn the main workspace into a managed project. Apply this contract when `main_workspace` is configured in `.project/project.json`.

## Choose locations and storage

Inspect the main workspace's `AGENTS.md`, directory map, ignore rules and relevant skill entrypoints. During project creation, inspect only what is needed to establish storage, layout, instruction routes and necessary background; leave source investigation and design for an explicitly requested task. Recommend locations from that evidence. Keep project sessions rooted at the project; use explicit workdirs for main-workspace or code commands. The main checkout retains its prescribed branch. Resolve instructions such as “update the main workspace” against that checkout, not the project's storage branch.

Choose `worktrees.base: project` for project-local code, or `main_workspace` for code under a dedicated main-workspace subdirectory, such as `worktrees/<project-id>/`. The latter preserves a shared top-level worktree convention without mixing projects' ownership. `worktrees.path` and each `development.worktree` are relative to the selected base. Use `project_runtime.py worktree-root` or `worktree-path <item-id>` to resolve the actual location; a recorded relative path alone is not an absolute destination. Existing developments retain their location: changing layout or binding while local work exists requires accounting for those worktrees before adopting a new mapping.

The project's `worktrees/.gitkeep` is tracked and empty; all other contents beneath it are ignored. Each code repository manages its own Git state. When code is external, recreate its dedicated directory after binding the main workspace; the project placeholder does not contain a symlink to it. Verify the main repository also ignores the selected project directory and code-worktree directory and tracks neither as files nor gitlinks.

For projects nested under the main workspace, maintain a versionable `.gitignore` in their containing directory, such as `projects/.gitignore`. In a container dedicated to independent project repositories, use `*` followed by `!.gitignore` so its contents are ignored and the ignore file remains visible to the main repository. In a shared container, add an anchored entry for only the selected project directory, preserving unrelated contents and existing rules. Reuse versionable ignore rules for external code-worktree directories, adding scoped entries to their containing `.gitignore` when needed. Confirm with `git check-ignore -v` that the effective isolation comes from these versionable rules, and with `git ls-files` and `git status` that nested repositories are isolated and the container's ignore file can be tracked. Creating an associated project includes this local integration configuration; committing or pushing main-workspace changes requires separate authorization.

If the main workspace has a remote, offer that URL with a separate project branch under its permitted namespace. The selected project storage ref must differ from the main workspace's own ref. Check the exact candidate ref; an unused branch starts with an empty root tree/history, and a user-selected existing empty-tree branch may be extended. Initialize the independent project repository in an empty directory, configure only the chosen storage ref, and push only that ref without force. Main-workspace files, skills, code, credentials and Git history are not copied into the project branch. Existing project branches use recovery. Branch-name collisions or unrelated contents require another choice.

## Portable association and local binding

Store `main_workspace` identity and optional clone URL/full ref, plus the chosen `worktrees` layout, using [schema](schema.md). Save only the verified local binding in `.project-local/main-workspace.json`:

```json
{"id": "oka", "root": "/absolute/path/to/OKAWorkspace"}
```

The root is selected from actual local evidence, not reconstructed by counting parent directories. Verify its `AGENTS.md` and identity; when a repository is configured, verify a matching effective remote URL and inspect its current branch against the main-workspace rules. Record-specific routes are relative to that main root. No remote means recovery requires a separately supplied main workspace. Never claim that cloning the project alone restores it.

Create tracked `.project/main-workspace.md` as a small routing document containing:

- Identity, purpose, clone/ref reference and the local binding filename.
- Required instruction entrypoints, starting with `AGENTS.md`, and a concise snapshot of project-relevant constraints with source paths and source commit/content hashes. Include repository bases, environment, delivery or permission constraints only when relevant.
- A table of business context and skill entrypoint paths, when each is needed, and what it supplies. Route to existing indexes instead of copying every document or skill body.
- Recovery prerequisites, worktree location rationale, and any unresolved instruction or environment conflicts.

Treat this document as navigation and recoverable context. At session start, resolve the binding and read the required original instructions explicitly; nested Git roots or a restored project outside its original parent may not automatically inherit them. Read topic documents and skills only for the current task. Preserve each instruction's actual scope and priority, and surface material conflicts before dependent writes. Snapshots never silently override newer original instructions. If the main workspace is unavailable, abstract item reading/management can continue from project records; code, release or other operations requiring missing constraints wait until those inputs are restored.

Pass the project root, verified main root, necessary instruction paths, item and role to delegated agents. A path reference is not proof that a host automatically discovered the main workspace's skills. Resolve and read the selected `SKILL.md` explicitly when needed, follow its script/environment conventions, and check its tools are available. Shared environments remain at the main root; project creation does not duplicate or recreate them.

## Refresh, restore and remove

On a new machine, restore or locate the main workspace at its configured ref using its own setup instructions, verify identity, then write the local binding. Keep project metadata reads usable before this step. Resolve code destinations afresh and recover only published branches, preserving the normal ownership gates. A relocated binding does not migrate dirty worktrees or transfer a writer's claim.

Context queries return the routing path and layout without reading the main workspace's bodies. For reused context/evidence, verify only the relevant source identities under the bound main root; changed constraints invalidate affected decisions and reviews. Local indexes are navigation, not evidence that external context is current. Persist deliberate updates to routing snapshots at the same checkpoints as other project context.

Cleanup and deletion enumerate exact item-owned worktrees both inside and outside the project. Preserve the main workspace, its shared environment/skills/source checkouts, sibling projects and their worktrees. An unavailable binding or occupied ambiguous path leaves cleanup pending; do not infer ownership from a directory prefix. Removing the project never recursively removes a shared main-workspace worktree root.
