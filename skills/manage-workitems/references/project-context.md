# Project context and routing

A management project is the selected workspace containing its configuration, instructions and work-item records. A nested source repository keeps its own scope. Read the project's `AGENTS.md`, configuration and affected documents directly. Existing YAML or JSON records are usable working inputs.

For business/code work, locate the actual main workspace and source repository and read their original instructions. Reuse covering authorization. Reading requirements alone does not request design, decomposition or implementation. Read-only tasks remain read-only.

| Requested task | Skill |
| --- | --- |
| Progress, requirements, metadata or archive updates | [manage-workitems](../SKILL.md) |
| A separate project workspace | [create-project](../../create-project/SKILL.md) |
| Refresh project layout or instructions | [upgrade-project](../../upgrade-project/SKILL.md) |
| Split a reviewed design into separately managed child items | [manage-workitems](../SKILL.md) |
| Requested design or implementation | [develop-workitem](../../develop-workitem/SKILL.md) |
| Acceptance, delivery or separately requested cleanup | [complete-workitem](../../complete-workitem/SKILL.md) |
| Remove a selected local project | [delete-project](../../delete-project/SKILL.md) |

Resolve selectors from actual records and report full IDs/titles, such as `123-quota-lock（统一配额锁）`. Ask only when the intended target remains ambiguous. Hierarchy describes decomposition; dependencies describe prerequisites.

Use [schema](schema.md) for locations, [workflow](workflow.md) for progress, [main-workspace association](main-workspace.md) for external context and [persistence](persistence.md) for commit/push behavior. Project knowledge can remain useful independently of an item.
