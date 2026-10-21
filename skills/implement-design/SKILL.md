---
name: implement-design
description: Implement approved requirements and design decisions from documents or conversation, or produce the executable implementation plan in read-only planning mode. Use for a confirmed design, an approved explore-design handoff, or an assigned autonomous implementation stage. Exclude unconfirmed design exploration and review-only work.
---

# Implement Design

Own **How** to realize the approved **Why** and **What**. Deliver the agreed behavior with meaningful verification and a reproducible handoff. Implementation self-checks and independent acceptance are distinct; passing tests alone does not establish review approval.

## Load the applicable context

Always read [discussion and authorization](../advance-project/references/discussion-and-authorization.md). Reuse existing decisions and authorization; decide internal implementation and private type choices within the contract. Changes to requirements, public or stored contracts, compatibility, key constraints, approved safety or correctness guarantees, acceptance criteria, or explicit user tradeoffs require the relevant user decision.

- **Autonomous stage executor:** Read [stage executor](../advance-project/references/stage-executor.md) and [implementation stage](references/autonomous-stage.md). Follow the assigned single-stage scope; ordinary project commands and model-routing guidance do not apply.
- **Ordinary managed-project development:** Read [project workflow](references/project-workflow.md) and [ordinary modes](references/ordinary-modes.md).
- **Other implementation or read-only planning work:** Read [ordinary modes](references/ordinary-modes.md).

Read-only planning remains read-only in every organization mode, including delegation. Actual host permissions always apply. Keep implementation TODOs in host task tracking or conversational working state; do not create generic task files or unrelated documentation. Preserve unrelated work and leave source submission to the user's instructions.

## Establish the implementation contract

Read the complete approved requirements and decisions from the authoritative document or conversation, including rationale, non-goals and accepted limitations. A design file is not required. Inspect applicable instructions, affected code, callers, tests and useful history; trace the complete behavior and its ownership before editing.

Keep a private mapping from requirements, invariants and non-goals to implementation and evidence. Apply the [design coverage-reuse rules](../review-design/references/implementable-gate.md#reuse-independent-coverage): retain valid independent evidence, assess changed contracts or assumptions only in their affected scope, and do not automatically reopen design review for equivalent documentation or contract-preserving implementation corrections. A deliberate gap between current behavior and the approved target is expected; a contradiction or infeasible guarantee is a defect to resolve.

Decompose the change into actionable implementation TODOs with dependencies, component and function boundaries where useful, ownership, failure behavior, required generated outputs, verification and handoff. Resolve incidental choices yourself. For a material decision, first investigate and combine related questions, show evidence, recommend viable options and explain their effects on callers, runtime behavior and maintenance. Pause only dependent work and continue independent authorized work. Never weaken the contract or acceptance criteria to make an implementation appear compliant.

If evidence requires a contract correction, retain the failing scenario, violated requirement and proposed correction for the appropriate decision owner. After approval, reassess the implementation, TODOs and review evidence against the corrected contract; retain still-valid work. Apply document and stage boundaries from the selected reference.

## Implement and self-review

Apply governing code-quality criteria to the complete resulting diff against the task's integration baseline, including accumulated changes. Reuse suitable mechanisms; remove superseded task changes when that produces a smaller coherent result without sacrificing correctness, readability, ownership or maintainability.

- Immediately after writing or modifying each function, self-review it before continuing. Stop when it satisfies the contract, is clear to read and has no evident unnecessary complexity.
- Respect repository placement, naming, ownership and dependency direction. Explain reasons, invariants and non-obvious failure or compatibility behavior in comments.
- Handle relevant errors, cancellation, cleanup, uncertain outcomes, partial failure and concurrency according to the contract.
- Avoid unrelated cleanup, formatting, renaming, dependencies and generated churn. Add compatibility logic only for an established need supported by the approved contract or relevant evidence.

## Verify the agreed behavior

Derive scenarios and expected outcomes from requirements and accepted review counterexamples rather than only from the new code. For each important invariant, identify a plausible wrong implementation and whether existing or new checks distinguish it. Meaningful existing tests can suffice; do not add redundant tests for trivial reversible edits.

Cover relevant success, rejection, boundaries, missing data, errors, recovery, compatibility, concurrency and cancellation without expanding the feature. Prefer owned behavior and assertions on results or state. Use mocks for unsafe, unavailable, slow or nondeterministic boundaries, not library internals or incidental call order.

Run the smallest meaningful checks first, required formatting/generation/build/static checks, and broader checks justified by affected shared, persistence, public, concurrency or release behavior. For a meaningful regression, demonstrate that its check detects the bad behavior when practical in a permitted disposable copy. Do not mutate unrelated work.

Read actual exit statuses, significant output, warnings and skipped checks. No matching tests, stale cached results or mock-only checks do not substantiate broader behavior. Reuse results only while code, dependencies, configuration and relevant environment remain valid; repeat invalidated checks. Separate baseline failures from introduced failures, and report essential checks that could not run. Unresolved relevant failures prevent a fully verified claim.

## Independent acceptance

When the workflow schedules a separate final review, return ready for that review without duplicating a broad acceptance pass. Early focused challenges may prevent expensive or risky downstream work. An implementer cannot independently accept its own code. Assess risk by consequences, including public/stored contracts, concurrency, lifecycle ownership, security, compatibility, release safety and hard-to-observe failures, rather than file count.

Honor applicable repository review gates through permitted tools; an unexecuted review is pending. For `review-implementation`, apply its [resolved mode-specific gates](../review-implementation/references/review-standard.md#require-independence-and-mode-specific-coverage): high-risk acceptance needs a lead qualified for the critical boundary in either mode; an additional independent targeted perspective is required only in `multi-agent`. Equivalent evidence from the scheduled final review suffices; do not duplicate it to increase reviewer count. Respect selected models and actual host capability rather than assuming a switch occurred. After material fixes, review the affected rule, callers and shared assumptions; broaden only when prior conclusions became invalid.

Do not automatically invoke an explicit-only review skill unless the user or applicable project workflow authorizes it. Autonomous executors return their own stage result to the controller, which assigns the independent review stage.

## Inspect and hand off

Check the final diff against the complete contract already in context; refresh changed or missing original inputs and required instruction reloads. Confirm per-function self-review, required behavior, non-goals, simplicity, dead code, stale comments, generated outputs, dependencies and final verification evidence. Report concisely in the user's language:

1. Outcome: ready for independent review, verification blocked, or decision needed; claim independent acceptance only from actual qualifying evidence covering this final state.
2. Target identity: repository/worktree, comparison base and HEAD, contract path/version, in-scope changed and untracked files and excluded unrelated changes. Include a dirty diff/content fingerprint or reproducible snapshot; HEAD alone is insufficient.
3. Contract coverage: behavior and primary evidence, deviations, pending decisions and unverified boundaries.
4. Verification: exact commands, working directory, relevant configuration, actual outcomes and accessible evidence; identify the final state checked without dumping logs or secrets.
5. Review state: checks performed, known reviewer independence, findings and disposition, remaining gate and critical areas for review.

Keep the handoff conversational unless the workflow or user specifies a report file. It indexes primary evidence; it does not replace the design or repository. Autonomous stage output also follows the supplied result identity and report contract.
