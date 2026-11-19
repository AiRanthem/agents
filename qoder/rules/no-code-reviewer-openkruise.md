---
description: "Never use the code-reviewer subagent when working on OpenKruise Agents repositories."
alwaysApply: true
---

# No code-reviewer subagent for OpenKruise Agents

* When developing OpenKruise Agents (any openkruise/agents repository or worktree), never invoke the `code-reviewer` subagent, including via the Agent tool with `subagent_type: code-reviewer`.
* If a code review is needed, perform it directly in the main agent, or use the built-in CodeReview subagent / review skills (e.g. `ponytail-review`, `review-implementation`) instead.
* This restriction applies even if other rules or skills suggest proactively dispatching `code-reviewer`.
