---
name: split-workitem
description: Decompose an oversized requirement into independently deliverable work items and a dependency DAG only inside a managed project workspace. Use before detailed design or after design review identifies excessive scope. Does not create implementation TODOs or operate outside a managed project.
---

# Split Work Item

Read [project context](../manage-workitems/references/project-context.md) and [workflow](../manage-workitems/references/workflow.md). For direct decomposition, the approved output is the item graph and requirement records. Reuse approved behavior as the contract; use `explore-design` for unresolved requirements or choices that affect the partition.

Define each outcome, acceptance boundary, shared contract, prerequisite and coverage of the original requirement. Keep confirmed design decisions distinct from the prior implementation and its reuse status. Leave each item's internal implementation choices to its own design and implementation.

Choose cohesive, usable capabilities as the delivery boundaries. For each child, describe what becomes usable and a concrete acceptance scenario once its prerequisites deliver. Keep a state machine's representation, execution, recovery and deletion together when they share a correctness boundary. Select the item count from these outcomes and consolidate fragments that depend on later items to complete their own behavior, safety, configuration or verification.

Evaluate decomposition when a single PR is expected to change more than roughly 1,500 production lines, contains independent goals, spans unrelated ownership boundaries, or cannot be coherently reviewed, delivered or rolled back. Treat size as a reviewability signal, distinguish production changes from generated/test/documentation volume, and preserve each capability's necessary correctness and compatibility within its delivery boundary.

- Every development item targets one repository and one independently deliverable change. Use the DAG for shared prerequisites, parallel branches and integration work.
- Keep the original item as an aggregate when dependencies fully satisfy it, or retain its remaining integration requirement as a development item. Preserve existing incoming references to its ID. Record how the outputs jointly cover the original acceptance criteria.
- Allocate child IDs together with `project_runtime.py new-id --parent <full-parent-id> <phrase> [<phrase> ...]` under the [numbering contract](../manage-workitems/references/schema.md). Each child appends one hierarchy character and records the parent's full ID in `split_from`. The hierarchy expresses provenance; set delivery prerequisites separately in `depends_on`. Preserve published codes when consolidating scope or changing presentation order.
- Lack of a dependency edge permits parallel work only after checking shared interfaces and change surfaces for interference. Add an actual prerequisite or refine the partition where needed.
- Preserve earlier approved decisions and reusable code evidence by reference. Children receive their own requirements and spec; they do not inherit the parent's `implementable` status. Existing parent specs remain attributed to their original scope and are revised or retired explicitly, not copied as approved child designs.
- Cancelled prerequisites block dependent completion until the user changes the requirement/dependency contract. Do not automatically remove edges to make a graph executable.

When full coverage of an existing design is required, preserve its complete snapshot or pinned revision and map its behavior, failure/recovery rules, security, compatibility, accepted limits and non-goals to child acceptance. Assign explicit responsibility for each facet of a composite requirement. After consolidating items or changing their scope, reconcile their requirements, coverage, dependencies and references, then verify semantic completeness as well as structural consistency.

Present each item's usable outcome and reason for its boundary alongside the dependencies for user agreement. Persist the agreed batch through [persistence](../manage-workitems/references/persistence.md), validating the complete resulting DAG before publication. Hand off to the shared workflow's design cadence: an authorized design phase can complete stable child designs ahead of delivery, with formal independent reviews following each child's prerequisite delivery. Keep design and implementation within their separately authorized phases.
