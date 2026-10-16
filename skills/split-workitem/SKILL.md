---
name: split-workitem
description: Decompose a managed project requirement into independently usable deliverables and a dependency DAG. Use for requested decomposition before detailed design or after oversized scope is identified; does not authorize implementation or child design.
---

# Split Work Item

Agree cohesive delivery boundaries for the user's requested requirement. Describe what each child makes usable, its acceptance scenario, shared contract, prerequisites and coverage of the original. Preserve approved behavior and unresolved decisions; use `explore-design` only when the user has requested design exploration. Do not create implementation TODO fragments as deliverables.

Keep necessary representation, execution, recovery, security, configuration and verification together when they share one correctness boundary. Use one repository per development item. Size and unrelated ownership/rollback boundaries are signals to split, not reasons to omit each capability's correctness. Preserve incoming references and original acceptance coverage; use an aggregate only when the child outputs fully satisfy the original outcome.

Persist the agreed split through installed `project.py` and the [fixed command contract](../manage-workitems/references/commands.md). Use `begin create --parent ORIGINAL --title TITLE --slug SLUG` for each agreed child and `dependency-update` for the agreed prerequisite sets. Use `kind-update ORIGINAL --kind aggregate` only when the agreed children fully cover the original outcome and any recorded code development has completed verified cleanup with its worktree absent; retain a development item for remaining integration. Converting an aggregate to development requires a repository. The program allocates IDs, routes drafts and validates the graph. Read every returned payload, edit only returned Markdown paths and execute each returned `finish_command` unchanged. Follow status handling in the command contract.

Hierarchy records provenance and dependencies record delivery prerequisites. Preserve published IDs, established edges and delivered status. Do not remove an edge merely to pass a gate. Children receive their own current requirement and later their own requested design/review; they inherit no parent implementation approval. Keep only current pointer-bound approval, review, delivery, waiver and cleanup evidence, with explicit agent/reviewer responsibility for assessing evidence against every acceptance criterion and failure boundary.

Report full IDs with titles, usable outcomes, dependencies and actual publication status. Finish after the agreed graph and requirement skeletons persist. Do not automatically design or review the children. A separately requested design phase may complete stable child designs before prerequisites deliver, while formal review uses their actual delivered baseline.
