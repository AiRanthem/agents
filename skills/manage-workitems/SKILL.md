---
name: manage-workitems
description: Create requirement skeletons, find, update, or archive abstract work items inside a managed project workspace identified by .project/project.json. Persist requirements and status through Git and optional Aone. Does not investigate code, design, implement, or delete work items; do not activate outside a managed project.
---

# Manage Work Items

Read [project context](references/project-context.md), then only the references needed for the current operation. Resolve the current item from the request and project metadata; ask when more than one item matches. Remain at the requirement level. A request to record requirements authorizes metadata and a requirement skeleton, not design or decomposition. Code exploration belongs to a separately requested `split-workitem` or design/development task.

Use [project_context.py](scripts/project_context.py) for filtered, paginated metadata queries and role-specific input paths. It reads project metadata, not source code. Search relevant `workitems/` requirement/spec text when the user's query cannot be answered by title/status metadata. An index miss is a reason to check canonical records, not proof that an item or capability does not exist.

- Create a stable, collision-resistant item ID with `project_runtime.py new-id`. Follow [schema](references/schema.md). Initialize `status: new`, `owner: null` and `development: null`. Record the user's stated outcome and known scope, acceptance and delivery obligations in `requirement.md`; reference project background instead of repeating it. Mark missing details as unresolved and ask only for information required to identify or persist the item. Creation does not require a complete contract or `spec.md`. An oversized incoming requirement may remain pending decomposition; do not automatically split it.
- Keep each development item to one repository, worktree and independent delivery. Aggregate items represent outcomes covered by their dependencies and have no development worktree.
- Represent prerequisites with `depends_on`; an edge means the prerequisite must deliver before implementation begins. Preserve `split_from` for provenance, not scheduling. Validate the merged graph for missing targets and cycles.
- Preserve the user's requirements separately from assumptions and tentative ideas. Record consequential decisions and unresolved questions succinctly, with their approval provenance. If a spec already exists, preserve it as the single design artifact; creating or changing its design belongs to a separately requested design task.
- Update state from observed progress or an explicit user correction, preserving its provenance. `developing` is a durable exclusive claim, not a casual progress label; use the claim gate in [workflow](references/workflow.md). `done` requires the declared delivery evidence. Cancellation does not fulfill a dependency.
- Archive by setting `archived`; preserve IDs, links, dependencies, records and searchability. Do not delete items. Aone archive is represented in the managed description unless an explicit project mapping supplies an archive field.

Prepare edits outside tracked paths and use [persistence](references/persistence.md) for publication. Batch intermediate revisions at a meaningful task checkpoint. Synchronize every enabled backend and verify the final remote push before claiming durable success. Project metadata commits are part of this workflow; code commits remain with the user.

Report the changed IDs, substantive change, dependency consequences and synchronization state. Distinguish pending, ambiguous and fully persisted results. Item creation ends after the metadata and requirement skeleton are persisted; enter design only on an explicit user request.
