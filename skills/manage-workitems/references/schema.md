# Project record schema, version 1

Management paths below are relative to the project root; development paths use the configured worktree base. Use UTF-8 JSON and Markdown. IDs are stable safe identifiers; generate work-item IDs with `project_runtime.py new-id`. IDs never depend on a mutable title. Extra fields may record project-specific facts but must not redefine the core fields.

## Project

`.project/project.json`:

```json
{
  "schema_version": 1,
  "id": "example-project",
  "name": "Example",
  "storage": {
    "remote": "origin",
    "branch": "projects/example",
    "url": "git@example.com:team/project-records.git"
  },
  "backends": {"aone": null},
  "repositories": [
    {"id": "service", "url": "git@example.com:team/service.git", "base_ref": "refs/heads/main", "publish_remote": "origin"}
  ]
}
```

`storage.branch` is the actual remote branch name, without `refs/heads/`; never infer it from the remote's default branch. `base_ref` is a full code-repository ref. Record publishing conventions when they differ from defaults. Machine-local clone paths and identities are not part of repository configuration.

Enabled Aone replaces `null` with an object containing `space_id`, `type`, `category`, and `status_map`. Record confirmed required custom fields and supported relation mappings as additional configuration. See [Aone](aone.md); credentials never belong in this file.

### Optional main workspace and worktree layout

An associated project adds these fields; existing standalone records remain valid:

```json
{
  "main_workspace": {
    "id": "oka",
    "name": "OKAWorkspace",
    "repository": {
      "url": "git@example.com:team/OKAWorkspace.git",
      "ref": "refs/heads/master"
    }
  },
  "worktrees": {"base": "main_workspace", "path": "worktrees/example-project"}
}
```

`main_workspace` is absent for a standalone project. Its `id` is a stable safe identifier, `name` is nonempty, and `repository` is either null or a clone URL and full Git ref for recovery. The associated project's `.project/main-workspace.md` holds required instruction paths, scoped context/skill routes and sourced constraint snapshots; see [association](main-workspace.md). Actual absolute roots belong only in `.project-local/main-workspace.json` as `{ "id": "oka", "root": "/local/main/workspace" }`.

Omitted `worktrees` means `{ "base": "project", "path": "worktrees" }`. The base is `project` or `main_workspace`; the latter requires an association and a dedicated subdirectory in the main workspace’s actual layout. Paths are normalized relative POSIX and contain no traversal or symlink components. A project-base path is `worktrees` or beneath it. A main-base path has at least two components and excludes `.git`, `.project` and `.project-local`; for example `worktrees/example-project` or `development/trees/example-project`. `development.worktree` uses the same base and must be strictly beneath that configured directory, e.g. `worktrees/example-project/wi-example`. Resolve it through `project_runtime.py worktree-path <id>`; `worktree-root` resolves the containing directory. Metadata remains readable without a machine binding; resolving main-workspace destinations requires a verified binding.

New projects track an empty `worktrees/.gitkeep` and ignore all other contents; code Git state belongs to each code repository. The placeholder survives cloning, including when code is placed externally. The original whole-directory ignore form remains valid for existing standalone projects. Do not change an existing development's location by merely editing configuration.

## Work item

`workitems/<id>/item.json`:

```json
{
  "id": "wi-example",
  "title": "One independently deliverable outcome",
  "kind": "development",
  "status": "new",
  "archived": false,
  "depends_on": [],
  "split_from": null,
  "repository": "service",
  "owner": null,
  "development": null,
  "delivery": {"required": ["merged"], "status": "pending", "evidence": []},
  "cleanup": "not_applicable"
}
```

| Field | Contract |
| --- | --- |
| `kind` | `development` has at most one development; `aggregate` has no code repository or worktree. An oversized incoming development item can await decomposition. |
| `status` | `new`, `in_progress` (alignment/design), `developing` (exclusive implementation claim), `awaiting_delivery`, `done`, `cancelled`. |
| `depends_on` | Prerequisite item IDs. Every prerequisite must actually deliver before implementation. No self edges, missing targets or cycles. |
| `split_from` | Original item ID for provenance. Does not imply a dependency. |
| `owner` | `null` or `{ "machine": "local-identity", "session": "session-id", "token": "unique-claim-token" }`. One writer for an item; developing always has an owner. The token is coordination data, not a credential. |
| `development` | `null` or `{ "worktree": "worktrees/wi-example", "branch": "feature/example", "base_commit": "full-code-commit-id" }`. The path is relative to `worktrees.base` and strictly below `worktrees.path`; optional published remote/ref and base_ref make recovery precise. |
| `delivery` | Required evidence kinds, `pending` or `delivered`, and evidence objects with `kind` and `reference`. Add ref/commit/PR/release and checked-at facts as needed. |
| `cleanup` | `not_applicable`, `pending`, or `done`. Independent of delivery and dependency readiness. |

Use a nonempty `delivery.required`, normally `["merged"]`. Aggregate items normally use `["dependencies"]`, with evidence explaining coverage of their own acceptance criteria. For deployment/release requirements add explicit kinds. `done` requires delivered evidence matching every required kind; a cancelled item never satisfies a prerequisite. User status corrections preserve the explanation and actual evidence; they do not fabricate a merge or release.

`requirement.md` contains outcome, scope, acceptance, delivery requirements and relevant project-context links. Avoid code detail during ordinary work-item management. `spec.md` describes only current Why/What, including the consequences of confirmed constraints. Its frontmatter is the only design-status field. Record approval provenance and reviewed spec/base identities in `reviews/<review-id>.md`; implementation progress belongs in `handoff.md`.

For an aggregate, `repository` and `development` are null and cleanup is not applicable. Preserve `split_from` references and archived nodes. When a dependency is cancelled or requirements change, reconsider dependent readiness and current review; do not silently bypass the edge.

## Backend receipt

`.project/sync/<id>.json` records `intent_id`, `content_sha256`, `state` (`pending`, `unknown`, `verified`), `external_id`, `baseline_fields`, `git_source_commit`, and `checked_at`. Before first creation, unknown fields may be null. Preserve operation/result evidence as additional fields. The baseline is the last confirmed Aone projection, never an assumption that a failed operation succeeded.

`project_runtime.py digest <id>` computes the synchronized business revision: sorted workspace-relative paths under `workitems/<id>/`, each followed by NUL, file bytes, then NUL; for `item.json` use canonical compact sorted-key UTF-8 JSON with `owner` removed. Backend receipts live outside the item and do not participate. An owner-only release therefore does not require another business-content sync. Keep operational journal detail in the receipt, and avoid changing the business record merely to record its own synchronization result.

Evidence records have their separate [evidence schema](evidence.md). The helper validates structure; source truth, acceptance coverage, design-review independence and live backend outcomes still require actual evidence.
