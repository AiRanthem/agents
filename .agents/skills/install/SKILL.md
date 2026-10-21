---
name: install
description: Install, update, repair, or verify this repository's shared skills on the current machine.
---

# Install

Make the repository's shared global skills active on the current machine while preserving unrelated local configuration. A caller may supply an additional authorized installation contract; this shared skill does not discover or select platform implementations.

## Source and selection

Resolve the physical path of this `SKILL.md`. Derive the dev-kit repository root from the `.agents/skills/install/SKILL.md` layout, and keep every discovery and installation action scoped to that root.

Read the dev-kit repository `AGENTS.md` and `skills/INSTALL.md` completely before changing installation targets. Use the shared installation contract and any additional contract already supplied by the caller; do not infer another contract from runtime identity.

Use the selected installation documents as the contract for destination paths, merge behavior, validation, and restart or trust steps. Treat an explicit install or update request as authorization for the local configuration writes described by those documents.

## Data preservation

Inspect every destination before changing it. Compare regular files and directories with their checked-in replacements. When a destination contains content absent from the repository, present the exact difference and obtain the user's decision before replacement.

Merge structured configuration at the documented key or array boundary. Preserve unrelated entries and validate the complete result before replacing the destination file.

## Completion

Run every verification required by the selected installation documents. Report the supplied installation contracts, installed links, merged configuration entries, validation results, and any remaining interactive trust or restart step.
