---
name: develop-workitem
description: Prepare or resume requested design and implementation for one work item inside a managed project workspace. Coordinate its worktree, design review, exclusive development claim and implementation review. Does not handle project or requirement creation; do not activate outside a managed project or duplicate a claimed development.
---

# Develop Work Item

Use this workflow for the user's requested design or implementation phase. Project creation and requirement recording stay with `create-project` and `manage-workitems`; do not prepare a worktree or start design merely because an item exists. Enter design only when the user explicitly requests it, including an explicit invocation of this skill's design workflow.

Load [project context](../manage-workitems/references/project-context.md), [workflow](../manage-workitems/references/workflow.md) and the role-specific context for the selected item. Read the complete current requirement and design when applicable; use [evidence](../manage-workitems/references/evidence.md) to avoid repeating discovery.

Keep the session rooted in the project. Commands may target the code worktree explicitly. Read the code repository's own instructions before investigating or editing it.

## Prepare or resume

Check remote project state, item identity, prerequisites and ownership. Resume an existing development and worktree; do not create another because a new session or machine was started. A different active owner blocks writes. Before creating a worktree or publishing its branch, acquire and durably publish a short-lived preparation owner with `in_progress`; this prevents two machines from creating different developments before implementation is claimed. Checkpoint the worktree record and release that preparation owner when handing the design to a new session. Cross-machine takeover requires an explicit handoff after the previous writer and uncertain external operations are resolved.

Select a suitable existing local repository or clone the configured code repository. Apply its actual remote/ref mappings and base; do not inherit the project storage branch as the code base. Resolve the configured worktree directory with `project_runtime.py worktree-root`, or an existing development with `worktree-path <id>`. For an associated main workspace, load its required instructions and applicable skill/environment conventions first. Use `create-worktree` for new linked worktrees in that resolved directory. Its publication of a new branch at the selected base is distinct from committing implementation changes. Persist the branch, full base ref/commit and path relative to the configured base so another machine can recover published code.

## Design

For an explicitly requested design phase, start `explore-design` from the item's requirements and align its behavior, ownership, shared contracts and acceptance with related items. Stable items can complete design before prerequisites deliver, including as part of an authorized design phase covering all decomposed items. Record assumed upstream capabilities, interfaces and behavior; retain explicit open decisions for uncertain scope. Preserve the spec's actual approval state, decisions and evidence at checkpoints. Apply the shared workflow's design cadence within the requested item scope.

After this item's prerequisites deliver, compare their actual results with the dependency assumptions and refresh the review target to include their delivered code. Resolve affected contract decisions through `explore-design` and user alignment while preserving unaffected design work. Leave the design awaiting a user-started `review-design` in a fresh context. Eligible independent items can be reviewed in parallel, without waiting for unrelated designs or deliveries. Do not automatically launch design review. Findings return to exploration or, for oversized scope, `split-workitem`. Only a current independent pass establishes `implementable`. When the user explicitly substitutes their own review for the independent pass, record that decision — reviewer, date, scope reviewed and the explicit go-ahead — in `decisions.md` and reflect it in the spec's approval state, so `implementable` stays auditable and a later session does not wait for a review the user already performed.

## Implement and hand off

Before code edits, require the approved current `implementable` design and actual prerequisite delivery, and complete the exclusive claim gate in the workflow. Set `developing`, record machine/session/token and worktree, synchronize configured backends, and verify the remote Git result. Another machine must observe the claim and refrain from starting another development. Publish claim and handoff checkpoints per [publish-cookbook](../manage-workitems/references/publish-cookbook.md): publish final business writes with pending intents before backend synchronization, then publish receipts from the confirmed readback.

When the user explicitly authorizes multiple items through one shared branch, worktree and PR, keep each item's design approval and prerequisite delivery gates. Before any shared code write, claim every participating item in one guarded bundle with the same machine/session/token and development identity. This gives every item the existing per-item ownership protection while retaining one code writer, worktree and PR. If an item has another owner, resolve it through [recovery](../manage-workitems/references/recovery.md) before starting shared writes; do not mix credentials or leave an attached item unowned.

At implementation handoff, advance all participating items to `awaiting_delivery` and give each its own evidence for the shared PR. With Aone enabled, publish their final business revisions and individual pending intents together, synchronize each item, then batch the receipts. When all readbacks match and the writer has stopped, that receipt bundle may also release the matching owners. A later owner-only release needs no additional backend synchronization. Include all business catch-up in the pending revision before synchronization.

Invoke `implement-design` with the full contract and durable progress record. Its project workflow includes a final `review-implementation` with the required fresh independent subagent; this is authorized by the user's selection of the project development workflow. Review a stable final diff, repair supported findings, and recheck the affected evidence. Keep code uncommitted for the user's final review and submission.

Persist a concise handoff with code snapshot identity, meaningful verification, review coverage, remaining findings and next action. Use `awaiting_delivery` after implementation review; passing tests or a local commit does not establish delivery. After the handoff is fully synchronized and this writer stops, release ownership while retaining the same development identity. Project metadata may be committed and pushed through the project protocol. Code commits and subsequent code pushes require the user's instruction.
