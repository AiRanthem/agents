---
name: explore-design
description: Explore feasibility, vague ideas, concrete requirements, or existing documents and create or refactor a repository-aware design that anchors later implementation and review. Use when explicitly invoked with $explore-design or when the user clearly requests a pre-implementation design document. Do not trigger for ordinary discussion, implementation plans or code, OpenSpec or ADR authoring, or post-hoc documentation.
---

# Explore Design

Resolve the direction of a development change before implementation. Produce a design that explains
why the change matters and precisely describes the intended end state. Do not turn the design into
an implementation plan.

## Boundaries

- Remain read-only while exploring. Read repository instructions, code, documentation, history, and
  external sources when they help establish facts.
- Write only the exact design-document paths the user approves. Never edit code, tasks, OpenSpec
  artifacts, or unrelated documentation while this skill is active.
- Treat code and implementation history as research evidence, not as the design's subject.
- Ask before a material scope change or any document write not covered by the user's approval.
- If the user also asks for implementation, finish or exit the design work first. Do not implement
  from this skill.

## Explore and converge

Treat exploration as a thinking stance, not a fixed questionnaire.

- Ground the discussion in the actual repository when one exists. Trace relevant behavior end to
  end, find existing patterns and constraints, and distinguish verified facts from assumptions.
- Accept vague ideas, feasibility questions, abstract goals, concrete requirements, and existing
  design documents as valid starting points.
- Clarify the problem, desired outcome, scope, constraints, affected users or systems, viable
  alternatives, risks, and unknowns. Ask only questions whose answers can change the direction.
- Challenge assumptions and compare meaningful options. Recommend a direction only when the
  evidence supports it.
- Use diagrams or comparison tables during exploration when they make relationships, flows, states,
  or tradeoffs easier to understand.
- Allow stable, long-lived facts about the existing system in the final Background when they are
  needed to explain the problem. Keep transient code snapshots, superseded models, implementation
  history, and migration narratives out of the design.

Do not start writing merely because a plausible approach exists. First make the important decisions
explicit. If a material question remains unresolved, allow an Open Questions section, explain its
impact, and mark the document as a draft. Do not describe that design as complete or ready for
implementation.

## Confirm the artifact

Inspect repository conventions before suggesting a title or path. Check applicable instruction
files, existing design or proposal directories, templates, metadata, naming patterns, and nearby
documents. OpenSpec material may be read as context but must not be created or modified.

Present the proposed scope and exact target paths, then obtain user confirmation before writing.
When no repository or convention exists, ask the user to confirm the destination and base name.

Apply these language rules:

- For a new design, create `<base>-EN.md` and `<base>-CN.md`. Write natural English and natural
  Simplified Chinese rather than literal translations.
- Keep both versions semantically equal. Decisions, constraints, diagrams, tables, open questions,
  and draft status must match; neither version is authoritative over the other.
- When updating an existing EN/CN pair, update both. If repository state or the user shows that one
  version was deliberately deleted, preserve the deletion and update only the remaining version. If
  the reason for absence is unclear, ask.
- Update an existing unsuffixed, single-file design in place. Do not rename it or create a bilingual
  pair merely because this skill was invoked.
- Follow repository formatting and metadata conventions. Otherwise use the conventions of the
  document's language.

## Author the design

Every design requires these top-level sections:

1. **Summary / 摘要** — Place it first but write it last. Let a reader understand the problem,
   direction, and end state in under one minute.
2. **Background / 背景** — Explain the problem, benefits, and significance: the Why.
3. **Target Design / 设计终态** — Describe the complete intended system after the change: the What.

Add other top-level sections only when they improve the design. Alternatives, Risks, and Open
Questions are valid when they carry material information. Do not force empty sections or a fixed
template beyond the three required sections.

Make Target Design precise enough to anchor both implementation and review. As applicable, define:

- scope and non-goals;
- responsibilities and system boundaries;
- component relationships, state transitions, and data flows;
- externally visible behavior and interface contracts;
- invariants, failure behavior, and behavior under missing or uncertain information;
- compatibility, security, operational, and data-protection constraints.

These are end-state contracts, not implementation instructions. A sequence that describes runtime
behavior is allowed; a sequence of development tasks is not.

Exclude file-by-file changes, function or class lists, pseudocode chosen only for implementation,
task breakdowns, migration procedures, rollout steps, test plans or commands, implementation status,
and implementation history.

An implementation agent may later add a separate **Implementation Notes / 实现注意事项** section
when it discovers a constraint that must remain attached to the design, such as a special production
upgrade requirement or a breaking change. Keep that section limited to information affecting safe
release, compatibility, or the design boundary. Do not use it as a work log, task list, or progress
report. Keep it synchronized across both language versions that still exist.

## Write for humans

- Put human readability first in presentation and end-state precision first in content.
- Prefer ordinary words. Explain an unavoidable project term the first time it appears. Do not use
  unexplained shorthand, fashionable labels, or compressed state expressions that make readers
  decode the prose.
- Lead with the user-visible promise and the overall picture before detailed rules.
- Use tables for repeated mappings or comparisons. Use diagrams for architecture, ownership,
  sequences, data flow, or state changes when prose alone is harder to follow. Do not add decorative
  visuals.
- State each rule once. Remove repetition, generic praise, and historical narration that does not
  support Why or What.
- Preserve important facts, decisions, caveats, boundaries, and unknowns when shortening text.

## Validate and stop

Before reporting completion:

- Re-read the design against the confirmed decisions and research evidence.
- Confirm that required sections exist, the Summary was written after the rest, and optional
  sections contain material information.
- Confirm that the target state is specific enough for a reviewer to detect missing, incorrect, and
  out-of-scope implementation.
- Confirm that no implementation plan, migration narrative, transient snapshot, or unexplained
  jargon leaked into the design outside the narrow Implementation Notes exception.
- For a bilingual pair, compare every decision, constraint, table, diagram, open question, and status
  for semantic equality.
- Run only narrow documentation checks that are relevant to the files. Do not run application tests
  merely because a design document changed.

Report the written paths, draft or complete status, unresolved questions, and actual validation.
Do not propose an implementation plan, an implementation prompt, or a next-step workflow.
