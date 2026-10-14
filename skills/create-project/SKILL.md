---
name: create-project
description: Create a durable project workspace across sessions, agents, and machines, standalone or associated with a business main workspace. Choose a dedicated Git branch, worktree layout and optional Aone mirror, then establish context and recovery instructions. May run outside a managed project.
---

# Create Project

Create one project workspace whose durable state is a dedicated remote Git branch. Read [the workspace contract](../manage-workitems/references/project-context.md) and [schema](../manage-workitems/references/schema.md). Reuse known preferences as recommendations, and have the user choose the workspace path, project name, storage repository and dedicated branch before creating remote resources. Inspect the selected repository's own ref mappings; this dev-kit's `devkits/` mapping is not a default for other repositories.

The workspace contains project context, work items, reusable evidence, and a retained `worktrees/` directory whose code contents are ignored. Each development item targets one code repository and one worktree. The project storage repository and code repositories have distinct responsibilities even when hosted by the same provider.

When invoked within a business main workspace, inspect its applicable instructions, directory layout, local skill entrypoints and Git mappings before recommending locations. Read [main-workspace association](../manage-workitems/references/main-workspace.md). Associate the project with the necessary business constraints and select either project-local worktrees or a dedicated location under the main workspace's actual worktree directory. A main workspace with a remote can supply the storage repository: recommend a separate unused branch initialized from an empty tree. Keep its normal checkout and branch intact.

## Establish the workspace

- Select an existing remote repository and an unused dedicated branch, or restore an existing project branch when that is the user's request. Reuse an existing local code repository when suitable; creating the project does not require cloning every code repository.
- Never overwrite a nonempty directory or reuse a branch containing unrelated data. Establish an independent Git repository with only project-owned files and its own Git directory; the management root is not a linked worktree of the main workspace. For a new branch, initialize an unborn/orphan branch in that empty directory, with no main-workspace files or history. An explicitly selected existing empty-tree branch may be extended after checking its exact ref; an existing managed project is restored using [recovery](../manage-workitems/references/recovery.md).
- Git storage is mandatory. If the user selects Aone, read [the Aone adapter](../manage-workitems/references/aone.md), check `a1` availability and identity, and resolve the existing space, type, required fields and status mapping before creating the workspace. Missing `a1` is an error; do not silently drop the backend.
- Copy the files under [assets/workspace](assets/workspace), fill every template value, and create `.project/project.json` according to the schema. Keep `worktrees/.gitkeep` empty and tracked; ignore every other entry under `worktrees/`. Put agreed project background in `.project/context.md`. For an associated project, create `.project/main-workspace.md` using the association contract, and save its local root binding under `.project-local/`. Keep root `AGENTS.md` short.
- For an associated project nested in the main workspace, configure its containing directory's versionable `.gitignore` according to [main-workspace association](../manage-workitems/references/main-workspace.md). For a dedicated `projects/` container, use `projects/.gitignore` with `*` and `!.gitignore`; preserve existing rules and unrelated contents. Main-workspace publication has its own authorization scope.
- Record repository clone URLs, full base refs and publishing conventions. Store the exact configured and effective storage URL in `storage.url`; creation must check that Git fetch and push resolve to the same selected destination before the first publication. Credentials, personal absolute paths and machine identity belong outside tracked metadata. Worktree paths in records are relative to the configured project or main-workspace base.
- Install the shared project skills when needed through this dev-kit's installation workflow. Preserve unrelated machine configuration. The workspace records its protocol version and recovery instructions; cloning it does not install host tools or user-level skills.

## Publish and verify

Project creation authorizes committing and pushing the new project metadata to the chosen dedicated branch. It does not authorize code commits, code publication, or changes to unrelated branches. Push only the selected ref without force; configure tracking and verify the remote commit.

Run `project_runtime.py validate` and a metadata query through `project_context.py`. Confirm the tracked directory placeholder, ignored worktree contents/local caches, completed template substitutions, recoverable repository references, and the selected remote/ref. For an associated project, verify main-workspace routes and isolation from its Git index; use `git check-ignore -v` to confirm the versionable ignore source and verify the container's `.gitignore` remains trackable. Verify the project can be read from a clean clone without machine-local state and document the binding needed for code work. With Aone, configuration checks are not a live work-item synchronization test.

Report the absolute workspace path, selected remote branch, enabled backends, actual validation and any incomplete publication. The user starts all project sessions from this root.
