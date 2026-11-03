# Project design ownership

Read [project context](../../manage-workitems/references/project-context.md), the complete current requirement/spec/decisions and original project/main-workspace/source instructions. An ordinary authorized design session maintains the spec and decisions directly at their final paths. An autonomous executor returns its assigned candidate and report to the [controller](../../advance-project/references/coordinator.md), which integrates formal project records.

Keep the spec focused on the complete current Why/What contract and keep status and attribution in project metadata. Record actual design authors and approval sources. Exploration does not establish independent review. Preserve effective decisions while removing superseded statements; use Git history for earlier versions.

Keep design within the requested scope. Explicit prerequisite assumptions may support early design; compare them with actual prerequisite behavior before implementation. Reuse valid independent coverage under the [coverage-reuse rules](../../review-design/references/implementable-gate.md#reuse-independent-coverage), and independently review affected changes. Material contract changes require the user's decision. For oversized work, complete the whole-system design, delivery stages and dependency graph before using `split-workitem`.

Reuse approval of an unchanged complete contract. Otherwise present the complete candidate and consequential choices for the user's decision. After approval, record the current version and genuine provenance, commit and push the project update, and report the authorized next stage. Ordinary design work does not invoke `review-design` without review authorization; explicitly started `advance-project` covers its stage dispatches.

Read-only planning remains read-only and uses [execution-mode handoff](execution-modes.md). A delegated [stage executor](../../advance-project/references/stage-executor.md) writes only its assigned candidate/report or source paths and returns actual attribution; the controller owns formal project publication.
