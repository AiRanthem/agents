---
name: implement-design
description: Implement a confirmed design document completely and exactly in an existing repository, with code, tests, generated outputs, and local verification. Use explicitly with $implement-design or implicitly only when the user clearly asks to implement a named or already-confirmed design, such as "implement docs/design/foo-EN.md". Do not trigger for ordinary coding, fixes, refactors, design work, planning, OpenSpec or ADR authoring, review-only work, or post-hoc documentation.
---

# Implement Design

Implement the confirmed design as the smallest complete change. Treat the design as the contract: implement
every required behavior, add nothing outside it, and leave fresh evidence that the result works.

## Authority and approval boundaries

- Stay in the current harness mode. Plan mode may require an approved plan before edits; Default mode may
  implement directly. Do not require a plan when neither the mode nor the user requires one.
- Read and follow all repository instructions that apply to the files in scope. Preserve unrelated and
  pre-existing work.
- Treat in-scope local edits and non-destructive checks as authorized. Ask before external writes, deployment,
  destructive actions, new dependencies, or a material expansion of scope.
- Do not create or modify plans, task files, OpenSpec artifacts, ADRs, or unrelated documentation unless the
  user explicitly requests it.
- Do not modify `AGENTS.md`, `CLAUDE.md`, or another repository-level instruction file without explicit user
  approval in the current conversation. Put durable, local design reasoning in code comments. If comments
  cannot carry an important explanation, explain the need and ask before changing repository instructions.

Ask for approval before adding or reshaping a data structure. This includes:

- adding any named structure, class, interface, protocol, enum, union, or type alias;
- adding, removing, or changing fields, methods, variants, or inheritance of an existing type;
- adding or changing a public, stored, wire, configuration, or database schema.

Explain why the change is needed, what existing type or simpler representation was considered, and the
smallest proposed shape. Local variables and ordinary anonymous values do not need approval, but do not use
them to hide a type or schema that should be explicit.

Stop before an affected change when the design is a draft, has a decision-changing open question, conflicts
with the code or its paired translation, or lacks a necessary product decision. Also stop for a newly found
breaking change or special release requirement. Continue only with independent work that cannot constrain the
pending decision.

If a breaking change, compatibility boundary, or special production upgrade must remain attached to the
design, propose a narrow `Implementation Notes` / `实现注意事项` entry. Write it only after approval, keep it
free of tasks and progress history, and give both surviving language versions the same meaning. Never change
the design merely to make an implementation deviation appear compliant.

## Establish the contract from evidence

Read the named design completely before editing code.

- For an `-EN.md` and `-CN.md` pair, find and read both files and treat them as equal. Preserve a counterpart
  that the user deliberately deleted. If the two files differ in a way that affects implementation, ask which
  contract is intended.
- Inspect the relevant code, tests, repository conventions, and history when useful. Trace the behavior end
  to end, including callers, responsibility boundaries, state and data flow, error paths, and existing shared
  patterns.
- Keep a private checklist that maps every design rule and non-goal to code and evidence. Use it to prevent
  missing or extra work. Do not create a repository task file or present a plan unless the user asks.

## Orchestrate with subagents

When subagents are available and permitted, consider every available agent, model, and reasoning-effort
combination, including Sol, Terra, Luna, and future choices. Honor an explicit user choice. Otherwise choose
the least expensive combination that can reliably meet the subtask's quality bar, then optimize wall-clock
time, main-agent context, and total token use. Evaluate the model and effort together rather than fixing one
first.

- Use current capability descriptions as routing evidence, not a permanent table. Prefer a low-cost agent for
  bounded research, documentation lookup, commands, output reduction, and mechanical edits; a balanced agent
  for contextual repository work; and the strongest justified agent for difficult or high-risk independent
  review.
- Delegate only work that is independent, clearly bounded, and cheaper to summarize than to keep in the main
  context. Run unrelated research, tests, builds, static checks, and disjoint low-risk edits in parallel when
  this shortens the critical path. Give writing agents non-overlapping file ownership and never review a moving
  target.
- Give each subagent only the task-local context it needs, with exact scope, constraints, required evidence,
  stopping conditions, and return format. Avoid repeated repository scans and full-history forks.
