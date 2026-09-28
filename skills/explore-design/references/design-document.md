# Agent-mode design document

Read and apply this reference only in Agent mode, after identifying the active host mode. It does not apply to Plan-mode discussion, approval, or implementation planning.

## Confirm the path

Inspect applicable instructions, design directories, templates, metadata, naming patterns, and nearby documents. Reuse an already-approved exact path; otherwise obtain path approval together with the Why/What contract. Repository conventions inform the proposed path, not authorization.

- Maintain exactly one authoritative document per design, in one language. Use the user's requested language; otherwise preserve an existing document's language or use Simplified Chinese for a new design.
- New designs use `<base>.md` unless repository naming conventions apply. Update an existing design in place, preserving its approved path.
- Follow repository formatting and metadata conventions, otherwise the conventions of the document's language.
- Record `design_status: review-pending` in YAML frontmatter for a complete approved design, or `design_status: draft` for an explicitly requested unapproved draft. Revisions to a previously reviewed Why/What contract reset this field to `review-pending`; only `$review-design` may set it to `implementable` after independent review passes. Preserve unrelated frontmatter fields.
- Write only approved design paths. Delegate writing only within those paths with non-overlapping ownership, and verify the resulting text yourself.

## Record the approved contract

Use these top-level sections, with headings in the document's language:

1. **摘要** — first in the document, written last; explain the problem, direction, and end state in under one minute.
2. **背景** — the problem, benefits, and significance: Why.
3. **设计终态** — the complete intended system after the change: What.

Add Alternatives or Risks only for material content. An explicitly requested draft may include Open Questions and must be labeled unapproved and incomplete. A normal completed document records settled decisions, with observable behavior, ownership, boundaries, invariants, failure outcomes, rationale, and accepted limitations as applicable.

Stable facts about the existing system may explain the background. Keep transient snapshots, superseded designs, implementation history, and migration narratives out of the contract. Examples describe runtime outcomes, not test commands.

Implementation TODOs, file-by-file edits, pseudocode, migration procedures, rollout steps, and verification plans belong to `$implement-design`. A later implementation agent may add approved **Implementation Notes**, titled in the document's language, only for essential release, compatibility, or design-boundary constraints; this section must not become a task list or work log.

## Validate

Re-read against the approved requirements and decisions. Confirm one document in the selected language, the three sections, observable target-state precision, the appropriate `design_status` (`review-pending` or `draft`), and absence of implementation-process content. Check that only the approved path was written and run relevant narrow documentation checks. Report draft status honestly; document completion does not establish independent review or implementation.
