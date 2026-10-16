# Project command contract

Run `<PYTHON> <installed-manage-workitems>/scripts/project.py --root <project> COMMAND`. `<PYTHON>` is the current workspace's prescribed Python 3 executable/environment; use that environment for every command and its returned continuation. Resolve the installed skill's physical path once. Git and [the declared Python dependencies](../scripts/requirements.txt) are required; enabled Aone also requires authenticated `a1`.

When dependencies are missing, install them into the workspace-selected environment with `<PYTHON> -m pip install -r <installed-manage-workitems>/scripts/requirements.txt`. If that environment is missing or cannot install packages under its instructions, report the missing prerequisite rather than switching to system Python. The ordinary agent interface uses typed command options and Markdown files.

Work-item writes use the following `begin`/`finish` workflow. Shared knowledge commands are direct typed CLI operations described in the operations table; they use returned body paths and hash guards and do not use `begin`.

## Fixed write workflow

1. Run `begin OP [ID]` with the requested operation's typed inputs.
2. Read every entry in the returned `read` payload completely. Read any required original instruction path returned for an external main workspace. Use only `editable` absolute paths for Markdown writes; the program supplies their initial content and publication destinations.
3. Only `ready` returns a `finish_command`; run it unchanged, including when `editable` is empty. The `finish` CLI accepts result/provenance options only for `design-review`: after assessment, add its actual `--result pass|fail --provenance SOURCE` to that returned base command. `development-finish` review evidence is supplied to `begin`, never added to the finish command.
4. Follow the returned status without expanding the workflow:

| Status | Action |
| --- | --- |
| `ready` | Read its inputs, edit its returned drafts and finish; a diagnostic status without an edit payload is reported as ready. |
| `published` | Report the completed checkpoint and end. |
| `no_op` | Report no change and end; there is no new publication. |
| `partial` | Execute only its `next_command` (resume of the retained operation), then apply this same status table. |
| `blocked` | For `code: stale_ticket`, execute only the returned `next_command` to begin the same operation with current inputs. For `code: stale_evidence`, the program returns no `next_command` or `finish_command`; obtain current authorization/review evidence and report the blocker. Otherwise report the exact blockers/missing facts and stop the affected operation. |

`status` reports current facts and the same fixed recovery branch. Do not create a replacement operation while an outcome is uncertain. Program-owned YAML, receipts, IDs, owner tokens, hashes, version increments, DAG checks and Git/Aone inspection are not agent work. The JSON `apply` interface and lower-level runtime helpers are legacy diagnostics, not an alternative write route.

## Operations

`ID` accepts a full ID, hierarchy code, phrase or exact title. Ambiguity is reported with candidates. Use the returned full ID in later operations. Supply actual user decisions and evidence; a command option is an assertion whose truth the agent must establish.

