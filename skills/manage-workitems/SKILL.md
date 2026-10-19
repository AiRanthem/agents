---
name: manage-workitems
description: Create, find, update or archive work items through the fixed project command workflow. A project progress or status report runs the progress command once and includes stored predevelopment markers. Applies inside a schema-v2 managed project; v1 projects support diagnostic reading and explicit migration. Requirement recording does not start design or development.
---

# Manage Work Items

Use installed [project.py](scripts/project.py) and the [command contract](references/commands.md). The program owns YAML, IDs, document routes, state transitions, ownership, graph gates and Git/Aone publication. The agent supplies the requested business facts and Markdown prose.

## Progress report

A request to report project progress or current status is complete after one `progress` command and the user report written from its JSON. The command refreshes remote authority with the same Git metadata write access as `status`, including `.git/project-publish.lock`. Its items already include the lifecycle summary plus stored predevelopment markers. Scheduling collections during advancement come from `autonomy status` for the recorded coordinator session; a progress report uses `progress`.

Write every item as its full ID and title. Include kind, status, design state and version, delivery status and required evidence, dependencies, branch, worktree, and implementation review result when the JSON has them. When `predevelop` is true, include the authorization source. When `predevelopment` is present, include phase, generation, formal base, baseline, each pin's snapshot id and commit, the retained original worktree and branch, and the item's own snapshot id, status, commit and prerequisite map.

Read phases from the JSON as follows. `speculative` means the recorded review passed on a frozen generation; formal acceptance and delivery wait until every pinned predecessor is human-accepted and actually delivered, so report that wait with the pins and the retained worktree. `preparing` means the generation is ready to pin inputs. `baseline` means pinned snapshots are being integrated. `reconciling` means the item is replaying onto the formal base. `formal`, and an item with no `predevelopment` object, use the stored item status, review result, acceptance and delivery. `predevelop: true` with no `predevelopment` object means the item is authorized and has no generation yet.

Also report `changed`, `commit`, pending sync, pending publications, and the number of `rejected_publications`. A `blocked` or `partial` result follows the command contract status table.

If this is an autonomous stage assignment, read [stage-executor](../advance-project/references/stage-executor.md), return evidence to the controller and perform no project command or formal project-document write. For autonomous scope coordination, use [advance-project](../advance-project/SKILL.md). For ordinary controller operations, read [discussion and authorization](../advance-project/references/discussion-and-authorization.md).

For requested internal-resource lifecycle or generation/mode replacement, read [resource lifecycle](references/resource-lifecycle.md) and use its direct typed commands. Existing resources and user files remain intact unless the applicable policy and exact deletion manifest authorize collection. For each requested Markdown workflow operation, run `begin OP [ID]` with its typed parameters. Read the complete returned `read` payload, including original instructions at any returned external paths. Edit only the absolute Markdown paths in `editable`, then execute the returned `finish_command` under the command contract. Only design review declares result/provenance finish arguments; `development-finish` receives actual review evidence at `begin`. An empty `editable` list requires no document edit. Follow the returned status as defined in the command contract: `blocked` with `code: stale_ticket` permits only its returned `next_command`; `blocked` with `code: stale_evidence` has no continuation command and requires current authorization/review evidence. Do not choose additional documents, construct JSON requests, edit YAML, recompute status, or reproduce Git/Aone checks and recovery.

Creation captures the user's goal, known scope, acceptance and delivery obligations in a requirement skeleton. Leave unknown details unresolved. Creation ends after persistence; it does not authorize source exploration, splitting, a design or a code worktree. Use `list --query` or `show` only when locating an existing item is part of the request; the program resolves selectors and reports ambiguity.

Keep each development item independently usable in one code repository. Hierarchy records decomposition; dependencies record delivery prerequisites. Archive preserves identity, current state and edges. For a defect in a delivered item, use `begin fix ORIGINAL --title TITLE --slug SLUG`; the program creates a separate `fixes` item and leaves the original delivered state intact. An unfinished fix blocks the original item's downstream implementation, delivery and aggregate completion.

Design and implementation use [develop-workitem](../develop-workitem/SKILL.md); actual delivery uses [complete-workitem](../complete-workitem/SKILL.md). The controller is the registrar, not the author or independent reviewer of every delegated result. A checkpoint cannot invent user approval, actual executor identity, independent review, human acceptance or delivery evidence. Project metadata publication does not authorize code commits or code pushes.

Report the full ID and title, substantive outcome and returned persistence status, for example `123-quota-lock（统一配额锁）`. Use [project context](references/project-context.md) for routing, [schema](references/schema.md) for record ownership and [recovery](references/recovery.md) for restoration scope. Native Plan mode remains read-only.
