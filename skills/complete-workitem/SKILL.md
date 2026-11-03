---
name: complete-workitem
description: Record user final code and design edits during human acceptance, actual acceptance, delivery obligations and separately requested cleanup for a project item. AI review or tests alone never establish delivery.
---

# Complete Work Item

Distinguish waiting for human acceptance, accepted but awaiting delivery, and actually delivered. Read [discussion and authorization](../advance-project/references/discussion-and-authorization.md) and [delivery and cleanup](references/delivery-and-cleanup.md).

Preserve the user's final code and design. Record actual human acceptance with its source and accepted target, separately from independent review. Align remaining outdated design text to the accepted implementation where the user has left it for reconciliation. Retain genuine earlier reviews at their original targets.

The project controller or ordinary authorized project session updates the existing documents and metadata directly, then commits and pushes those project changes. A stage executor returns assigned evidence under [stage-executor](../advance-project/references/stage-executor.md). Read-only planning remains read-only.

Inspect the actual evidence for each declared merge, release, deployment or other delivery obligation. Update status to reflect what occurred and state what remains unverified. Aggregate acceptance covers the full original outcome. Project metadata publication, AI review and tests do not establish source delivery or human acceptance.

Source publication, cleanup and project removal require authorization covering those actions. Preserve successful delivery facts when cleanup fails and keep remaining source edits and obligations visible.
