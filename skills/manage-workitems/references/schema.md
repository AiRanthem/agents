# Project record schema, version 2

The program creates and maintains YAML. Work-item agents read the returned prose payload and edit only the Markdown drafts selected by `begin`; Markdown bodies contain the complete current effective content, not superseded alternatives or event transcripts. The program treats their prose as opaque and validates only structured state and designated bindings. Git history is the audit trail for earlier body versions. Paths below are relative to the management root.

| Path | Owner and content |
| --- | --- |
| `.project/project.yaml` | Program: project identity, exact storage authority, backend configuration, repository and optional main-workspace/worktree configuration. |
| `workitems/<id>/metadata.yaml` | Program: identity, title, kind, dependencies, decomposition/fix links, document routes and design version/state. |
| `.project/state/<id>.yaml` | Program: exclusive ownership, active development and checkpoint state. |
| `.project/sync/<id>.yaml` | Program: durable external intent, uncertain outcomes and verified receipts. Returned commands resolve its location; it is not a Markdown handoff. |
| Root and item `AGENTS.md` | Program-generated routing to the current shared workflow and preserved business instructions. |
| `.project/context.md` | Overall project facts and business context. |
| `.project/project-instructions.md` | Program-generated routes to current project context and business instructions. |
| `.project/business-instructions.md` | Optional explicit project-specific instructions containing current effective constraints. |
| `evidence/<id>.yaml` and `.md` | Program-owned knowledge metadata and its complete current opaque Markdown body; entries are global and need not point to an item. |
| `workitems/<id>/requirement.md` | Goal, scope, acceptance and delivery obligations. |
| `workitems/<id>/spec.md` | The complete current design; no machine-status frontmatter. |
| `workitems/<id>/decision.md` | Current effective decisions and approval context, maintained as one complete Markdown document. |
| `workitems/<id>/context.md` | Current facts, verification, remaining uncertainty and handoff. |
| `workitems/<id>/logs.md` | Current operational context and handoff, maintained as one complete Markdown document. |
| `workitems/<id>/records/<record-id>.md` and `.yaml` | Current pointer-bound review, delivery, waiver or cleanup evidence, paired with program-owned bindings. |

Agent-authored Markdown is opaque to the program. For decision and log updates, write the complete current document, remove superseded statements, and retain constraints that still apply. The program replaces the file; it does not append events or infer semantic staleness. Git history is the audit trail for prior document versions. Keep only evidence pairs required by current review, delivery, waiver or cleanup pointers, plus artifacts needed to resume pending operations; when a pointer is invalidated, its evidence pair is removed in the same publication.

## Identity and hierarchy

New IDs are `<code>-<phrase>`, for example `123-quota-lock`. Each code character identifies one hierarchy level; siblings use `1`–`9`, then `A`–`Z`. Phrases use lowercase ASCII words separated by hyphens. IDs are stable after publication, including archived and cancelled items. The program allocates and resolves IDs; an unpublished conflicting allocation is retried only through its returned workflow.

Hierarchy and `split_from` record decomposition provenance. `depends_on` records delivery prerequisites. A separate post-delivery defect item records `fixes: <original-id>` and retains the original `done` delivery history. Cancellation never fulfills a prerequisite. Migration preserves existing IDs and DAG references.

known-limit: one character per level allows 35 siblings. A larger capacity needs an agreed encoding change preserving existing references.

## Program-derived lifecycle

The design begins at version 1 when first written. The program hashes raw bytes: changed bytes increment the version; identical bytes do not. A changed contract invalidates its approval/review bindings. `draft` becomes `review-pending` only with actual user approval and its source; `implementable` requires a real independent passing review bound to the current requirement, spec, base and sessions. None of these states is expressed by editing prose.

Implementation requires a current approval/review binding or the user's explicit scoped design-review waiver, plus delivered prerequisites and published exclusive ownership. For a simple requirement, the user may explicitly authorize `development-start --skip-design-review --approval-source SOURCE` for this unchanged contract; the program records a requirement/spec/base/dependency-bound waiver, not a review pass. The agent cannot decide to skip review itself. A requirement-only contract is permitted for that waiver when there is no spec. Contract/dependency changes invalidate it and migration never fabricates it. Actual verified delivery records `done`; passing tests, review or a local commit is insufficient. Delivery and local cleanup remain separate. An unfinished fix blocks new downstream implementation/delivery, aggregate completion and the next gated checkpoint in an active session. After fix delivery, relevant baselines and reviews are checked again.

Schema 1 is readable for diagnostics and migratable through `migrate`; no ordinary v1 write compatibility is implied. Migration preserves identities, DAG and current effective business constraints, and blocks on unresolved synchronization, active ownership or a business source that needs an agent to assemble current text. Knowledge metadata is converted from JSON to YAML without dropping fields, and its Markdown body remains opaque. It does not retain obsolete document copies as a parallel project history. Project Git history provides prior versions.
