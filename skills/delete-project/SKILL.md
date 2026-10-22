---
name: delete-project
description: Inspect and remove an explicitly selected local managed project through a program-generated exact removal manifest. Preserves remote branches and Aone history by default; may run outside the project. Does not delete individual work items or prune unrelated Git state.
---

# Delete Project

Use installed `manage-workitems/scripts/project.py --root PROJECT removal-plan` for the selected local project. The program resolves project identity, local resources, unpublished content, synchronization and remote recoverability. Read the returned exact manifest and reported blockers; do not assemble paths, inspect Git/Aone, choose preservation/recovery actions or edit manifest YAML yourself.

The manifest accounts for item-owned worktrees both inside and outside the project and preserves the main workspace, shared roots, environments, source checkouts, sibling projects and unrelated worktrees. Remote project/code branches and Aone history stay outside default local removal. A request to remove a project does not authorize discarding unpublished code or deleting remote resources.

Complete already-authorized independent preservation through the program's returned inputs before asking about deletion. If a blocker or missing input remains, report its listed facts; do not remove those resources. Present the exact reviewable manifest and obtain explicit authorization unless this same concrete manifest is already authorized. The instruction requiring this confirmation is this skill's exact-manifest boundary; explain it when confirmation is needed.

After authorization, execute `remove --manifest ID --confirm DIGEST` with the program-returned ID/digest. The digest guards the selected manifest; it is not user approval. The program rechecks state and performs only the authorized removal. Changed state requires a fresh manifest rather than broadening deletion. Follow returned results and report actual removed/preserved resources, remaining blockers and retained history. A partial outcome permits only a program-returned resume command; otherwise report the unresolved result without choosing another recovery path.

The removal manifest includes retained generations/worktrees and the resource registry recovered from the preserved project remote. Report that retained registry and remote-resource responsibility. Unsettled archive/collection intents block removal until their original operations settle; removing local project files does not authorize remote ref deletion.
