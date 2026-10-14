---
name: split-workitem
description: Decompose an oversized requirement into independently deliverable work items and a dependency DAG only inside a managed project workspace. Use before detailed design or after design review identifies excessive scope. Does not create implementation TODOs or operate outside a managed project.
---

# Split Work Item

Read [project context](../manage-workitems/references/project-context.md) and [workflow](../manage-workitems/references/workflow.md). Use `explore-design` to investigate the relevant code and align Why/What with the user. For direct decomposition, the approved output is the item graph and requirement records; a separate parent spec and design review are unnecessary.

Resolve enough design to define each outcome, acceptance boundary, shared contract, prerequisite and coverage of the original requirement. Resolve uncertainty that changes the partition. Leave each item's internal implementation choices to its own design and implementation.

Evaluate decomposition when a single PR is expected to change more than roughly 1,500 production lines, contains independent goals, spans unrelated ownership boundaries, or cannot be coherently reviewed, delivered or rolled back. Count changes honestly, distinguish generated/test/documentation volume, and do not optimize line count or split files mechanically. Necessary correctness and compatibility remain intact.

- Every development item targets one repository and one independently deliverable change. Use the DAG for shared prerequisites, parallel branches and integration work.
- Keep the original item as an aggregate when dependencies fully satisfy it, or retain its remaining integration requirement as a development item. Preserve existing incoming references to its ID. Record how the outputs jointly cover the original acceptance criteria.
- Lack of a dependency edge permits parallel work only after checking shared interfaces and change surfaces for interference. Add an actual prerequisite or refine the partition where needed.
- Preserve earlier approved decisions and reusable code evidence by reference. Children receive their own requirements and spec; they do not inherit the parent's `implementable` status. Existing parent specs remain attributed to their original scope and are revised or retired explicitly, not copied as approved child designs.
- Cancelled prerequisites block dependent completion until the user changes the requirement/dependency contract. Do not automatically remove edges to make a graph executable.

Show the proposed outcomes and dependency changes together for user agreement. Persist the agreed batch through [persistence](../manage-workitems/references/persistence.md), validating the complete resulting DAG before publication. Resume no code implementation as part of decomposition.
