---
name: create-project
description: Create a durable project workspace on a dedicated Git branch, standalone or associated with a business main workspace. Establish metadata, necessary background and supplied requirement skeletons; creation ends before design or development. May run outside a managed project.
---

# Create Project

Create the selected independent management repository through installed `manage-workitems/scripts/project.py`. Read the [command contract](../manage-workitems/references/commands.md). Reuse already selected destination, name, storage repository/ref and optional backend/association choices; ask only for missing choices required by the program. This dev-kit's `devkits/` Git namespace is not a default for other repositories.

Write necessary background as Markdown and run typed `init DESTINATION --id ID --name NAME --storage-url URL --storage-branch BRANCH --context-file FILE --publish`. For an associated workspace, provide its typed identity/repository/root and `--main-workspace-context-file`; for code repositories, provide the typed repository inputs. The program constructs YAML, renders instructions, establishes the independent repository and exact scoped ref, validates and publishes. Do not write configuration JSON/YAML, copy templates manually or repeat Git/Aone setup checks. Initialization without `--publish` is local preparation only.

The program owns empty-directory, selected-ref and unrelated-content boundaries. A main workspace keeps its own checkout and branch; association preserves original instruction routes, business constraints and separate environment. See [main-workspace association](../manage-workitems/references/main-workspace.md). Do not weaken its permission boundaries or copy its files/history into the project branch. Main-workspace code or configuration publication needs its own authorization.

If Aone is selected, supply the actual existing space, type/category and required status mappings through the supported typed inputs. Missing authentication or unsupported configuration stops with the program's reported facts; it does not authorize dropping the backend or creating another external project.

Record supplied requirements afterward with `begin create --title TITLE --slug SLUG` in the new project. Read its full returned payload and original external instructions, fill only the returned requirement/context drafts, execute its `finish_command` unchanged, then follow the [fixed status branch](../manage-workitems/references/commands.md#fixed-write-workflow). Unknown scope, acceptance or delivery details stay unresolved. Do not investigate source, split, generate a spec, claim implementation or prepare a code worktree merely to complete creation.

Creation authorizes project metadata publication to the selected dedicated ref; code submission, remote deletion and unrelated branches retain their own boundaries. After project metadata and supplied requirement skeletons are persisted, report the absolute root, selected branch/backend, full item IDs with titles, unresolved requirements and actual returned status. Enter design only when the user separately requests it, including an explicit design request in the same message after creation completes.
