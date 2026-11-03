# Project design-review ownership

Read [project context](../../manage-workitems/references/project-context.md), complete current requirements and design, original project/main-workspace/source instructions and relevant primary evidence. Bind the review to the actual candidate and source baseline. Read-only reviews return a separate report and leave formal project files unchanged except expressly authorized mechanical candidate corrections.

Ordinary review requires an explicit user request and an independent reviewer. Authorized `advance-project` covers its review stage without another permission request. The controller records the real reviewer's evidence; it cannot supply a missing review or substitute its identity for the reviewer. A substantive design author or reviser cannot independently approve that design.

Review the approved complete contract. Missing requirements, unresolved consequential choices or unavailable source facts are concrete limits to the assessment. Follow the [shared review standard](implementable-gate.md), including mechanical corrections and [coverage reuse](implementable-gate.md#reuse-independent-coverage). A retained genuine Pass may support unchanged coverage after an applicability assessment; it does not create approval for material changes or replace missing review.

Return the actual reviewer identity, reviewed documents and source target, findings, verdict and report. For a permitted mechanical correction, include the final candidate, exact diff, determining evidence and confirmation that the approved contract is unchanged. Substantive corrections belong to a separate author and receive affected independent re-review. Prefer the original reviewer when still independent.

The ordinary authorized project session or autonomous controller updates the existing review report and metadata directly, preserving exact reviewed content, real authorship and approval sources, then commits and pushes the project update. Do not add unreviewed corrections or claim that registration itself proves quality. Keep the spec focused on the design contract; record independent review separately.

A report-only delegate or [stage executor](../../advance-project/references/stage-executor.md) writes only the assigned report and authorized candidate corrections, then returns evidence for integration. Read-only planning returns the assessment without formal project writes or publication.
