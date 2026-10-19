# Project record schema, version 2

The program creates and maintains YAML. Work-item agents read the returned prose payload and edit only the Markdown drafts selected by `begin` or supplied as captured autonomy result artifacts; Markdown bodies contain the complete current effective content, not superseded alternatives or event transcripts. The program treats their prose as opaque and validates only structured state and designated bindings. Git history is the audit trail for earlier body versions. Paths below are relative to the management root.

| Path | Owner and content |
| --- | --- |
| `.project/project.yaml` | Program: project identity, exact storage authority, backend configuration, repository and optional main-workspace/worktree configuration. |
| `workitems/<id>/metadata.yaml` | Program: identity, title, kind, dependencies, decomposition/fix links, document routes and design version/state. |
| `.project/state/<id>.yaml` | Program: exclusive ownership, active development, checkpoint state and `workflow.autonomy` authorization, execution attempts, captured spawn/result receipts, author identities and user acceptance bindings. |
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
| `workitems/<id>/records/<record-id>.md` and `.yaml` | Current pointer-bound review, delivery, waiver, cleanup or frozen predevelopment evidence, paired with program-owned bindings. |

Agent-authored Markdown is opaque to the program. For decision and log updates, write the complete current document, remove superseded statements, and retain constraints that still apply. The program replaces the file; it does not append events or infer semantic staleness. Git history is the audit trail for prior document versions. Keep only evidence pairs required by current review, delivery, waiver, cleanup or snapshot pointers, plus artifacts needed to resume pending operations; when a pointer is invalidated, its evidence pair is removed in the same publication. Explicit development discard retains its cleanup snapshot through `workflow.development_discard_record` until fresh code preparation is recorded; ordinary cleanup may replace `cleanup_record` without losing that pending reservation evidence.

## Identity and hierarchy

New IDs are `<code>-<phrase>`, for example `123-quota-lock`. Each code character identifies one hierarchy level; siblings use `1`–`9`, then `A`–`Z`. Phrases use lowercase ASCII words separated by hyphens. IDs are stable after publication, including archived and cancelled items. The program allocates and resolves IDs; an unpublished conflicting allocation is retried only through its returned workflow.

Hierarchy and `split_from` record decomposition provenance. `depends_on` records delivery prerequisites. A separate post-delivery defect item records `fixes: <original-id>` and retains the original `done` delivery history. Cancellation never fulfills a prerequisite. Migration preserves existing IDs and DAG references.

known-limit: one character per level allows 35 siblings. A larger capacity needs an agreed encoding change preserving existing references.

## Program-derived lifecycle

The design begins at version 1 when first written. The program hashes raw bytes: changed bytes increment the version; identical bytes do not. A changed contract invalidates its approval/review bindings. An authorized contract-internal autonomous revision records approval `kind: derived_revision`, preserves `original_user_approval` and binds the new design bytes and execution; a new independent passing review must explicitly return `contract_unchanged: true`. A changed approved contract requires a user decision. `draft` becomes `review-pending` only with actual user approval and its source or this bound derived revision; `implementable` requires a real independent passing review bound to the current requirement, spec, base and sessions. None of these states is expressed by editing prose.

Implementation requires a current approval/review binding or the user's explicit scoped design-review waiver, plus delivered prerequisites and published exclusive ownership. For a simple requirement, the user may explicitly authorize `development-start --skip-design-review --approval-source SOURCE` for this unchanged contract; the program records a requirement/spec/base/dependency-bound waiver, not a review pass. The agent cannot decide to skip review itself. A requirement-only contract is permitted for that waiver when there is no spec. Contract/dependency changes invalidate it and migration never fabricates it. Actual verified delivery records `done`; passing tests, review or a local commit is insufficient. Delivery and local cleanup remain separate. An unfinished fix blocks new downstream implementation/delivery, aggregate completion and the next gated checkpoint in an active session. After fix delivery, relevant baselines and reviews are checked again.

Autonomy authorization binds a coordinator, selected scope, requirement/decision hashes and any explicit design-review skip. For current actual user approval, `approved_contract` preserves that approval and the complete approved requirement/spec/decision for subsequent independent comparison; derived revisions preserve this original snapshot rather than fabricating new user approval. Execution records bind item, role, attempt, worker and current document/base/dependency inputs, including dirty code snapshots. Captured raw native data must identify the matching worker; `call_id` is optional when observable, with explicit local receipt-hash provenance otherwise. Acceptance records bind the actual user source to current artifact inputs and the code tree; they are distinct from implementation review and delivery.

New result capture requires observed terminal worker data and confirmed descendant cleanup. Reports and revised candidates retain immutable bodies and SHA-256 hashes in the execution record; recovery consumes these captured inputs without relying on temporary source files. An already delivered, verified-cleaned development item may record actual human acceptance against its retained reviewed snapshot, exempting only missing historical reads within the removed recorded code worktree. Current contract and remaining original input guards still apply.

Schema 1 is readable for diagnostics and migratable through `migrate`; no ordinary v1 write compatibility is implied. Migration preserves identities, DAG and current effective business constraints, and blocks on unresolved synchronization, active ownership or a business source that needs an agent to assemble current text. Knowledge metadata is converted from JSON to YAML without dropping fields, and its Markdown body remains opaque. It does not retain obsolete document copies as a parallel project history. Project Git history provides prior versions.

Opt-in autonomy adds `authorization.predevelop`, `snapshots` (records keyed by immutable ID), `latest_snapshot`, and `predevelopment` with phase `preparing`, `baseline`, `speculative`, `reconciling` or `formal`. Each snapshot is a retained same-ID YAML/Markdown record pair with frozen input binding and prose, original HEAD/full tree, mapped branch/ref/URL, publication state `planned`/`committed`/`published`, commit OID and explicit authorization source. Its prerequisite map pins inherited snapshot IDs. A generation retains exact published input records, configuration hash, authorization, fetched formal-base OID (`formal_base`), initial integrated baseline and the original development descriptor; reconciliation also retains own source snapshot, old baseline, formal target and generation. The marker remains after formal convergence for inspection and recovery. New `baseline`/`rebase` attempts use the ordinary implementer role settings and terminal-receipt guards. These fields do not reinterpret `awaiting_delivery` as human acceptance: the derived scheduler reports speculative waits separately and prohibits acceptance/delivery until convergence and fresh reviews.

## Managed lifecycle state

`workflow.design_authors` preserves actual design contributors. `design.approval.recorded_by` identifies the registrar while `source` identifies actual user approval; registrar identity alone is not authorship. Legacy `session` remains readable provenance.

`workflow.lifecycle` owns adopted policy, mode/coordinator handoff, replacement intent, immutable preservation checkpoints, retired source generations with dispositions, resource states and exact collection intents. Resources transition live → released → deleting → deleted; released resources can return live before deletion marking. Generation workflow phases remain separate. The program validates identities and uses the existing `.project/state/<id>.yaml` guarded publication authority. See [resource lifecycle](resource-lifecycle.md).
