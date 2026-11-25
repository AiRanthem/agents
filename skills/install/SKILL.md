---
name: install
description: Install, update, repair, or verify this dev-kit's shared skills on the current machine. Use the installation source from the skill's own checkout when invoked from another repository.
---

# Install

Make the repository's shared global skills active on the current machine while preserving unrelated local configuration. A caller may supply an additional authorized installation contract; this shared skill does not discover or select platform implementations.

## Source and selection

Resolve this file's physical path at `skills/install/SKILL.md` to locate the dev-kit repository root. Use that checkout as the installation source even when invoked from another repository. Limit writes to the destinations covered by the selected installation contracts.

Read the dev-kit repository `AGENTS.md` and `skills/INSTALL.md` completely before changing installation targets. Use the shared installation contract and any additional contract already supplied by the caller; do not infer another contract from runtime identity.

Use the selected installation documents as the contract for destination paths, merge behavior, validation, and restart or trust steps. An explicit install, update, or repair request authorizes the local writes described by those documents. A verification request inspects and reports the installed state.

## Data preservation

Inspect every destination before changing it. Create an empty target and reconcile entries whose ownership is established by the selected contract. An unchanged copy of a previously shipped file is managed when its contents match a known installation revision. If ownership is unclear or the destination includes local changes, show the relevant difference and obtain the user's decision before replacement. Continue independent authorized work while waiting.

Merge structured configuration at the documented key or array boundary. Preserve unrelated entries and validate the complete result before replacing the destination file.

## Completion

Run every verification required by the selected installation documents. Report the supplied installation contracts, installed links, merged configuration entries, validation results, and any remaining interactive trust or restart step.
