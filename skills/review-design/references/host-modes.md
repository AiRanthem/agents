# Native host modes and document status

Use native Plan only when active host instructions explicitly establish it; otherwise honor ordinary Agent permissions. These rules do not authorize design-content edits.

## Native Plan

Review read-only and report in conversation. A successful independent challenge is **Review passed without document status**. It needs no design file or `implementable` status for the `$explore-design` → `$implement-design` planning handoff. Do not write status, reports or temporary drafts, directly or through delegation. Findings and decision requests stay outside the host's final-plan mechanism.

## Ordinary Agent

On an independent pass on a fully user-approved documented Why/What, write only `design_status: implementable` in that exact document's YAML frontmatter. Add the field if absent while preserving unrelated metadata and the body. Verify the result and report **Implementable** only when writeback succeeded for the reviewed identity.

If approval, a document or permitted writeback is missing, report **Review passed without document status**. Do not imply the document is `implementable`. A Plan-mode pass can support later Agent writeback only while the approved contract and repository assumptions remain unchanged.

A material design revision resets its status to `review-pending`. A failed review of an already `implementable` document clears that stale status in Agent mode when permitted; otherwise report the status invalid. Do not revise the design body. Route Why/What corrections to `$explore-design`, with any user-owned decisions resolved before affected implementation. Synchronize an existing design document in Agent mode before affected code edits.

`Implementable` establishes the documented review result. It does not authorize new requirements, public or stored contracts, dependencies or implementation; ordinary implementation still needs authorization. Contract-internal private types and local implementation choices follow existing authorization rather than a new type-shape approval gate.
