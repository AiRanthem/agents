# Execution modes and ordinary handoff

Read this reference outside a delegated project stage. Read-only planning is active only when host instructions explicitly establish it. A request mentioning a plan, an exploratory stance, a read-only tool or a permission failure does not establish read-only planning mode. Otherwise use execution behavior while honoring actual permissions.

## Read-only planning

Keep exploration and approval in conversation. Do not create or modify design files, temporary drafts or existing designs, including through delegation. Do not propose a new design-file path, seek approval for one or add document creation to the implementation plan. User approval of decisions does not lift read-only planning restrictions.

Return only the single implementation plan produced by `$implement-design` as the final planning result. Questions, decision summaries and approval requests stay in conversation.

After the complete Why/What is approved, read and invoke `$implement-design` in the current conversation with those requirements and decisions. This handoff is part of the approved workflow; do not ask the user to invoke it again. It resolves How and produces the sole final implementation plan without requiring a design document or `implementable` status. If unavailable, report the missing capability conversationally; do not replace it with a design document or an approval plan.

Before handoff, verify there were no design-file writes or new document tasks. Continue into implementation planning and return its executable plan.

## Ordinary execution

Keep exploration in conversation unless the user explicitly requests a draft or approves the complete contract. Before writing either document, follow the [design document rules](design-document.md). A draft request authorizes writing the unapproved design at the path the user specified or already approved. Keep open decisions visible in the draft.

For the formal design, present any outstanding path decision with the complete contract for approval. Reuse existing approval of both. After approval, write or finalize the authoritative Why/What document at that path for independent review. Validate it and report the agreed contract, path, exact design identity, actual checks and pending review.

Invoke `$review-design` next only when the user explicitly requested it; otherwise report pending review. A finding that changes a user-owned contract returns to exploration and approval. Explicitly authorized project advancement uses its delegated stage routing instead of this ordinary invocation rule.
