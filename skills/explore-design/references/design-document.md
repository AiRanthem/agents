# Agent-mode design document

Read and apply this reference only in Agent mode, after identifying the active host mode. It does not apply to Plan-mode discussion, approval, or implementation planning.

## Confirm the path

Inspect applicable instructions, design directories, templates, metadata, naming patterns, and nearby documents. Reuse an already-approved exact path; otherwise obtain path approval together with the Why/What contract. Repository conventions inform the proposed path, not authorization.

- New designs use `<base>-CN.md`, in natural Simplified Chinese.
- Update the Chinese member of an existing pair without changing its English counterpart. Do not claim the pair is synchronized; meaning-changing differences must be resolved before implementation.
- Update an existing unsuffixed single-file design in place. Preserve its name and single-file form.
- Follow repository formatting and metadata conventions, otherwise the conventions of the document's language.
- Write only approved design paths. Delegate writing only within those paths with non-overlapping ownership, and verify the resulting text yourself.

## Record the approved contract

Use these top-level sections:

1. **摘要** — first in the document, written last; explain the problem, direction, and end state in under one minute.
2. **背景** — the problem, benefits, and significance: Why.
3. **设计终态** — the complete intended system after the change: What.

Add Alternatives or Risks only for material content. An explicitly requested draft may include Open Questions and must be labeled unapproved and incomplete. A normal completed document records settled decisions, with observable behavior, ownership, boundaries, invariants, failure outcomes, rationale, and accepted limitations as applicable.

Stable facts about the existing system may explain the background. Keep transient snapshots, superseded designs, implementation history, and migration narratives out of the contract. Examples describe runtime outcomes, not test commands.

Implementation TODOs, file-by-file edits, pseudocode, migration procedures, rollout steps, and verification plans belong to `$implement-design`. A later implementation agent may add approved **Implementation Notes / 实现注意事项** only for essential release, compatibility, or design-boundary constraints; this section must not become a task list or work log.

## Validate

Re-read against the approved requirements and decisions. Confirm the three sections, natural Simplified Chinese, observable target-state precision, and absence of implementation-process content. Check that only approved Chinese paths were written and run relevant narrow documentation checks. Report draft status or any remaining language-pair inconsistency honestly; document completion does not establish independent review or implementation.
