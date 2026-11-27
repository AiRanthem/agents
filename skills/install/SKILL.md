---
name: install
description: Install, update, repair, or verify this dev-kit's shared skills and applicable host configuration. Use the installation source from the skill's own checkout when invoked from another repository.
---

# Install

Make this dev-kit active for the target agent host while preserving unrelated local configuration.

## Source and selection

Resolve this file's physical path at `skills/install/SKILL.md` to locate the dev-kit repository root. Use that checkout as the installation source even when invoked from another repository. Limit writes to the destinations covered by the selected installation contracts.

Read the dev-kit repository `AGENTS.md` and `skills/INSTALL.md` completely. Use only the shared contract for a shared-only request. For host setup, use the caller's authorized host contract if supplied. Otherwise, take the target host from the user's request, default to the active agent host, and read `INSTALL.md` in that host's top-level directory in the same checkout. If the host is unclear or its contract is missing, complete only the authorized shared work and report the gap.

Use the selected installation documents as the contract for destination paths, merge behavior, validation, and restart or trust steps. An explicit install, update, or repair request authorizes the local writes described by those documents. A verification request inspects and reports the installed state.

## Data preservation

Inspect every destination before changing it. Create an empty target and reconcile entries whose ownership is established by the selected contract. An unchanged copy of a previously shipped file is managed when its contents match a known installation revision. If ownership is unclear or the destination includes local changes, show the relevant difference and obtain the user's decision before replacement. Continue independent authorized work while waiting.

Merge structured configuration at the documented key or array boundary. Preserve unrelated entries and validate the complete result before replacing the destination file.

## Completion

Run every verification required by the selected installation documents. Report the contracts used, installed links, merged configuration entries, validation results, and any remaining interactive trust or restart step.
