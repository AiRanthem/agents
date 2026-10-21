# Execution modes and document status

Use read-only planning only when active host instructions explicitly establish it; otherwise honor ordinary execution permissions. Design-content writes are limited to authorized mechanical corrections under the [shared standard](implementable-gate.md#mechanical-corrections-and-authorship); substantive corrections belong to the design author.

## Read-only planning

Review read-only and report in conversation. A successful independent challenge is **Review passed without document status**. It needs no design file or `implementable` status for the `$explore-design` → `$implement-design` planning handoff. Do not write status, reports or temporary drafts, directly or through delegation. Mechanical corrections stay in conversation; findings and decision requests stay outside the final implementation plan.

## Ordinary execution

Apply permitted mechanical corrections only within the authorized document, record their diff/evidence and unchanged contract, and assess that final exact document. On an independent pass on a fully user-approved documented Why/What, write `design_status: implementable` in that exact document's YAML frontmatter. Add the field if absent while preserving unrelated metadata and the body. Verify the result and report **Implementable** only when writeback succeeded for the reviewed identity.

If approval, a document or permitted writeback is missing, report **Review passed without document status**. Do not imply the document is `implementable`. A read-only planning pass can support later authorized writeback only while the approved contract and repository assumptions remain unchanged.

A material design revision resets its status to `review-pending`. A failed review of an already `implementable` document clears that stale status in execution mode when permitted; otherwise report the status invalid. Do not make substantive revisions to the design body. Route substantive Why/What corrections to `$explore-design`, with any user-owned decisions resolved before affected implementation. Synchronize an existing design document in execution mode before affected code edits.

`Implementable` establishes the documented review result. It does not authorize new requirements, public or stored contracts, dependencies or implementation; ordinary implementation still needs authorization. Contract-internal private types and local implementation choices follow existing authorization rather than a new type-shape approval gate.
