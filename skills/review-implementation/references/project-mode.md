# Project implementation review

Read the current complete requirement and spec, applicable original instructions, comparison baseline and the actual stable source snapshot supplied by the controller. Do not seek historical review conclusions before your own assessment. Include staged, unstaged and relevant untracked contents; HEAD alone is insufficient.

The stage executor edits only its designated report, keeps source read-only and returns findings, outcome, actual identity, input binding, snapshot, commands and provenance. It never calls project commands or records its own review. The controller uses the [command workflow](../../manage-workitems/references/commands.md) or [autonomous coordinator](../../advance-project/references/coordinator.md) to bind real evidence to current inputs. It does not substitute its own code assessment. A runtime rejection or absent quality execution cannot become a review pass.

In ordinary project development, the authorized owner/controller may invoke this skill in a fresh subagent and pass its real result, provenance, reviewer session and report file to `begin development-finish ID`, then execute the returned finish command. In autonomous mode use the actual dispatch/result receipt contract instead of inventing a reviewer session. Source submission, delivery and cleanup remain separate authorization boundaries.
