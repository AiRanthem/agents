# Implementation and read-only planning

## Mode and readiness

Read-only planning exists only when active host instructions establish it; a request to plan, missing write access or a read-only tool does not establish that mode. Normal execution is subject to actual permissions. Require a plan only when the user or active mode requires it.

For direct implementation outside managed projects, use a current `design_status: implementable` document as review evidence when available; check whether later changes invalidate it. If no current review status exists, including a conversation-only design, explain the missing review assurance and concrete uncertainty before affected edits, and ask whether to proceed unless that unchanged contract already has the user's agreement. Such agreement waives only missing review status. It does not settle product decisions or waive defects, permissions or verification. Invoke `$review-design` only when the user has authorized design review.

Use the approved final implementation plan or authorized `$receiving-code-review` correction targets as the current execution contract. Material Why/What revisions require the applicable approval handoff. Managed projects follow the same actual authorization and evidence principles and maintain their existing records directly.

## Contract correction

After the user approves a material Why/What correction, reassess the whole implementation against it, retaining still-correct work and evidence. Approval of a previous contract does not approve a material contract change.

- In execution, approval of a concrete correction authorizes updating the existing design in its language. For a standalone document, set its frontmatter to `design_status: review-pending`. For a managed project, update the item's spec and record pending review in project metadata under the [project workflow](project-workflow.md). Keep implementation tasks and history out of the design.
- Existing design in read-only planning: leave all files unchanged, restate the approved correction conversationally and retain the existing paths and agreed edits for execution synchronization. This does not authorize creating a design file.
- Conversation-only design: restate the revised approved contract; do not create a document.

Do not modify repository instructions such as `AGENTS.md` without explicit authorization. Use concise code comments for durable local reasoning where suitable.

## Mode-specific result

In read-only planning, do not create or modify source, designs, temporary drafts or delegated files. Return the settled executable TODO decomposition once as the final planning result. Include the approved contract, component and necessary function boundaries, failure handling, verification, independent acceptance and handoff requirements. Distinguish proposed checks from checks actually run. Do not include document creation or a second planning task. Tell the executor to load `$implement-design` with the approved contract and TODOs and proceed in execution mode. Persistence performed by the surrounding runtime is permitted when its active permissions allow it.

In execution, execute the settled TODOs under the existing approval. When resuming an approved final plan, load the contract, confirm relevant assumptions and synchronize approved deferred edits into existing documents before affected code edits. Reconsider the approach only when new evidence or a user change invalidates it.

## Delegation

Honor user model choices and actual tools. Use bounded independent research, disjoint edits or checks when delegation is authorized and useful; give exact scope, ownership, constraints, evidence and stopping conditions. Keep writing scopes disjoint and review stable inputs. The implementation owner retains interpretation, integration, decision handling, critical verification and completion reporting; inspect delegated diffs and verify material claims against primary evidence.

Do not assume a requested model switch occurred, quotas are separate or an unapproved external route is available. Raise consequential unresolved decisions with the smallest coherent boundary and evidence. A model change does not settle a user decision. If a required capability or quality gate is unavailable, report that boundary and continue independent authorized work.
