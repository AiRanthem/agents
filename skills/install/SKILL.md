---
name: install
description: Install or update the personal Agent configuration maintained by this repository. Use when the user asks to install, update, repair, or verify this dev kit on the current machine.
---

# Install

Make the repository's checked-in Agent configuration active on the current machine while preserving unrelated local configuration.

## Source instructions

Resolve this `SKILL.md` through its symlink to its physical path. Derive the dev-kit repository root from the `skills/install/SKILL.md` layout, and keep every discovery and installation action scoped to that root.

Read the dev-kit repository `AGENTS.md`, then discover every installation document with `rg --files --hidden -g 'INSTALL.md' <dev-kit-root>`. Read each discovered document completely before changing its targets.

Use the installation documents as the contract for destination paths, merge behavior, validation, and restart or trust steps. Treat an explicit install or update request as authorization for the local configuration writes described by those documents.

## Data preservation

Inspect every destination before changing it. Compare regular files and directories with their checked-in replacements. When a destination contains content absent from the repository, present the exact difference and obtain the user's decision before replacement.

Merge structured configuration at the documented key or array boundary. Preserve unrelated entries and validate the complete result before replacing the destination file.

## Completion

Run every verification required by the installation documents. Report installed links, merged configuration entries, validation results, and any remaining interactive trust or restart step.
