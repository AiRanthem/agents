---
name: advance-project
description: Autonomously advance an explicitly requested managed-project scope through design review, implementation, independent code review and corrections until human acceptance is needed. Use for a whole project, an item subtree or selected items after initial contracts are approved; do not create missing initial designs or deliver source automatically.
---

# Advance Project

Coordinate from the management project root. Read the current project documents and update them directly as work progresses. The controller owns formal project records and commits and pushes completed metadata edits under [project persistence](../manage-workitems/references/persistence.md). Stage executors own their assigned investigation, code and assessment. Keep real authorship, review evidence, acceptance and delivery distinct.

Read [discussion and authorization](references/discussion-and-authorization.md). In execution mode, use [coordinator](references/coordinator.md) with the caller-supplied role bindings and actual permission limits. A delegated executor reads [stage-executor](references/stage-executor.md) and its assigned stage skill; it does not become a controller.

Advance in-scope items in dependency order, completing each stage and its descendant tasks before selecting the next stage. An oversized item with a complete independently reviewed design uses `split-workitem`; children inherit the relevant contract and enter their own review, with further design only for demonstrated gaps.

For code review and re-review, select `single-agent` and pass that mode to `review-implementation`. Its independent reviewer covers the complete assigned target. Preserve valid previous evidence and useful source when a stage fails or resumes.

Read-only planning remains read-only. Inspect existing contracts and capabilities without writing records, preparing source worktrees or dispatching writers. In execution mode, continue authorized work until items need a real user decision, human acceptance, separately authorized delivery, or an unavailable prerequisite. Continue unaffected items and report concrete evidence and remaining gaps. Source commits, pushes, PRs and cleanup require covering user instructions; ordinary advancement leaves source uncommitted.
