# Association with a business main workspace

The business main workspace owns reusable context, repository conventions, environments and local skills. The project owns requirements, designs, coordination and evidence. Physical nesting does not merge these scopes.

Record the main-workspace identity and actual path, relevant repository/ref and original instruction locations in existing configuration or association documents. Code may live under ignored `worktrees/` or a dedicated main-workspace directory. Changing a recorded path does not move existing code.

Read original main-workspace and source `AGENTS.md` files before dependent work. Preserve environment, repository, permission and delivery constraints. When delegating, supply original instruction paths and the actual code location rather than substituting a summary.

The main checkout retains its own branch and files. Commit project records only to the configured project branch. Preserve enclosing-workspace ignore rules for nested independent repositories and do not include unrelated business files in project metadata.

A clone of project records does not restore its separate environment or unpublished code. Resolve locations against the current filesystem and retain existing source. Removal covers explicitly selected project-owned paths, preserving main workspaces, shared roots, repositories, environments and other worktrees.
