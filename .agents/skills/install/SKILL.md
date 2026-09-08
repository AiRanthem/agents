---
name: install
description: Install, update, repair, or verify this repository's shared skills and the active Agent's configuration on the current machine.
---

# Install

Make the repository's checked-in configuration for the active Agent and its shared global skills active on the current machine while preserving unrelated local configuration.

## Source and selection

Resolve the physical path of this `SKILL.md`. Derive the dev-kit repository root from the `.agents/skills/install/SKILL.md` layout, and keep every discovery and installation action scoped to that root.

Read the dev-kit repository `AGENTS.md`, then discover installation documents with `rg --files --hidden -g 'INSTALL.md' <dev-kit-root>`.

Always select `skills/INSTALL.md` to install the shared skills globally. Identify the active Agent from the runtime identity, then select only the top-level directory whose name matches that Agent and contains an `INSTALL.md`; for example, Codex selects `codex/INSTALL.md`. Read the selected documents completely before changing their targets.

When the active Agent cannot be identified reliably or has no matching installation document, stop the Agent-specific installation and report the missing match. Continue with the shared skills only when the user's request permits a partial installation.

Use the selected installation documents as the contract for destination paths, merge behavior, validation, and restart or trust steps. Treat an explicit install or update request as authorization for the local configuration writes described by those documents.

## Data preservation

Inspect every destination before changing it. Compare regular files and directories with their checked-in replacements. When a destination contains content absent from the repository, present the exact difference and obtain the user's decision before replacement.

Merge structured configuration at the documented key or array boundary. Preserve unrelated entries and validate the complete result before replacing the destination file.

## Completion

Run every verification required by the selected installation documents. Report the active Agent, selected installation documents, installed links, merged configuration entries, validation results, and any remaining interactive trust or restart step.
