---
name: develop-workitem
description: Prepare or resume requested design or implementation for one managed-project work item. Use for ordinary single-item development; route explicitly requested autonomous scope advancement to advance-project.
---

# Develop Work Item

Advance only the authorized development phase, keeping the session at the management project root and source operations in the exact code workdir. Read [discussion and authorization](../advance-project/references/discussion-and-authorization.md). Requirement creation alone does not authorize source investigation, design or implementation.

- **Ordinary single-item project development:** Read [ordinary development](references/ordinary-development.md) and use its program-owned worktree, ownership, independent review and delivery gates.
- **User requests continued autonomous advancement:** Use [advance-project](../advance-project/SKILL.md); the controller directly dispatches each stage and owns all project checkpoints. Do not add an item manager.
- **Already dispatched stage executor:** Read [stage-executor](../advance-project/references/stage-executor.md) and the assigned stage skill. Perform that one stage and return evidence; do not call project commands or edit formal project records.

Native Plan remains read-only for the controller and delegated work. Tests and AI review do not establish human acceptance, delivery or authorization to submit source. Preserve unrelated work and the runtime's actual blocked/recovery state.
