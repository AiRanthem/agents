# Native host modes and ordinary handoff

Read this reference outside a delegated project stage. Native Plan is active only when host instructions explicitly establish it. A request mentioning a plan, an exploratory stance, a read-only tool or a permission failure does not establish Plan mode. Otherwise use Agent behavior while honoring actual permissions.

## Native Plan

Keep exploration and approval in conversation. Do not create or modify design files, temporary drafts or existing designs, including through delegation. Do not propose a new design-file path, seek approval for one or add document creation to the implementation plan. User approval of decisions does not lift native Plan restrictions.

Reserve the host's final-plan mechanism, such as `CreatePlan` or a `proposed_plan` block, for the single implementation plan produced by `$implement-design`. Questions, decision summaries and approval requests stay in conversation.

After the complete Why/What is approved, read and invoke `$implement-design` in the current conversation with those requirements and decisions. This handoff is part of the approved workflow; do not ask the user to invoke it again. It resolves How and produces the sole final implementation plan without requiring a design document or `implementable` status. If unavailable, report the missing capability conversationally; do not replace it with a design document or an approval plan.

Before handoff, verify there were no design-file writes or new document tasks. Continue into implementation planning instead of ending with a design summary as the final plan.

## Ordinary Agent

Remain read-only during exploration until the user approves the reported contract; existing approval of the exact complete contract is sufficient. Before writing, read [design-document](design-document.md), resolve the document path and include any required path decision with the contract discussion. State that approval enables writing the formal design for independent review.

After approval, write one authoritative Why/What document in one language at the approved path, following that reference. Validate the document and report the agreed contract, path, exact design identity, actual checks and pending review. Do not mark it `implementable`.

Invoke `$review-design` next only when the user explicitly requested it; otherwise report pending review. A finding that changes a user-owned contract returns to exploration and approval. Explicitly authorized project advancement uses its delegated stage routing instead of this ordinary invocation rule.
