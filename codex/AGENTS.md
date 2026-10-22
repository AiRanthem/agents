# Response

* Unless explicitly requested otherwise, respond in Simplified Chinese.

# Plan Mode

* Do not propose a plan unless the user has explicitly permitted it.

# Skill authority

* Explicit user instructions take precedence over skill guidelines. Apply existing authorization from the conversation without asking again; authorization remains limited to its approved scope and does not bypass harness permissions.
* Before requesting new approval, complete independent, already-authorized work needed to make the decision concrete and reviewable.
* If a skill causes a permission request, pause, or incomplete result, name and link to its `SKILL.md`, quote the relevant instruction, and distinguish an explicit requirement from your interpretation.

# Code quality

* Understand the affected flow and callers before editing; fix root causes at their ownership boundary.
* Choose clear, maintainable code that satisfies the approved contract. Within those requirements and quality constraints, minimize the final PR: assess the complete resulting diff against the task’s established integration baseline, including accumulated changes. Optimize the final state rather than the size of each edit or repair; replace intermediate approaches and remove superseded task changes when that produces a smaller coherent result. Reuse suitable existing mechanisms and avoid complexity without a concrete benefit. Retain broader changes when needed for correctness, readability, ownership, or maintainability; do not trade these away for fewer changed lines or files. Preserve unrelated user changes.
* Add compatibility logic only for an established need. Cite the approved contract or relevant history, release, schema, or runtime evidence; distinguish code history from observed production data.
* Preserve correctness, trust-boundary validation, security, data protection, accessibility, real-hardware calibration, and explicit requirements. Verify non-trivial logic with the smallest meaningful runnable check; trivial reversible edits need no new tests.
* Document a deliberate shortcut's known ceiling and upgrade path in a nearby `known-limit:` comment.

# Subagent context reuse

* When subagents share substantial original material, prefer native full-context forks (`fork_turns: "all"`) for eligible same-model/same-effort assignments. Append each assignment's scope without recopying inherited originals.
* Preserve user model and role choices and permissions. Use clean dispatch when inherited history is unrelated or full-context reuse is unavailable. Record any fallback and claim cache savings only from actual usage evidence.

# Native entry bindings

* Resolve this instruction file's physical repository directory and use its `project.py` for project commands; it supplies the stable identity from `CODEX_THREAD_ID` or `PROJECT_SESSION_ID` and preserves that entrypoint in returned continuations. Do not generate a new identity or substitute a worker ID.
* Before starting `advance-project`, load this directory's `AUTONOMY.md` and supply its role bindings, configuration evidence, project command entrypoint and permission limits to the shared controller. Other shared skills remain platform-neutral.
* For an authorized installation request, load this directory's `INSTALL.md` and supply it alongside the shared installation contract. Native skill entries own invocation policy and UI metadata; their shared sources remain the business contract.

# Execution mode binding

* Map active native Plan to the shared read-only planning contract, and Agent to ordinary execution subject to actual permissions. A request mentioning a plan or a permission failure does not switch modes. Use a `proposed_plan` block only for the sole settled implementation plan; questions and approval requests remain conversational.
