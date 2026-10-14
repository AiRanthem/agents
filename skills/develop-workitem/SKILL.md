---
name: develop-workitem
description: Prepare or resume design and implementation for one work item only inside a managed project workspace. Coordinate its worktree, design review, exclusive development claim and implementation review. Do not activate outside a managed project or create a duplicate development for a claimed item.
---

# Develop Work Item

Load [project context](../manage-workitems/references/project-context.md), [workflow](../manage-workitems/references/workflow.md) and the role-specific context for the selected item. Read the complete current requirement and design when applicable; use [evidence](../manage-workitems/references/evidence.md) to avoid repeating discovery.

Keep the session rooted in the project. Commands may target the code worktree explicitly. Read the code repository's own instructions before investigating or editing it.

## Prepare or resume

Check remote project state, item identity, prerequisites and ownership. Resume an existing development and worktree; do not create another because a new session or machine was started. A different active owner blocks writes. Before creating a worktree or publishing its branch, acquire and durably publish a short-lived preparation owner with `in_progress`; this prevents two machines from creating different developments before implementation is claimed. Checkpoint the worktree record and release that preparation owner when handing the design to a new session. Cross-machine takeover requires an explicit handoff after the previous writer and uncertain external operations are resolved.

Select a suitable existing local repository or clone the configured code repository. Apply its actual remote/ref mappings and base; do not inherit the project storage branch as the code base. Resolve the configured worktree directory with `project_runtime.py worktree-root`, or an existing development with `worktree-path <id>`. For an associated main workspace, load its required instructions and applicable skill/environment conventions first. Use `create-worktree` for new linked worktrees in that resolved directory. Its publication of a new branch at the selected base is distinct from committing implementation changes. Persist the branch, full base ref/commit and path relative to the configured base so another machine can recover published code.

## Design

Start `explore-design` from the item's requirements. Before prerequisites deliver, allow read-only exploration and an initial `spec.md`, with its actual approval state and explicit dependency assumptions. Preserve decisions and evidence at checkpoints.

After prerequisites deliver, update the review target to include their actual delivered code and invalidate affected assumptions. Leave the design awaiting a user-started `review-design` in a fresh context. Do not automatically launch design review. Findings return to exploration or, for oversized scope, `split-workitem`. Only a current independent pass establishes `implementable`.

## Implement and hand off

Before code edits, require the approved current `implementable` design and actual prerequisite delivery, and complete the exclusive claim gate in the workflow. Set `developing`, record machine/session/token and worktree, synchronize configured backends, and verify the remote Git result. Another machine must observe the claim and refrain from starting another development.

Invoke `implement-design` with the full contract and durable progress record. Its project workflow includes a final `review-implementation` with the required fresh independent subagent; this is authorized by the user's selection of the project development workflow. Review a stable final diff, repair supported findings, and recheck the affected evidence. Keep code uncommitted for the user's final review and submission.

Persist a concise handoff with code snapshot identity, meaningful verification, review coverage, remaining findings and next action. Use `awaiting_delivery` after implementation review; passing tests or a local commit does not establish delivery. After the handoff is fully synchronized and this writer stops, release ownership while retaining the same development identity. Project metadata may be committed and pushed through the project protocol. Code commits and subsequent code pushes require the user's instruction.