- Keep design interpretation, user approval, data-structure decisions, architecture, security and business
  judgment, integration, critical test scope, and the completion decision with the main agent. The main agent
  reviews every delegated diff and verifies material conclusions against primary evidence.

Treat an implementation as non-trivial when it changes behavior across files or responsibility boundaries, or
affects a public contract, stored data, concurrency, security, compatibility, or release safety.

- For ambiguous, cross-boundary, or high-risk work, after mapping the affected flow and before editing it, use
  a read-only subagent to challenge the scope, missed paths, and assumptions. Resolve its findings before any
  writing agent starts.
- After all writers and focused tests finish, freeze the implementation and require a fresh, independent,
  read-only review for every non-trivial change. Ask it to compare the design, final diff, and tests for
  correctness, omissions, extra scope, readability, minimality, coverage, and warnings, and to state evidence,
  uncertainty, and unexamined areas.
- Re-review the affected area after material fixes. Skip delegation for small work when coordination costs
  more than doing and checking it directly.

A subagent report is a second perspective, not completion proof. The main agent still performs the final diff
review and fresh validation below.

## Write the smallest complete implementation

After understanding the whole affected flow, use the first option that fully satisfies the design:

1. no code change;
2. an existing implementation, type, or pattern;
3. the language standard library;
4. a native platform feature;
5. an installed dependency;
6. the minimum new code.

- Fix the root cause at the shared responsibility boundary instead of repeating patches in callers.
- Prefer deletion, plain control flow, few files, and a short diff. Avoid speculative flexibility, single-use
  abstractions, wrappers, factories, helpers, mocks, dependencies, and scaffolding.
- Keep ownership, dependency direction, naming, and file placement consistent with the repository. Make the
  code readable from top to bottom without clever indirection.
- Add concise comments for reasons, invariants, non-obvious constraints, compatibility, or failure behavior.
  Do not narrate syntax or copy the design into the code.
- Follow documented library and platform contracts. Handle errors, cancellation, cleanup, partial failure,
  uncertain input, and concurrency when the design or boundary requires them.
- Do not simplify away explicit requirements, trust-boundary checks, security, accessibility, data-loss
  prevention, or real-world calibration. Avoid unrelated formatting, renaming, cleanup, and generated churn.

Treat zero bugs, warnings, errors, and production incidents as the quality goal, not as a claim that evidence
cannot support. Any unresolved relevant failure prevents completion.

## Prove the behavior

Choose the test and implementation order that makes the work clearest. Finish with tests that fail for
meaningful violations of the design.

- Cover every visible rule and important invariant. Include relevant success, rejection, failure, missing
  data, limit, compatibility, concurrency, and recovery cases. Do not test imagined features outside scope.
- Reuse the repository's test structure. Prefer real implementations and assertions on results or state. Use
  fakes, stubs, or mocks only when the real boundary is unsafe, unavailable, slow, or non-deterministic.
- Test owned behavior rather than library internals or incidental call order. Avoid duplicate tests, broad
  snapshots, and fixtures that make review harder without adding confidence.
- Meet the repository's coverage gate. When tooling supports it, inspect line coverage for the changed scope
  and close meaningful uncovered branches. Do not use a universal percentage or add low-value tests to raise a
  number; business-rule coverage remains required even when line coverage is high.
- Run the narrowest useful checks first, then expand with the risk from public contracts, persistence,
  concurrency, shared packages, or release behavior. Run required formatting and generation commands. Do not
  run unrelated end-to-end suites by habit.

Before claiming completion, run fresh commands that prove the final tree builds, tests, formats, and passes
relevant static checks without new warnings or errors. Read their exit status and output. If an essential
check cannot run, report the exact gap and do not describe the implementation as fully verified.

## Check and report the result

Re-read the design and inspect the final diff as a reviewer:

- match every design rule to implemented behavior and evidence;
- confirm every non-goal and scope boundary remains untouched;
- confirm each approved type or schema change matches the agreed shape;
- remove duplication, dead code, unnecessary abstractions, stale comments, accidental churn, and tests that
  add no confidence;
- check generated outputs, dependency files, formatting, warnings, errors, and validation results.

Report the implemented outcome, changed paths, design coverage, checks actually run, coverage evidence when
available, and any blocker or unverified area. Distinguish pre-existing failures from failures introduced by
the change. Claim only what the evidence proves.
