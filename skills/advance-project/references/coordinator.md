# Autonomous project controller

Work from the management root. Read its original `AGENTS.md`, [project context](../../manage-workitems/references/project-context.md), current requirements, design, decisions, dependencies and existing source locations. The caller supplies available stage-role bindings, configuration evidence and actual permission limits. The controller owns project documents and metadata; executors own their assigned source and assessment. Do not invent unavailable roles, tool capabilities or model provenance.

## Scope and progress

Use the user's selected whole project, item subtree or explicit item set. Read outside prerequisites without silently adding them to the scope. Record the actual advancement authorization in the existing project context. Assess progress from current artifacts, actual reviews, acceptance and delivery facts. Keep task IDs and execution details in working state rather than turning them into project eligibility tokens.

Maintain requirements, design, metadata, current context and reports at their final paths. After a coherent update, commit the affected project files and push the configured branch under [persistence](../../manage-workitems/references/persistence.md). Preserve unrelated changes. A failed push retains local work for an ordinary retry. Metadata publication does not publish source code or establish an external backend result.

Retain completed code and valid evidence after interruption. A missing source location or required capability affects only dependent work. Reconstruct facts from current files and actual Git state; do not reset useful work or ask for a special recovery authorization merely to continue an already authorized task.

## Stages and evidence

Bind these first-level responsibilities to the supplied executors. Keep controller responsibilities out of their assignments.

| Stage | Skill |
| --- | --- |
| Design review | `review-design` |
| Design revision | `explore-design` |
| Implementation | `implement-design` |
| Code review | `review-implementation` with `single-agent` mode |
| Fix | `receiving-code-review` |

Choose an in-scope stage whose actual inputs are available. Supply its complete approved contract, original instructions, source location and comparison base, permitted writes, designated candidate/report paths, [stage-executor](stage-executor.md) and a compact evidence index. Wait for its work and descendant cleanup before selecting the next stage. Independent reviewers receive stable original evidence and author-independent context. Prefer the original reviewer for affected re-review while that reviewer remains independent.

Record actual authors, reviewers, targets, findings, checks and results directly in the item documents and metadata:

- Design review records the independent reviewer's actual verdict and report. Copy authorized mechanical candidate corrections exactly, with their determining evidence and unchanged-contract explanation. Substantive corrections belong to a separate author.
- Design revision preserves the approved contract and records its author and material changes. Obtain a user decision for a material contract change; retain applicable earlier review coverage and independently review the affected scope.
- Implementation and fixes use the approved contract and actual prerequisite behavior. Reuse the recorded source worktree, preserve useful code, and record meaningful verification and unresolved limits. An implementation report is not independent approval.
- Code review uses one qualified reviewer independent of implementation and fixes. Pass `single-agent` explicitly, including on re-review. The reviewer assesses correctness, quality, security, tests and high-risk boundaries against the complete stable target. Missing essential evidence is an incomplete assessment, not Pass.

For decomposition, use `split-workitem` to write complete inherited child contracts and their dependency graph. Whole-project and subtree authorization cover included children; an explicit item set expands only under covering authorization. Assess retained design coverage using the [coverage-reuse rules](../../review-design/references/implementable-gate.md#reuse-independent-coverage), with actual original approval and review evidence. Record applicability directly; do not invent a new independent verdict.

## Completion and decisions

Keep independent review judgment with the reviewer. Tests and AI review do not establish human acceptance. Consolidate consequential user-owned choices under [discussion and authorization](discussion-and-authorization.md) while continuing unaffected work.

During human acceptance, preserve user-finalized code and design and use [complete-workitem](../../complete-workitem/SKILL.md) to record the real conclusion and align remaining outdated design descriptions. An accepted item awaits only its actual remaining delivery obligations; do not restart design or implementation because its final files changed under that acceptance. Downstream items assess relevant prerequisite changes in their own work. Aggregate items retain whole-outcome acceptance and delivery responsibility without a source implementation stage.

Finish when the scoped work is completed or needs human acceptance, separately authorized delivery, a consequential decision or an unavailable prerequisite. Account for outstanding tasks and their resources. Report full item IDs and titles, current artifacts, actual checks and their limits, acceptance/delivery gaps and retained source locations. Cleanup follows the actual scope and [resource preservation](../../manage-workitems/references/resource-lifecycle.md).
