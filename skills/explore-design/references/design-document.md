# Design document during execution

Read this reference only for ordinary execution-mode document writing after identifying the active host mode. Read-only planning discussion and delegated project stage executors do not use this write workflow. Executors follow their assigned candidate paths and return them to the controller without official-document writes.

In a schema-v2 project, [shared project context](../../manage-workitems/references/project-context.md) supplies the project path and persistence rules: use `workitems/<id>/spec.md` as the sole Why/What document, keep machine status out of its frontmatter, and record approval/review state through the project command workflow. An oversized item needs a complete parent spec with delivery stages and DAG, followed by independent Pass before decomposition. Child specs inherit the approved contract; additional design exploration is conditional on actual blocking gaps. Do not create a second standalone design document. read-only planning mode remains read-only.

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

For oversized project items, include usable delivery stages, their acceptance coverage and the dependency DAG as design decisions; future child refinement does not reduce parent completeness. Implementation TODOs, file-by-file edits, pseudocode, migration procedures, rollout steps, and verification plans belong to `$implement-design`. A later implementation agent may add approved **Implementation Notes**, titled in the document's language, only for essential release, compatibility, or design-boundary constraints; this section must not become a task list or work log.

## Validate

Confirm that the pre-write completeness reflection covered the current contract and re-read the written document against that contract, approved requirements and decisions. Reopen the reflection if writing introduced a substantive change. Confirm one document in the selected language, the three sections, observable target-state precision, the appropriate `design_status` (`review-pending` or `draft`), and absence of implementation-process content. Check that only the approved path was written and run relevant narrow documentation checks. Report draft status honestly; document completion does not establish independent review or implementation.
