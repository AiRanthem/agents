---
name: receiving-code-review
description: Evaluate code-review feedback against the current contract and code. Use when explicitly requested or assigned within an authorized review-feedback task. Apply supported corrections within existing fix authorization and return evidence for independent re-review.
---

# Receiving Code Review

Turn comments into evidence-backed dispositions and corrections. Feedback is a claim to evaluate, not authority to expand the contract. Receiving comments or requesting an assessment may authorize evaluation alone; an existing implementation/fix scope or a request to fix authorizes supported corrections within that scope. Reuse that authorization without another accepted-target confirmation each round. External replies and thread resolution require explicit authorization.

## Load context and establish the target

Read [discussion and authorization](../../references/discussion-and-authorization.md). For a managed work item, follow the project workflow selected by `$implement-design` for authorized corrections.

Identify the comment revision, approved contract and current target, including relevant staged, unstaged and untracked changes. Inspect affected flows, callers, tests and compatibility evidence before deciding. Reuse prior decisions and unaffected valid verification.

## Evaluate and act within authorization

For each material comment, reconstruct the claim and classify it as fully accepted, partially accepted or rejected against current evidence. If evidence or a material decision is missing, mark it unresolved; uncertainty is not rejection. Already addressed describes implementation state, not disposition. Correct prior disagreement when new evidence changes the conclusion. Missing repository references alone do not prove a feature is unused in production.

Make the following clear in the evaluation and final handoff:

- Rejected comments or portions: the exact rejected claim, evidence, reasoning and practical boundary. Do not invent rebuttals to fully accepted comments.
- Accepted portions: concrete observable correction targets, relevant constraints/non-goals and whether current code already satisfies them. Exclude rejected portions.
- Unresolved comments: missing evidence or the exact user decision and its consequences.

Within an authorized implementation or fix scope, apply supported accepted targets directly. Internal implementation and private type choices belong to the executor. Changes to requirements, public or stored contracts, compatibility, key constraints, approved safety/correctness guarantees, acceptance criteria or explicit tradeoffs require the user's decision through the applicable owner. First investigate, combine related questions and reuse existing decisions; pause only dependent corrections while independent authorized work continues. Silence or elapsed time does not authorize a change.

If authorization covers evaluation alone, finish the evidence-backed evaluation before requesting the specific edit authorization still needed. Do not imply that every review round requires confirmation. If no accepted target needs code changes, report that outcome without starting implementation.

## Correct and return evidence

Use `$implement-design` in the current conversation for authorized corrections, supplying accepted targets as the correction contract, supporting evidence, current target identity and rejected boundaries. Do not ask the user to invoke it separately or reconfirm unchanged targets. It owns decomposition, implementation self-review and verification.

If implementation reveals a material contract defect, return the evidence and proposed correction to the applicable decision owner and continue independent authorized work. Review findings do not authorize extra features or weaker acceptance criteria.

Report dispositions, already-satisfied targets, changes, actual checks, unresolved decisions and remaining uncertainty. Include the current dirty artifact identity and evidence needed for independent re-review. Fix completion does not establish independent implementation acceptance; return after the assigned corrections and affected behavior are addressed. For authorized external replies, follow the [PR thread reply rules](../maintain-prs/SKILL.md#交付与收尾) to check for existing replies before posting and verify the resulting thread state.
