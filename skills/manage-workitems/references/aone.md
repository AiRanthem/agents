# Optional Aone mirror

Use only when `.project/project.json` enables Aone. Git holds the complete requirement and spec. Aone mirrors the agreed managed fields and points to the durable Git documents. Shared Aone spaces can contain several local projects: every title is `【项目名】工作项内容`.

## Configuration evidence

The initial adapter contract was checked against `a1` CLI 0.2.46. Verify installed `a1 --version` and relevant `--help` before use; project type/fields/workflows vary. Missing `a1` or unavailable identity is an error when this backend is selected. Do not print credentials or copy authentication configuration into the project.

Resolve these with the user during project creation: existing Aone project/space ID, work-item type/category, required custom fields, status mapping for all local states, and optional dependency-relation mapping. Use `a1 auth whoami --format json` to identify the current employee ID; assign created items to that identity, not an inferred display name. If multiple spaces/types match, show the actual choices. Do not create a new Aone project implicitly.

Confirmed command shapes:

```text
a1 project workitem create --project <space-id> --type <type> --category <category> --title <title> --assignee <emp-id> --status <mapped-status> --body-file <file>
a1 project workitem update <external-id> --title <title> --body-file <file> --status <mapped-status>
```

Both commands accept repeated `--cfs key=value` for required custom fields; discover fields with `a1 project workitem field list --type <type>`. `update` has no `--project` flag. Creation supports relations such as `--relation blocked-by:<external-id>`; discover support for updating/removing relations before claiming graph mirroring. Do not misuse `parent`/`sub` relations as DAG scheduling. Discover list/get commands and response fields from the installed CLI's help; do not invent flags or a search API.

## Owned projection and drift

Agree on a projection: managed title, mapped status, assignee on creation, and a clearly marked description section containing stable project/item ID, requirement summary, acceptance, dependency IDs, archive marker and Git document links. Include a stable project/item correlation marker in every create body. The full spec remains accessible via its immutable Git revision reference; do not rely on unknown body-size limits or silently truncate a contract. Preserve unrelated description sections and fields.

Before an update, read the actual item and compare every owned field with the last verified `baseline_fields`. Changes outside the owned projection are preserved. A difference inside the projection is a conflict: report the exact fields and obtain the intended reconciliation instead of choosing a winner automatically. After successful alignment, record the resolved baseline and retry the intended revision. Read back after writes and compare normalized fields before marking a receipt verified.

Use a Git browser URL only when the provider's URL format is known; otherwise include clone URL, full commit and repository-relative document paths. Link the business revision commit (`git_source_commit`), not a later receipt commit. This avoids a receipt-to-body synchronization loop. Record Aone's actual returned ID and link when available.

There is no verified Aone native archive operation in this adapter. Mirror `archived` in the managed description unless the selected project has a confirmed explicit archive-field mapping. Cancellation and delivery statuses use the project's actual workflow, not invented universal status IDs. If required transitions cannot be expressed, leave synchronization pending and explain the missing mapping.

## Failures and recovery

The [publication protocol](persistence.md) owns operation ordering. After a timeout or lost response, preserve the Git intent and mark the outcome unknown when that can be published. Search/read Aone by stable project/item marker and inspect candidates before retrying. One matching item can be adopted only after identity and intended fields are verified; ambiguous or absent results after an uncertain create require reconciliation, not a blind second create.

known-limit: this version uses the agent-driven CLI adapter and durable receipts, not an unattended transaction engine. There is no verified server idempotency key, field CAS, or atomic Git+Aone commit. Thus cross-machine agent writes are serialized by Git ownership, while a simultaneous manual Aone edit can still race with the compare/update interval. Do not promise stronger consistency. Upgrade to an automated adapter only after those API contracts and recovery behavior are verified.
