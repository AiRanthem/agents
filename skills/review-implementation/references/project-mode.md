# Project implementation review

Use the [read-only project route](../../manage-workitems/references/commands.md#reading-and-setup) to locate the complete current requirement, item spec, recorded approval and original project and source instructions. Keep reviewed source read-only.

Apply the standard's [review preparation](review-standard.md#prepare-shared-context-and-a-review-plan) and [mode rules](review-standard.md#resolve-review-mode). The project operator passes the resolved mode to the independent reviewer. A delegated lead returns a missing mode decision to the caller.

Assess the comparison baseline and stable source snapshot, including staged, unstaged and relevant untracked contents. Apply the standard's [re-review rules](review-standard.md#re-review-only-what-changed-but-invalidate-honestly) after fixes.

Apply the [independence and mode-specific gates](review-standard.md#require-independence-and-mode-specific-coverage) and [acceptance rules](review-standard.md#report-acceptance-and-stop). Return findings, outcome, resolved mode, reviewer identity, reviewed contract and source versions, commands and provenance. An ordinary read-only review returns its assessment in conversation. A delegated reviewer writes only its designated report when the assignment authorizes it. In read-only planning every role reports in conversation.

When authorized to register the result, the project operator records the report, actual reviewer, outcome and reviewed target under [direct file maintenance](../../manage-workitems/references/commands.md), then commits and pushes the project records. Source submission, delivery and cleanup retain their separate authorization boundaries.