| Operation | Typed inputs and Markdown purpose |
| --- | --- |
| `create` | `--title TITLE --slug SLUG`; optional `--parent ID`, `--repository ID`, `--kind development\|aggregate`, repeated `--depends-on ID` and `--delivery-required KIND`. Fill the returned requirement and context drafts. |
| `fix ORIGINAL` | `--title TITLE --slug SLUG`; fill a new requirement/context describing the defect and acceptance. Links to the delivered original and leaves its delivered state intact. |
| `requirement-update ID` | Edit the returned current requirement draft. |
| `design-update ID` | Edit the returned complete current design draft, only for requested design work. |
| `decision-record ID` | Replace the complete current decision Markdown in the returned draft, retaining effective decisions and removing superseded text; `--approval-source SOURCE` records actual user approval of the current design. |
| `design-review ID` | Begin without a result. Read the inputs and write the independent report, then use `finish TICKET --result pass\|fail --provenance SOURCE` as declared in `finish_options`. Requires a separately user-requested independent review session. |
| `development-start ID` | `--base-ref REF --branch BRANCH --worktree RELATIVE_PATH` as required for the selected code development. Only explicit user authorization permits `--skip-design-review --approval-source SOURCE` for this unchanged contract. Publication establishes ownership before code edits. |
| `development-finish ID` | At `begin`, supply `--result pass\|fail --provenance SOURCE --reviewer-session SESSION --review-file FILE` from the actual independent reviewer; persist the review through the returned report draft, then run the returned finish command unchanged. These are required begin inputs, not finish options. |
| `delivery-record ID` | Repeated `--kind KIND --reference SOURCE` and `--provenance SOURCE`; fill the returned delivery report with actual obligation coverage. |
| `context-update ID` | Edit the returned current facts, verification and handoff draft. |
| `log-record ID` | Replace the complete current log/context Markdown in the returned draft. The program does not append machine-generated events. |
| `rename ID` | `--title TITLE`. |
| `dependency-update ID` | Repeated `--depends-on ID` for the requested prerequisite set. |
| `archive ID` | `--archived` or `--no-archived`; preserves identity, current state and dependency edges. Current pointer-bound evidence follows record retention rules. |
| `kind-update ID` | `--kind development\|aggregate`, with `--repository ID` when converting to development. A development item can become aggregate only after recorded cleanup is `done` and its worktree is absent. The program validates these structural conditions. |
| `cleanup-record ID` | `--cleanup-status pending\|done\|not_applicable --reference SOURCE`; record actual cleanup evidence after separately authorized cleanup. The default `--mode verify` checks actual removal; `--mode manual|skipped --approval-source SOURCE` records only the user's explicit cleanup disposition, without claiming a skipped removal happened. Explicit `--discard-development --approval-source SOURCE` with `--cleanup-status done --mode verify` also discards an unfinished recorded implementation after removal, retains its snapshot in the cleanup record, and invalidates prior base-bound review/waiver evidence; current implementation gates must be satisfied again. Ordinary cleanup preserves development metadata. |
| `knowledge-show ID` | Direct read-only command: `project.py --root ROOT knowledge-show ID`. Returns metadata/body/hash, a unique-per-call `body_file` path, exact guarded `update_command` and `remove_command`; an absent ID also returns absent guards and `create_required_flags`. It does not create the draft file and does not use `begin`. |
| `knowledge-update ID` | Write the complete UTF-8 Markdown body to returned `body_file` (create its parent directory if needed), then use returned `update_command` with its exact guards; append only intentional typed metadata options. Its guarded form is `project.py --root ROOT knowledge-update ID --body-file PATH --expect-metadata-sha256 HASH\|absent --expect-body-sha256 HASH\|absent`. Creating an entry also requires the returned `--repository --topic --summary --scope --kind fact\|inference\|search\|verification` values. Existing metadata is reused unless options are supplied. Repeated `--input KEY=VALUE` replaces the entire inputs mapping; repeated `--source PATH` replaces the entire sources list. Use `--clear-inputs` or `--clear-sources` to clear the mapping/list; each clear option is mutually exclusive with its corresponding repeated option. Repeated `--source-revision PATH=REVISION` and `--source-sha256 PATH=SHA256` set source metadata: each path must uniquely match a path in the current sources or the complete replacement list supplied by `--source`; an unlisted or ambiguous path is rejected. SHA256 values must be 64 lowercase hexadecimal characters. |
| `knowledge-remove ID` | Use only the returned `remove_command`, guarded by `--expect-metadata-sha256 HASH --expect-body-sha256 HASH`, to remove an explicitly obsolete/unneeded YAML/Markdown pair. Lack of an item pointer does not establish staleness. This does not use `begin`. Successful, pending or stale draft files are not automatically removed and remain uncommitted work. |

A requirement/spec change invalidates affected approval and review bindings. The program derives design versions from raw bytes: first design is version 1, a changed design increments once, identical bytes do not increment. It checks prerequisite delivery, open upstream fixes and current review/base/session bindings at each gated checkpoint, including checkpoints in an already active session.

## Reading and setup

`list --query TEXT --limit 20` is an example bounded diagnostic read; `--limit` defaults to 50. `show ID [--documents]` is also a bounded diagnostic read. These do not establish a live remote claim. V1 projects support diagnostic reading and `migrate`; ordinary work-item writes require v2. Shared knowledge commands are available through the typed command interface. Read [project context](project-context.md) for session and instruction boundaries.

`migrate` deterministically migrates schema and refreshes generated project instructions from installed sources. Use `migrate --dry-run` only when the user requests a preview. Repeat execution against identical source hashes returns `no_op`. See [upgrade-project](../../upgrade-project/SKILL.md).

After the user has selected the destination and exact storage authority, initialize using typed arguments:

```text
project.py init DESTINATION --id ID --name NAME --storage-url URL --storage-branch BRANCH --context-file BACKGROUND.md --publish
```

Code repository setup uses `--repository-id ID --repository-url URL --repository-base-ref REF`. Association uses `--main-workspace-id ID --main-workspace-name NAME --main-workspace-root ROOT`, optional `--main-workspace-url URL --main-workspace-ref REF`, `--main-workspace-context-file FILE` and `--worktrees-base BASE --worktrees-path RELATIVE_PATH`. Aone uses `--aone-space SPACE --aone-type TYPE --aone-category CATEGORY` and repeated `--aone-status LOCAL=REMOTE`. Supply only the user's actual configuration; unsupported required fields are reported by the program. Write background Markdown, not configuration JSON. The program renders templates, establishes the independent repository, validates the exact ref and publishes metadata. Without `--publish`, initialization is local preparation only. Record supplied requirements afterward through `begin create`.

`removal-plan` returns a program-owned exact local-removal manifest. After explicit authorization of that concrete manifest, `remove --manifest ID --confirm DIGEST` performs the guarded removal; see [delete-project](../../delete-project/SKILL.md).

`resume` is executed exactly as returned, including its identity file/session binding. It resumes an existing intent; it does not authorize takeover. Do not reconstruct it from local YAML or retry an uncertain external creation yourself.
