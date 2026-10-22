# Project context and routing

Project mode applies at a management Git root with valid `.project/project.yaml` schema 2. A code repository or linked worktree does not become a project because it is nested beneath one. Schema-1 `.project/project.json` projects allow diagnostic reading and explicit migration only. Creation, upgrade and deletion may target an explicitly selected project from outside it.

Start project sessions at the management root and read its `AGENTS.md`. Resolve the caller-supplied project entrypoint through the [fixed command workflow](commands.md), using the shared script only as its fallback. For a requested write, the program returns the complete read payload, editable Markdown paths and exact finish command. Read those inputs; do not select additional project documents or reproduce the program's gates and persistence checks. Program-generated item instructions and returned original main-workspace instructions retain their own scopes.

Authorized read-only investigation may use `show ID` and selected `--documents`; reviews use `context ID --role review-design|review-implementation` to obtain primary inputs while deferring earlier review reports. Read applicable original project/main-workspace/source instructions without `begin` or takeover; keep shared artifacts unchanged and retain any assessment in a separate temporary report with stable input identities. Project write operations use the control-claim write lock. Requirements and design work use the complete selected current requirement and spec from the returned payload. Reading a requirement does not authorize design, decomposition, source exploration or implementation. Reuse explicit authorization for the same scope without asking again. Read-only planning mode remains read-only; Agent-mode project checkpoints may publish metadata, while code submission requires its own user instruction.

| Requested task | Skill |
| --- | --- |
| Report project progress or current status | [manage-workitems](../SKILL.md#progress-report), one `progress` command |
| Record requirements, rename, change dependencies or archive | [manage-workitems](../SKILL.md) |
| Create a separate project repository | [create-project](../../create-project/SKILL.md) |
| Deterministic project migration and instruction refresh | [upgrade-project](../../upgrade-project/SKILL.md) |
| Materialize an implementable oversized design into child contracts and a delivery DAG | [split-workitem](../../split-workitem/SKILL.md) |
| Requested design or implementation | [develop-workitem](../../develop-workitem/SKILL.md) |
| Explicit scoped autonomous advancement | [advance-project](../../advance-project/SKILL.md), through the [coordinator interface](commands.md#autonomous-advancement) |
| Verify actual delivery or separately requested cleanup | [complete-workitem](../../complete-workitem/SKILL.md) |
| Remove the selected local project | [delete-project](../../delete-project/SKILL.md) |

Report full IDs and titles, such as `123-quota-lock（统一配额锁）`. The program resolves full IDs, codes, phrases and exact titles; report ambiguity instead of constructing paths from a guess. Each code level describes decomposition, while the dependency DAG determines delivery prerequisites.

Shared project knowledge is global and may remain valid without an item pointer. Use the direct knowledge commands in [the command contract](commands.md#operations); they do not use the work-item `begin` workflow. Each read returns a unique draft path without creating it. Keep the complete current Markdown body and explicit typed metadata, use returned guards for replacements or removal, and preserve pending or stale drafts as uncommitted work.

[Schema](schema.md) defines record ownership; [workflow](workflow.md) defines lifecycle evidence and authorization. [Main-workspace association](main-workspace.md) describes the separate business context boundary. [Recovery](recovery.md), [Aone](aone.md) and [persistence](persistence.md) describe program responsibilities and the facts to report when execution stops; they do not add agent-selected recovery procedures.

For explicit autonomous advancement, retain selected scope, current control claim and coordinator audit provenance. Read `autonomy status` for artifact-derived readiness and continue unrelated ready items. The advancing agent manages task trees directly and passes current complete original inputs, code workdir/baseline, output paths and genuine actor attribution. Project state does not register executors. Pass `approved_contract` to derived-design reviewers for original-contract comparison. Reviews require independent original evidence and stable source. A metadata checkpoint grants no extra source writes, remote deletion or takeover; each follows its covering authorization and typed command.
