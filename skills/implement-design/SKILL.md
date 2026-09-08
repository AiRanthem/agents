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
- Treat in-scope local edits and non-destructive checks as authorized, subject to the type approvals below.
  External writes, deployment, destructive actions, new dependencies, and material scope expansion require
  user authorization; apply authorization already given in the conversation without asking again.
- Do not create or modify plans, task files, OpenSpec artifacts, ADRs, or unrelated documentation unless the
  user explicitly requests it.
- Do not modify `AGENTS.md`, `CLAUDE.md`, or another repository-level instruction file without explicit user
  approval in the current conversation. Put durable, local design reasoning in code comments. If comments
  cannot carry an important explanation, explain the need and ask before changing repository instructions.

Ask before adding or reshaping a data structure unless the user has already approved that change and its
shape, directly or in the confirmed design. A general implementation request alone does not approve an
unspecified shape. This applies to:

- adding any named structure, class, interface, protocol, enum, union, or type alias;
- adding, removing, or changing fields, methods, variants, or inheritance of an existing type;
- adding or changing a public, stored, wire, configuration, or database schema.

Explain why the change is needed, what existing type or simpler representation was considered, and the
smallest proposed shape. Local variables and ordinary anonymous values do not need approval, but do not use
them to hide a type or schema that should be explicit.

Implement deliberate differences between the current code and the confirmed target state. Stop before an
affected change when the design is still an unapproved draft, lacks a necessary product decision, has a
decision-changing open question or translation conflict, or repository evidence makes the intended contract
unclear or infeasible. Also stop for a newly found breaking change or special release requirement not covered
by existing approval. Continue independent work that cannot constrain the pending decision.

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

When subagents are available and permitted, follow applicable routing instructions and honor explicit user
choices. Choose the least expensive available model and reasoning effort that can reliably meet the subtask's
quality bar. Account for coordination, wall-clock time, main-agent context, and total token use.

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

- Use a read-only subagent to challenge scope, missed paths, and assumptions when unresolved ambiguity or
  cross-boundary risk warrants it. Resolve decision-changing findings before affected edits; independent
  authorized work may continue.
- Require an independent read-only review for changes with material risk to public contracts, stored data,
  concurrency, security, compatibility, or release safety, and when repository instructions require it.
  Otherwise delegate review when it improves confidence or saves time or context enough to justify its cost;
  touching multiple files alone does not require delegation. Review after writers and focused tests finish,
  against a stable implementation. Ask the reviewer to compare the design, final diff, and tests for
  correctness, omissions, extra scope, readability, minimality, coverage, and warnings, and to state evidence,
  uncertainty, and unexamined areas.
- Re-review the affected area after material fixes. Skip delegation for small work when coordination costs
  more than doing and checking it directly.

A subagent report is a second perspective, not completion proof. The main agent reviews the final diff and
checks that validation evidence covers the final state; it need not repeat valid delegated checks.

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

Choose the test and implementation order that makes the work clearest. Use existing tests when they already
detect meaningful violations of the design; add the smallest regression check for uncovered non-trivial
behavior. Do not add tests that merely mirror a reversible, low-impact edit.

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

Before claiming completion, ensure build, test, formatting, generation, and static-check evidence covers the
final state to the extent required by the change's risk and repository rules. Read command exit statuses and
output. Reuse results from this task when the checked code, dependencies, configuration, and relevant
environment remain unchanged. Repeat or broaden checks only for subsequent changes, failures, or unresolved
concerns that invalidate or exceed that evidence. If an essential check cannot run, report the exact gap and
do not describe the implementation as fully verified.

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
