---
name: complete-workitem
description: Register user final code and design edits during human acceptance, verified acceptance, actual delivery obligations and separately requested cleanup for a managed-project item. AI review or tests alone never establish delivery.
---

# Complete Work Item

Distinguish waiting for human acceptance, accepted but awaiting delivery, and actually delivered. Read [discussion and authorization](../advance-project/references/discussion-and-authorization.md) and, for controller work, [delivery and cleanup](references/delivery-and-cleanup.md).

Explicit human acceptance of the current implementation replaces independent implementation review with an attributed pass. During human acceptance, user edits to code and design are final drafts and require no further review. Preserve a user-finalized design; align remaining outdated design text to accepted code through the human-acceptance checkpoint in the delivery reference. The acceptance covers this factual alignment and enters waiting for delivery; preserve its actual user source and current target. The user may explicitly skip any verification checkpoint, including acceptance or delivery verification, under [user verification decisions](../manage-workitems/references/commands.md#user-verification-decisions). Register current scoped decisions, honor them and report skips as unverified; do not invent independent review or actual delivery evidence. The defaults below apply when no covering user decision exists.

Only the project controller performs project CLI operations and writes formal records. A stage executor returns its assigned evidence under [stage-executor](../advance-project/references/stage-executor.md); it cannot complete, accept or deliver an item itself. Read-only planning is read-only and cannot delegate these writes.

Record real user acceptance for the actual current artifacts and verify every declared merge, release, deployment or other obligation. Aggregate items require evidence against every acceptance criterion under the existing aggregate contract; never send them through code implementation merely because they are in an autonomous scope. Only human acceptance plus actual prerequisite delivery unlocks autonomous downstream work.

Source publication, local cleanup and project removal retain their own authorization. A request to advance to acceptance does not authorize them. Keep evidence of unverified obligations and remaining source edits visible; do not set `done` by hand or equate project metadata publication with source delivery.
