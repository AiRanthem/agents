---
name: upgrade-project
description: Refresh an existing managed project's AGENTS.md and management prompts against the current installed project skills and templates, preserving project-specific instructions and facts. Use for repeatable project-protocol prompt upgrades. Excludes work-item identity or data migrations, code changes, and host skill installation.
---

# Upgrade Project

Bring the selected project's management instructions into agreement with the current shared project protocol. A successful upgrade preserves the project's own requirements, constraints and recovery facts, removes conflicting copies of superseded shared rules, and produces no further changes when repeated against the same sources.

Use the current management root, or an explicitly selected project root when invoked elsewhere. Read its applicable instructions and `.project/project.json`; resolve ambiguous project selection before writing. A request to upgrade the project's prompts authorizes the resulting management checkpoint through [persistence](../manage-workitems/references/persistence.md).

## Establish the current sources

Resolve this installed skill's physical path to locate the sibling project skills and [workspace templates](../create-project/assets/workspace). Discover template files including hidden directories. Read the current [project context](../manage-workitems/references/project-context.md), the templates corresponding to the destination documents, and the shared references or skill bodies needed to understand changed behavior. Follow an explicitly selected target source when supplied; otherwise the installed sources define the target. Do not infer it from an old project copy, a remembered release, or the data schema version.

Identify the source snapshot with its repository revision and relevant file hashes when it has local changes, or file hashes when no revision is available. Recheck the relevant sources before publication if they changed during the task. Updating the shared skills themselves belongs to their installation workflow, not this project upgrade.

Read the project's management prompts and their routing links. Typical destinations are root `AGENTS.md`, `.project/workflow.md`, `.project/recovery.md` and, when associated, `.project/main-workspace.md`. Inspect `.project/context.md` only for relevant context or embedded management instructions. Include other project-owned prompt documents when the current protocol routes to them and the publication mechanism supports their paths. Do not scan source code or treat work-item requirements, specs and review records as prompt templates.

## Reconcile instructions

Compare behavior and responsibility, not just template text. Rules about the shared lifecycle, ownership, synchronization and skill routing belong to the shared protocol unless an existing user decision establishes a deliberate project exception. An upgrade request authorizes replacing their outdated copies. A rule's presence in a project file alone does not establish an approved exception.

- Replace outdated shared behavior with the current rule and remove contradictory duplicates across the selected documents. Keep common protocol detail in the installed shared skills, with concise project entrypoints and links.
- Preserve project-specific requirements, background, terminology, delivery obligations, permissions, repository references and main-workspace routes. Retain unaffected local wording. Fill template values from verified project metadata and existing facts; never copy unresolved placeholders or replace a project document wholesale with a generic template.
- Preserve explicit user decisions. Ask only when the current protocol conflicts with an established project-specific decision and existing authorization does not resolve which behavior should apply. Name the conflicting requirements and their sources; continue any coherent independent prompt updates. Do not weaken a business, delivery or permission constraint merely because a template omits it.
- Add a missing management entrypoint only when the current protocol requires it and its project facts are known. Keep data, work-item IDs and references, ownership, status and delivery evidence intact. A prompt upgrade does not authorize schema or identity migration, remote reconfiguration, code/worktree changes, edits to a separate main workspace, or machine configuration changes.
- Keep repeated upgrades stable: avoid timestamp-only edits, mandatory version stamps, duplicate sections and cosmetic rewrites of already aligned instructions. No change means no publication or empty commit.

## Publish and verify

Prepare the semantic changes outside tracked paths and publish only the changed management prompts with observed byte guards through the current [persistence contract](../manage-workitems/references/persistence.md). Review the complete resulting instruction chain, including project-specific overrides, before publication. If another writer changed the inputs, refresh and reconcile again; do not overwrite the newer text. If the current runtime cannot validate or publish this project's records or paths, report the specific compatibility gap without bypassing its gates or silently performing a data migration.

Verify the resulting Markdown and links, resolved template values, preserved project instructions and the current runtime's structural checks. Check that work-item records, backend receipts, code and local bindings were not changed by the prompt checkpoint. Prompt-only updates do not alter the Aone work-item projection or require new item synchronization. Confirm the selected remote ref contains the intended changes before reporting persistence success; distinguish an already current project, a published upgrade and an incomplete upgrade.

Report the target source snapshot, changed paths and substantive behavior changes, preserved local constraints, actual validation and any unresolved conflicts. Keep this report outside the project unless the user requests a durable record; repeat execution must not create churn just to record that it ran.
