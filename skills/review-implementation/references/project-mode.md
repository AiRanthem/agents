# Project implementation review

Authorized read-only reviews use the [read-only project route](../../manage-workitems/references/commands.md#reading-and-setup) and retain a separate temporary report. The controller records actual results directly in project files; reviewed source remains read-only.

Apply the standard's [review preparation](review-standard.md#prepare-shared-context-and-a-review-plan) and [mode rules](review-standard.md#resolve-review-mode). The project operator or controller passes the resolved mode to the fresh reviewer. A delegated lead returns a missing mode decision to the caller.

Read the current complete requirement and spec, applicable original instructions, comparison baseline and the actual stable source snapshot supplied by the controller. Do not seek historical review conclusions before your own assessment. Include staged, unstaged and relevant untracked contents; HEAD alone is insufficient.

The stage executor writes only its designated report. Apply the [independence and mode-specific gates](review-standard.md#require-independence-and-mode-specific-coverage) and the standard's [acceptance rules](review-standard.md#report-acceptance-and-stop). Return findings, outcome, resolved mode, actual identity, input binding, snapshot, commands and provenance. The controller records the independent assessment and its actual target under [direct file maintenance](../../manage-workitems/references/commands.md).

In ordinary project development or autonomous advancement, the controller records the actual result, report, reviewer identity and provenance in the existing project records, then commits and pushes that metadata. Native tasks remain with the coordinating agent. Source submission, delivery and cleanup retain their separate authorization boundaries.
