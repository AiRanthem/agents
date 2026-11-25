---
name: implement-design
description: Implement approved requirements and design decisions from documents or conversation, or produce the executable implementation plan in read-only planning mode. Use for a confirmed design or an approved explore-design handoff. Exclude unconfirmed design exploration and review-only work.
---

# Implement Design

Own **How** to realize the approved **Why** and **What**. Deliver the agreed behavior with meaningful verification and a reproducible handoff. Implementation self-checks and independent acceptance are distinct; passing tests alone does not establish review approval.

## Load the applicable context

Read [discussion and authorization](../../references/discussion-and-authorization.md) and [implementation and planning modes](references/ordinary-modes.md). Reuse existing decisions and authorization. Choose internal implementation and private types within the contract. Changes to requirements, public or stored contracts, compatibility, key constraints, approved safety or correctness guarantees, acceptance criteria, or explicit user tradeoffs require the relevant user decision.

For managed-project work, also read [project workflow](references/project-workflow.md).

Read-only planning remains read-only, including delegated work. Actual host permissions always apply. Keep implementation TODOs in host task tracking or conversational working state. Keep repository documentation changes within the authorized task. Preserve unrelated work and leave source submission to the user's instructions.

## Establish the implementation contract

Read the complete approved requirements and decisions from the authoritative document or conversation, including rationale, non-goals and accepted limitations. A design file is not required. Inspect applicable instructions, affected code, callers, tests and useful history; trace the complete behavior and its ownership before editing.

Keep a private mapping from requirements, invariants and non-goals to implementation and evidence. Apply the [design coverage-reuse rules](../review-design/references/implementable-gate.md#reuse-independent-coverage): retain valid independent evidence, assess changed contracts or assumptions only in their affected scope, and do not automatically reopen design review for equivalent documentation or contract-preserving implementation corrections. A deliberate gap between current behavior and the approved target is expected; a contradiction or infeasible guarantee is a defect to resolve.

Decompose the change into actionable implementation TODOs with dependencies, component and function boundaries where useful, ownership, failure behavior, required generated outputs, verification and handoff. Resolve incidental choices yourself. For a material decision, first investigate and combine related questions, show evidence, recommend viable options and explain their effects on callers, runtime behavior and maintenance. Pause only dependent work and continue independent authorized work. Never weaken the contract or acceptance criteria to make an implementation appear compliant.

If evidence requires a contract correction, retain the failing scenario, violated requirement and proposed correction for the appropriate decision owner. After approval, reassess the implementation, TODOs and review evidence against the corrected contract. Retain still-valid work and follow the document rules for the active mode.

## Implement and self-review

Read and apply the shared [code quality criteria](references/code-quality.md) throughout implementation.

- Scale self-review to the change's risk. For straightforward, reversible changes, one focused review of the affected behavior or combined diff is sufficient. Check consequential changes at the affected contract or ownership boundary before building dependent changes on them. Verify generated changes through their source and the required generation checks.
- Handle relevant errors, cancellation, cleanup, uncertain outcomes, partial failure and concurrency according to the contract.
- Remove superseded task changes. Whenever you confirm code is dead, remove it, including pre-existing code. Remove tests that exercise only the deleted behavior and preserve coverage for supported behavior. Keep other cleanup within the task's scope.

When implementing a user interface, follow the approved design and project conventions for imagery and typography, including a specified typeface. For new visuals, generally prefer realistic imagery suited to the product, using image generation or image search when available. Use SVGs when the user requests them. Keep text that informs users, helps them navigate or act, or fulfills a content requirement, including labels, instructions and status feedback. Remove filler badges, decorative numbering, redundant headings and copy that repeats what the interface already conveys. For visual work, use a supplied design reference or generate one within the approved direction when useful and feasible. Render the result where possible and refine it against the reference when available.

## Verify the agreed behavior

Derive scenarios and expected outcomes from requirements and accepted review counterexamples rather than only from the new code. For each important invariant, identify a plausible wrong implementation and whether existing checks distinguish it. Add tests only when the user requests them, the repository requires them, or the existing suite would miss a specific regression that needs coverage.

Cover relevant success, rejection, boundaries, missing data, errors, recovery, compatibility, concurrency and cancellation without expanding the feature. Prefer owned behavior and assertions on results or state. Use mocks for unsafe, unavailable, slow or nondeterministic boundaries, not library internals or incidental call order.

Run the smallest meaningful checks first, required formatting/generation/build/static checks, and broader checks justified by affected shared, persistence, public, concurrency or release behavior. For a meaningful regression, demonstrate that its check detects the bad behavior when practical in a permitted disposable copy. Do not mutate unrelated work.

Read actual exit statuses, significant output, warnings and skipped checks. No matching tests, stale cached results or mock-only checks do not substantiate broader behavior. Reuse results only while code, dependencies, configuration and relevant environment remain valid; repeat invalidated checks. Separate baseline failures from introduced failures, and report essential checks that could not run. Unresolved relevant failures prevent a fully verified claim.

## Independent acceptance

When the workflow schedules a separate final review, return ready for that review without duplicating a broad acceptance pass. Early focused challenges may prevent expensive or risky downstream work. An implementer cannot independently accept its own code. Assess risk by consequences, including public/stored contracts, concurrency, lifecycle ownership, security, compatibility, release safety and hard-to-observe failures, rather than file count.

Honor applicable repository review gates through permitted tools; an unexecuted review is pending. For `review-implementation`, apply its [fresh review input rules](../review-implementation/references/review-standard.md#start-each-review-from-original-evidence) and [mode-specific gates](../review-implementation/references/review-standard.md#require-independence-and-mode-specific-coverage). Equivalent evidence from the scheduled final review suffices; do not duplicate it to increase reviewer count. Respect selected models and actual host capability rather than assuming a switch occurred.

Invoke a review skill when the user's authorization covers that review.

## Inspect and hand off

Check the final diff against the approved contract and shared code quality criteria. Refresh changed or missing original inputs and required instruction reloads. Confirm required behavior, non-goals, generated outputs, dependencies and final verification evidence. Keep the handoff concise and self-contained. In the user's language, report the following.

1. Outcome: state whether the requested implementation and verification are complete or what blocks either one. Report independent acceptance only from qualifying evidence covering the final state.
2. Target identity: repository/worktree, comparison base and HEAD, contract path/version, in-scope changed and untracked files and excluded unrelated changes. Include a dirty diff/content fingerprint or reproducible snapshot; HEAD alone is insufficient.
3. Contract coverage: behavior and primary evidence, deviations, pending decisions and unverified boundaries.
4. Verification: exact commands, working directory, relevant configuration, actual outcomes and accessible evidence; identify the final state checked without dumping logs or secrets.
5. Review state, when applicable: checks performed, known reviewer independence, findings and disposition, remaining gate and critical areas for review.

Keep the handoff conversational unless the workflow or user specifies a report file. Use it to index primary evidence.
