---
name: complete-workitem
description: Record verified human acceptance, actual delivery obligations and separately requested cleanup for a managed-project item. AI review or tests alone never establish delivery.
---

# Complete Work Item

Distinguish waiting for human acceptance, accepted but awaiting delivery, and actually delivered. Read [discussion and authorization](../advance-project/references/discussion-and-authorization.md) and, for controller work, [delivery and cleanup](references/delivery-and-cleanup.md).

Only the project controller performs project CLI operations and writes formal records. A stage executor returns its assigned evidence under [stage-executor](../advance-project/references/stage-executor.md); it cannot complete, accept or deliver an item itself. Read-only planning is read-only and cannot delegate these writes.

Record real user acceptance for the actual current artifacts and verify every declared merge, release, deployment or other obligation. Aggregate items require evidence against every acceptance criterion under the existing aggregate contract; never send them through code implementation merely because they are in an autonomous scope. Only human acceptance plus actual prerequisite delivery unlocks autonomous downstream work.

Source publication, local cleanup and project removal retain their own authorization. A request to advance to acceptance does not authorize them. Keep evidence of unverified obligations and remaining source edits visible; do not set `done` by hand or equate project metadata publication with source delivery.
