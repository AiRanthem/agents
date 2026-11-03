# Project record layout

The agent maintains documents and metadata directly. Preserve established locations and business fields; the paths below describe the normal YAML layout. Existing JSON records may be maintained in their current form or converted during an authorized update without losing facts or references. A format version describes the stored representation.

| Path | Content |
| --- | --- |
| `.project/project.yaml` | Project ID/name, configured Git remote/branch, optional external backend, repositories and main-workspace association. |
| `.project/main-workspace.json`, `.project/repositories.yaml` | Actual workspace and repository locations when separate location files are used. |
| Root and item `AGENTS.md` | Applicable instructions and routes to original business instructions. |
| `.project/context.md` | Project-wide goals, domain context and current constraints. |
| `.project/business-instructions.md`, `.project/main-workspace.md` | Applicable business constraints and original workspace locations when present. |
| `workitems/<id>/metadata.yaml` | Stable identity, title, kind, dependency/decomposition/fix links, document routes and design progress. |
| `.project/state/<id>.yaml` | Current status, source branch/worktree, implementation, review, acceptance and delivery facts. |
| `.project/sync/<id>.yaml` | Optional external item ID/URL, actual synchronization result and unresolved outcomes. |
| `workitems/<id>/requirement.md` | Goal, scope, acceptance criteria and delivery obligations. |
| `workitems/<id>/spec.md` | Complete current design, decisions and tradeoffs. |
| `workitems/<id>/decision.md` | Current user decisions and their real sources. |
| `workitems/<id>/context.md`, `logs.md` | Current findings, verification, unresolved facts and handoff. |
| `workitems/<id>/records/` | Useful review, acceptance, delivery and cleanup reports; accompanying metadata when needed. |
| `evidence/<id>.md` and optional `.yaml` | Reusable knowledge, scope, sources and limitations. |

Write complete current content and remove superseded statements during an update. Git preserves previous versions. Keep useful original reports associated with their actual targets and distinguish them from current conclusions. Temporary tool output can remain outside formal documents.

## Identity and relationships

New IDs use `<code>-<phrase>`, such as `123-quota-lock`. Each code character identifies a hierarchy level; siblings use `1`–`9`, then `A`–`Z`. Phrases use lowercase ASCII words separated by hyphens. Choose an unused code among existing siblings and keep published IDs stable, including archived or cancelled items. Preserve existing IDs and references during maintenance.

Hierarchy and `split_from` describe decomposition. `depends_on` lists prerequisite items; `fixes` links a new defect item to the original delivered item. Cancellation does not establish delivery. Use full stable IDs without self references or dependency cycles.

known-limit: this convention permits 35 siblings per level. A project needing more should adopt an explicit encoding extension while preserving existing references.

## Progress and evidence fields

Keep `status`, `design`, `development`, `delivery`, `cleanup` and `archived` aligned with actual work. Existing labels such as `developing`, `awaiting_delivery` and `done` describe facts, not permissions. Record unresolved facts in context.

`design` may contain its file, version, current state, actual user approval source and review. Update its version when revising the design and explain consequential changes. `design.next_action` can identify implementation or decomposition. Child items inherit relevant complete parent design and preserve that relationship.

`development` records the actual repository, branch, worktree, baseline and implementation/review results. `delivery` records required outcomes and evidence for achieved outcomes. Source push, merge, release, deployment and end-to-end behavior are separate facts. `cleanup` records actual removals and retained resources.

Record actual author/reviewer identities, assessed scope/version, outcome, findings and provenance. `recorded_by` identifies the registrar; it does not establish authorship, independence or user approval. Human acceptance records the user's actual conclusion and accepted target separately from independent review.

Autonomous work records its authorized scope and actual outcomes in these same files. Preserve useful source-recovery locations and unresolved external outcomes as explicit facts. No separate operation registry or mandatory transition protocol is needed to edit project records.
