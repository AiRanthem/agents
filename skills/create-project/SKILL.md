---
name: create-project
description: Create a durable project workspace on a dedicated Git branch, standalone or associated with a business main workspace. Establish metadata, necessary background and supplied requirement skeletons; creation ends before design or development. May run outside a managed project.
---

# Create Project

Create the selected management workspace directly using ordinary file and Git tools. Reuse the user's selected destination, name, storage repository/ref and backend choices. Ask only for missing consequential choices. This dev-kit's Git namespace is not a default for other repositories.

Read the [project layout](../manage-workitems/references/schema.md) and adapt the [workspace template](assets/workspace/AGENTS.md). Write configuration, background, instructions and supplied requirement skeletons at their final paths. Preserve unrelated destination content; use an independent checkout and dedicated branch so the associated main workspace keeps its existing branch and files. Read its original instructions and record its actual location and constraints through [main-workspace association](../manage-workitems/references/main-workspace.md).

Record the selected Git destination and optional external backend explicitly. If Aone is selected, use the actual configured space and type/status mappings through available authenticated tools. Report unresolved configuration or synchronization honestly; do not substitute another backend or create an external project without authorization.

Assign unused work-item IDs under the existing hierarchy. Record the user's goal, known scope, acceptance and delivery obligations; leave unknown details unresolved. Creation alone does not authorize source investigation, design, decomposition, implementation or code worktrees.

Commit the created project files and push the selected dedicated branch. Preserve local files and commits if publication fails, and report the actual result. Creation authorizes this project metadata publication; code submission, remote deletion and unrelated branches retain their own authorization boundaries. Report the absolute root, branch/backend, item IDs and titles, and unresolved requirements. Proceed to design only when requested.
