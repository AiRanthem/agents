# Project design ownership

Read [project context](../../manage-workitems/references/project-context.md), the complete current requirement/spec/decisions and original project/main-workspace/source instructions. An ordinary authorized design session maintains the spec and decisions directly at their final paths.

Use the item's existing spec (normally `workitems/<id>/spec.md`) as its sole current Why/What document. Record design status, actual authors and approval sources in project metadata, with independent review evidence in the review records. Preserve effective decisions while removing superseded statements; use Git history for earlier versions.

Keep design within the requested scope. Explicit prerequisite assumptions may support early design; compare them with actual prerequisite behavior before implementation. Reuse valid independent coverage under the [coverage-reuse rules](../../review-design/references/implementable-gate.md#reuse-independent-coverage), and independently review affected changes. Material contract changes require the user's decision.

Keep one work item for a single acceptance goal, including changes delivered through several PRs. After independent design review passes, the item is ready for authorized implementation subject to its prerequisites. Set `design.next_action` to `split` only for agreed, separately managed outcomes. After the parent design passes, [manage-workitems](../../manage-workitems/SKILL.md) handles authorized decomposition.

Reuse approval of an unchanged complete contract. Otherwise present the complete candidate and consequential choices for the user's decision. After approval, record the current version and genuine provenance, commit and push the project update. Invoke `review-design` only when the user has authorized design review.

Read-only planning remains read-only and uses [execution-mode handoff](execution-modes.md).
