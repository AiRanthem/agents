# Project context and routing

Project mode applies at a management Git root with valid `.project/project.yaml` schema 2. A code repository or linked worktree does not become a project because it is nested beneath one. Schema-1 `.project/project.json` projects allow diagnostic reading and explicit migration only. Creation, upgrade and deletion may target an explicitly selected project from outside it.

Start project sessions at the management root and read its `AGENTS.md`. Use the installed [project.py](../scripts/project.py) through the [fixed command workflow](commands.md). For a requested write, the program returns the complete read payload, editable Markdown paths and exact finish command. Read those inputs; do not select additional project documents or reproduce the program's gates and persistence checks. Program-generated item instructions and returned original main-workspace instructions retain their own scopes.

Requirements and design work use the complete selected current requirement and spec from the returned payload. Reading a requirement does not authorize design, decomposition, source exploration or implementation. Reuse explicit authorization for the same scope without asking again. Native Plan mode remains read-only; Agent-mode project checkpoints may publish metadata, while code submission requires its own user instruction.

| Requested task | Skill |
| --- | --- |
| Report project progress or current status | [manage-workitems](../SKILL.md#progress-report), one `progress` command |
| Record requirements, rename, change dependencies or archive | [manage-workitems](../SKILL.md) |
| Create a separate project repository | [create-project](../../create-project/SKILL.md) |
| Deterministic project migration and instruction refresh | [upgrade-project](../../upgrade-project/SKILL.md) |
| Decompose a requirement into usable deliverables | [split-workitem](../../split-workitem/SKILL.md) |
| Requested design or implementation | [develop-workitem](../../develop-workitem/SKILL.md) |
| Explicit scoped autonomous advancement | [advance-project](../../advance-project/SKILL.md), through the [coordinator interface](commands.md#autonomous-advancement) |
| Verify actual delivery or separately requested cleanup | [complete-workitem](../../complete-workitem/SKILL.md) |
| Remove the selected local project | [delete-project](../../delete-project/SKILL.md) |

Report full IDs and titles, such as `123-quota-lock（统一配额锁）`. The program resolves full IDs, codes, phrases and exact titles; report ambiguity instead of constructing paths from a guess. Each code level describes decomposition, while the dependency DAG determines delivery prerequisites.

Shared project knowledge is global and may remain valid without an item pointer. Use the direct knowledge commands in [the command contract](commands.md#operations); they do not use the work-item `begin` workflow. Each read returns a unique draft path without creating it. Keep the complete current Markdown body and explicit typed metadata, use returned guards for replacements or removal, and preserve pending or stale drafts as uncommitted work.

[Schema](schema.md) defines record ownership; [workflow](workflow.md) defines lifecycle evidence and authorization. [Main-workspace association](main-workspace.md) describes the separate business context boundary. [Recovery](recovery.md), [Aone](aone.md) and [persistence](persistence.md) describe program responsibilities and the facts to report when execution stops; they do not add agent-selected recovery procedures.

For explicit autonomous advancement, retain the exact selected scope and coordinator identity. Read `autonomy status` for ready/running/blocked/acceptance/delivery collections; continue ready items while reporting affected blockers. When delegation is authorized for the task, pass the project root, item ID, role, bound attempt/input identity, code workdir and required original instruction paths. The trusted coordinator captures actual host spawn/result receipts and native worker identity rather than accepting worker-authored execution claims; an optional host `call_id` must be actually observable. Pass returned `approved_contract` to derived-design reviewers for comparison with the original approved requirement/spec/decision. Each reviewer starts from the returned current inputs and primary repository evidence; do not load obsolete review files or treat another review's conclusions as evidence of an assessment. Code commands use an explicit code workdir and that repository's applicable instructions. A project metadata checkpoint cannot authorize extra source writes, remote deletion or takeover.

known-limit: local serialization uses Unix `flock`; native Windows requires equivalent cross-process locking and concurrency validation before writes are enabled.
