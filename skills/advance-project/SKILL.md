---
name: advance-project
description: Autonomously advance an explicitly requested managed-project scope through design review, implementation, independent code review and corrections until human acceptance is needed. Use for a whole project, an item subtree or selected items after initial contracts are approved; do not create missing initial designs or deliver source automatically.
---

# Advance Project

When project scripts block or malfunction, the controller uses [user-authorized manual recovery](../manage-workitems/references/recovery.md#user-authorized-manual-recovery), including concrete approved state/file corrections and script repair. Executors return recovery needs to the controller.

Coordinate from the management project root on one machine. Complete one stage and its descendant tasks before selecting the next ready stage. Project state tracks current artifacts and genuine contribution evidence; the advancing agent manages execution. Advance ready development items within the requested scope in sequence. An oversized parent with `design.next_action: split` goes from full independent design Pass to controller-owned decomposition. Children inherit its complete relevant contract and enter their own review directly; supplement design only for demonstrated blocking gaps. Keep project records and lifecycle operations with the controller, and code, investigation and review with stage executors.

Read [discussion and authorization](references/discussion-and-authorization.md). In execution mode, read [coordinator](references/coordinator.md) and confirm the caller-supplied execution bindings before dispatch. A delegated stage executor reads [stage-executor](references/stage-executor.md) and its stage skill; it does not become a project controller.

For code review and re-review, the coordinator selects `single-agent` and explicitly passes that mode to `review-implementation`. The executor follows the assigned mode without asking for mode confirmation.

Read-only planning is a read-only host mode, not an autonomous execution mode. Inspect existing scope, contracts, readiness and capabilities without authorizing, spawning writers, preparing worktrees or publishing records. A user request for autonomous work does not lift planning-mode or harness permissions.

End the round when the current stage and its descendants are accounted for and every in-scope item is waiting for human acceptance, accepted but awaiting delivery, completed or concretely blocked. Report exact items, real evidence, acceptance and delivery gaps. AI approval, this run ending and project completion are distinct facts. Leave source uncommitted. Source publication and PRs require covering user instructions.