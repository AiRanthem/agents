---
name: manage-workitems
description: Create, find, update or archive work items through the fixed project command workflow. Applies inside a schema-v2 managed project; v1 projects support diagnostic reading and explicit migration. Requirement recording does not start design or development.
---

# Manage Work Items

Use installed [project.py](scripts/project.py) and the [command contract](references/commands.md). The program owns YAML, IDs, document routes, state transitions, ownership, graph gates and Git/Aone publication. The agent supplies the requested business facts and Markdown prose.

For each requested operation, run `begin OP [ID]` with its typed parameters. Read the complete returned `read` payload, including original instructions at any returned external paths. Edit only the absolute Markdown paths in `editable`, then execute the returned `finish_command` under the command contract. Only design review declares result/provenance finish arguments; `development-finish` receives actual review evidence at `begin`. An empty `editable` list requires no document edit. Follow the returned status as defined in the command contract: `blocked` with `code: stale_ticket` permits only its returned `next_command`; `blocked` with `code: stale_evidence` has no continuation command and requires current authorization/review evidence. Do not choose additional documents, construct JSON requests, edit YAML, recompute status, or reproduce Git/Aone checks and recovery.

Creation captures the user's goal, known scope, acceptance and delivery obligations in a requirement skeleton. Leave unknown details unresolved. Creation ends after persistence; it does not authorize source exploration, splitting, a design or a code worktree. Use `list --query` or `show` only when locating an existing item is part of the request; the program resolves selectors and reports ambiguity.

Keep each development item independently usable in one code repository. Hierarchy records decomposition; dependencies record delivery prerequisites. Archive preserves identity, current state and edges. For a defect in a delivered item, use `begin fix ORIGINAL --title TITLE --slug SLUG`; the program creates a separate `fixes` item and leaves the original delivered state intact. An unfinished fix blocks the original item's downstream implementation, delivery and aggregate completion.

Design and implementation use [develop-workitem](../develop-workitem/SKILL.md); actual delivery uses [complete-workitem](../complete-workitem/SKILL.md). A checkpoint cannot invent user approval, independent review or delivery evidence. Project metadata publication does not authorize code commits or code pushes.

Report the full ID and title, substantive outcome and returned persistence status, for example `123-quota-lock（统一配额锁）`. Use [project context](references/project-context.md) for routing, [schema](references/schema.md) for record ownership and [recovery](references/recovery.md) for restoration scope. Native Plan mode remains read-only.
