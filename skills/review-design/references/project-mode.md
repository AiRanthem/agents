# Project design-review ownership

Use [project context](../../manage-workitems/references/project-context.md) to locate original instructions, the current requirement, the item's spec, approval and review records, and the relevant source baseline. Bind the assessment to the actual candidate.

A project design review requires user authorization and an independent reviewer. Record the actual reviewer and supporting evidence. A substantive author of any version cannot independently approve the design.

Review the approved complete contract. Missing requirements, unresolved consequential choices or unavailable source facts are concrete limits to the assessment. Follow the [shared review standard](implementable-gate.md), including mechanical corrections and [coverage reuse](implementable-gate.md#reuse-independent-coverage). A retained genuine Pass may support unchanged coverage after an applicability assessment; it does not create approval for material changes or replace missing review.

Return the actual reviewer identity, reviewed documents and source target, findings, verdict and report. For a permitted mechanical correction, include the final candidate, exact diff, determining evidence and confirmation that the approved contract is unchanged. Substantive corrections belong to a separate author and receive affected independent re-review. Prefer the original reviewer when still independent.

When authorized to register the result, the project operator updates the existing review report and metadata, preserving exact reviewed content, real authorship and approval sources, then commits and pushes the project update. Keep the spec focused on the design contract and record independent review separately.

An ordinary read-only review returns the assessment in conversation. A report-only delegate writes only its assigned report and expressly authorized candidate corrections, then returns evidence for integration. Read-only planning returns the assessment in conversation in every role.
