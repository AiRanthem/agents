---
name: split-workitem
description: Materialize an oversized work item's complete independently reviewed design into cohesive child work items and a dependency DAG. Children inherit the design and need refinement only for demonstrated gaps.
---

# Split Work Item

Use the complete parent spec and its actual independent review. Requirement registration alone does not start decomposition. The parent design describes the whole behavior, shared interfaces and invariants, consequential failures, usable delivery stages, acceptance coverage and dependencies. Resolve missing consequential decisions in the authorized design work before depending on them.

Create child records and documents directly using the project's [layout](../manage-workitems/references/schema.md). Preserve published IDs and existing references; allocate unused hierarchical IDs consistent with the project. Extract each child's complete relevant contract, usable outcome, acceptance scenarios, repository, prerequisites and original-scope coverage. Preserve shared guarantees and failure boundaries. Design inheritance does not require a new exploration phase.

Keep components together when they share a correctness or delivery boundary. Use one code repository per development child. Maintain the parent/child relationships and actual dependency graph together, without cycles or missing references. Never remove a real prerequisite merely to make an item appear ready.

When children cover the original outcome, record the parent as an aggregate and keep its whole-system design and acceptance responsibility. Account for any existing parent source and recovery location; remove it only under covering cleanup authorization. Make remaining integration an explicit child.

Children enter their own `review-design` with inherited contracts and actual prerequisite assumptions. Parent review is not child review. Supplement designs only for demonstrated omissions, contradictions or consequential choices, and reuse valid earlier coverage under the [shared standard](../review-design/references/implementable-gate.md). Changes to parent guarantees or shared contracts return to the responsible owner for the necessary decision and affected review.

Commit and push the coherent parent/child documents and metadata. Report full IDs/titles, usable outcomes, dependencies, inherited design paths and actual publication status. Continue review or implementation only within the authorized scope.
