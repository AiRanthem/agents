---
name: manage-workitems
description: Create, find, update or archive project work items by editing their documents and metadata directly, then committing and pushing the project branch. Report progress from current project facts. Requirement recording does not start design or development.
---

# Manage Work Items

Read the selected project's `AGENTS.md`, configuration and affected work-item documents. Locate associated repositories and original instructions through [project context](references/project-context.md). Maintain Markdown and YAML directly at their existing paths under the [record layout](references/schema.md). Local files are the working state.

Complete each authorized project-record change by committing the affected files and pushing the configured project branch normally. Preserve unrelated edits and retain local work if publication fails. Project-record publication does not authorize source code publication, deployment, messaging or deletion. See [persistence](references/persistence.md) and the optional [Aone mirror](references/aone.md).

For creation, record the user's goal, known scope, acceptance and delivery obligations. Leave unknown facts unresolved. Allocate an unused stable ID from the existing hierarchy and create its requirement/context documents. Creation ends after these records are persisted; design, decomposition and implementation follow the user's requested scope.

For an update, change the complete current document and corresponding metadata together. Keep IDs, dependency references and document paths consistent. Archiving preserves identity and facts. A defect in delivered work gets a separate item with `fixes` pointing to the original; preserve its delivery history. [Workflow](references/workflow.md) describes the business facts to maintain.

Record actual authors, reviewers, user decisions, verification and delivery. A registrar is not automatically an author or reviewer. Human acceptance records the user's actual conclusion about the current work. Preserve user-finalized code and design and distinguish acceptance from independent review. Unperformed work remains unverified.

Use [develop-workitem](../develop-workitem/SKILL.md) for requested design or implementation, [advance-project](../advance-project/SKILL.md) for explicitly requested autonomous advancement and [complete-workitem](../complete-workitem/SKILL.md) for acceptance, delivery and separately requested cleanup. An autonomous stage executor returns its work to the controller, which maintains the shared project records.

## Progress report

Read the current project and selected item files. Report each full ID and title, substantive status, design and implementation progress, dependencies, source branch/worktree, actual review and acceptance, delivery obligations and unresolved facts. Distinguish recorded evidence from facts verified live for the report. Reporting alone does not authorize changes or remote writes.

Maintain useful findings in existing context or [evidence](references/evidence.md). Report what changed and the actual commit/push or external synchronization outcome. Read-only planning remains read-only.
