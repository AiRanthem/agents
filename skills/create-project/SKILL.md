---
name: create-project
description: Create a durable project workspace on a dedicated Git branch, standalone or associated with a business main workspace. Establish metadata, necessary background and supplied requirement skeletons; creation ends before design or development. May run outside a managed project.
---

# Create Project

Create the selected management workspace directly using ordinary file and Git tools. Reuse the user's selected destination, name, storage repository/ref and backend choices. Ask only for missing consequential choices. This dev-kit's Git namespace is not a default for other repositories.

Read the [project layout](../manage-workitems/references/schema.md) and use the [workspace template](assets/workspace/AGENTS.md), including its linked context, workflow and recovery documents. Introduce project goals, terminology and constraints for a new reader in the context document. Fill template fields from the selected project, use credential-free repository locations, identify unknown values and verify that generated documents have no unresolved template placeholders. Preserve the template's exclusions for local source. Write configuration and supplied requirement skeletons at their final paths.

Preserve unrelated destination content and the business checkout. Verify the exact selected storage ref. Start a new independent project history containing only its authorized records. If the ref already holds this project, [resume it](../manage-workitems/references/recovery.md); an unrelated tree or history needs a different destination. For an associated project, read the original instructions and record its actual location and constraints under [main-workspace association](../manage-workitems/references/main-workspace.md).

Record the selected Git destination and optional external backend explicitly. If Aone is selected, use the actual configured space and type/status mappings through available authenticated tools. Report unresolved configuration or synchronization honestly; do not substitute another backend or create an external project without authorization.

Assign unused work-item IDs under the existing hierarchy. Record the user's goal, known scope, acceptance and delivery obligations; leave unknown details unresolved. Creation alone does not authorize source investigation, design, decomposition, implementation or code worktrees.

Publish the created files on the selected dedicated branch under [project publication](../manage-workitems/references/persistence.md). Creation authorizes this project metadata publication. Report the absolute root, branch/backend, item IDs and titles, actual publication outcome and unresolved requirements. Proceed to design only when requested.
