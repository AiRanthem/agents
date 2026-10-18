# Ordinary implementation and native Plan

Read this for ordinary development and whenever the host establishes native Plan mode. Autonomous executors retain their assigned stage boundaries and use this document only for native Plan restrictions when applicable.

## Mode and readiness

Native Plan exists only when active host instructions establish it; a request to plan, missing write access or a read-only tool does not establish that mode. Agent is normal execution subject to actual permissions. Require a plan only when the user or active mode requires it.

For direct Agent implementation outside managed projects, use a current `design_status: implementable` document as review evidence when available; check whether later changes invalidate it. If no current review status exists, including a conversation-only design, explain the missing review assurance and concrete uncertainty before affected edits, and ask whether to proceed unless that unchanged contract already has the user's agreement. Such agreement waives only missing review status. It does not settle product decisions or waive defects, permissions or verification. Do not invoke explicit-only `$review-design` without authorization.

Execution of an approved native Plan final plan does not add a new status gate. Authorized correction targets from `$receiving-code-review` are the correction contract without a separate design-status confirmation unless they materially revise Why/What. Managed projects use their program gate instead of this direct-implementation status rule.

## Contract correction

After the user approves a material Why/What correction, reassess the whole implementation against it, retaining still-correct work and evidence. A waiver for a previous contract does not approve a revised contract.

- Existing design in Agent: synchronize the approved correction into that document in its language and set `design_status: review-pending`. Approval of the concrete correction authorizes its scoped writeback. Keep implementation tasks and history out of the design. Managed projects use their draft/publish workflow instead of direct writes.
- Existing design in native Plan: leave all files unchanged, restate the approved correction conversationally and retain the existing paths and agreed edits for Agent synchronization. This does not authorize creating a design file.
- Conversation-only design: restate the revised approved contract; do not create a document.

Do not modify repository instructions such as `AGENTS.md` without explicit authorization. Use concise code comments for durable local reasoning where suitable.

## Mode-specific result

In native Plan, do not create or modify source, designs, temporary drafts or delegated files. Return the settled executable TODO decomposition once through the host's final-plan mechanism. Include the approved contract, component and necessary function boundaries, failure handling, verification, independent acceptance and handoff requirements. Distinguish proposed checks from checks actually run. Do not include document creation or a second planning task. Tell the executor to load `$implement-design` with the approved contract and TODOs and proceed in Agent mode. Per-function self-review belongs to execution. Host persistence of the final plan is permitted.

In Agent, execute the settled TODOs directly without another approval-plan phase. When resuming an approved final plan, load the contract, confirm relevant assumptions and synchronize approved deferred edits into existing documents before affected code edits. Reconsider the approach only when new evidence or a user change invalidates it.

## Ordinary delegation

Honor user model choices and actual tools. Use bounded independent research, disjoint edits or checks when delegation is authorized and useful; give exact scope, ownership, constraints, evidence and stopping conditions. Keep writing scopes disjoint and review stable inputs. The implementation owner retains interpretation, integration, decision handling, critical verification and completion reporting; inspect delegated diffs and verify material claims against primary evidence.

Do not assume a requested model switch occurred, quotas are separate or an unapproved external route is available. Raise consequential unresolved decisions with the smallest coherent boundary and evidence; changing model does not settle a user decision. If a required capability or quality gate is unavailable, report that boundary and continue independent authorized work. These ordinary routing guidelines do not govern autonomous executor descendants; the autonomous stage contract owns that organization.
