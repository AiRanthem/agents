---
name: advance-project
description: Autonomously advance an explicitly requested managed-project scope through design review, implementation, independent code review and corrections until human acceptance is needed. Use for a whole project, an item subtree or selected items after initial contracts are approved; do not create missing initial designs or deliver source automatically.
---

# Advance Project

Coordinate from the management project root and manage each item’s stage task tree directly. Project state tracks current artifacts and control claims; native executors and their liveness belong to the advancing agent. Advance every ready development item within the requested scope, subject to actual host capacity. Keep project records and lifecycle operations with the controller; keep code, investigation and review with stage executors. Do not introduce work-item managers.

Read [discussion and authorization](references/discussion-and-authorization.md). In execution mode, read [coordinator](references/coordinator.md) and confirm the caller-supplied execution bindings before dispatch. A delegated stage executor instead reads [stage-executor](references/stage-executor.md) and its stage skill; it does not become a project controller.

For code review and re-review, the coordinator selects `single-agent` and explicitly passes that mode to `review-implementation`. The executor follows the assigned mode without asking for mode confirmation.

Read-only planning is a read-only host mode, not an autonomous execution mode. Inspect existing scope, contracts, readiness and capabilities without authorizing, spawning writers, preparing worktrees or publishing records. A user request for autonomous work does not lift planning-mode or harness permissions.

When explicitly enabled or resuming an existing generation, also read [predevelopment](references/predevelopment.md). It defines frozen prerequisite snapshots and mandatory formal convergence; default advancement retains ordinary prerequisite gates.

End the round only when no further action is ready under the current authorization and write claims, this run’s task trees are accounted for and every in-scope item is waiting for human acceptance, accepted but awaiting delivery, speculatively waiting for prerequisite delivery, completed or blocked. An artifact-ready item awaiting takeover approval is write-blocked for this run; retain its actual readiness and report the pending approval separately. These terminal dispositions may coexist; keep following every outstanding executor. Report exact items, real evidence, acceptance and delivery gaps. AI approval, this run ending and project completion are distinct facts. Leave formal source uncommitted; the explicit predevelopment exception covers only its isolated snapshot and Git transformation stages. Other source publication and PRs require covering user instructions.
