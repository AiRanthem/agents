---
name: cleanup-worktree
description: Audit a completed development worktree across relevant remotes, verify its work reached at least one remote trunk, then remove only the exact worktree and branch resources the user confirms, including verified rebase safety branches. Use for post-development cleanup; do not use for abandoning unmerged work or general Git pruning.
---

# Clean Up a Completed Worktree

Prove that the development work reached a remote trunk, present one exact cleanup manifest with its effects, and execute the confirmed deletion without losing local work or touching unrelated resources.

## Project workitems

When cleaning a worktree for an item in a valid project workspace, load [the shared project context](../manage-workitems/references/project-context.md) and follow project workflow, evidence, and persistence rules. A project item's `done` delivery record is not by itself proof that this skill's cleanup gate passed: preserve the existing authoritative merged-request and work-accounting requirements, and report when direct source integration has no qualifying PR/MR evidence path. Project cleanup can remove only the confirmed local worktree and local branch; never delete its remote branch or other remote ref. Record project state through the designated runtime only after the cleanup result is verified. Keep the exact manifest, user confirmation, local safety checks, and pre-mutation refresh required below. Outside a valid project workspace, retain the generic cleanup behavior.

Resolve project item paths with `project_runtime.py worktree-path <id>` before preparing the manifest. Associated main-workspace worktrees may be outside the project root. Preserve that main workspace, its shared environment/source repositories and sibling projects; an unavailable or conflicting binding prevents removing the affected worktree.

## Establish scope and request direction

Identify the target worktree, local branch, `HEAD`, upstream, fork point, corresponding remote source refs, and a surviving worktree for execution. Inspect configured fetch and push URLs, refspec mappings, branch configuration, and worktree use; do not assume `origin`, matching branch names, or a single provider. Keep searches and output limited to candidate refs after discovering the mappings.

Use the conversation and available memory to discover request identifiers, publication destinations, branch renames, and any `rebase-worktree` report. Verify remembered candidates live. A safety branch must come from that report's exact full ref and original `HEAD` OID, never a naming pattern.

Classify requests by source repository and direction before deciding eligibility:

- **Outgoing:** the candidate branch is the source. These requests establish delivery and may still need the source branch. Query every relevant provider for current and historical outgoing requests, including multiple requests for the same source. Use exact source repository and branch, remembered identifiers, and commit lookup when supported and appropriate for that provider.
- **Incoming:** another branch proposes merging into the candidate. These do not prove that the candidate's own work is unmerged and do not block cleanup solely because they are open. Preserve their source branches and requests unless separately authorized. Include the effect of deleting their target in the cleanup report: the provider may close or invalidate them. Respect a user's explicit instruction to ignore incoming requests; if the user requires them to remain usable, retain their target branch.

A development branch does not become a protected or shared trunk merely because a bot request targets it. Verify its actual role and protection. Known provider effects belong in the same confirmation boundary; do not promise that incoming request states will remain unchanged after target deletion.

Use an authoritative CLI or API and its actual state-filter and pagination semantics. An empty response to an unsupported filter is not exhaustive evidence. Do not send internal commit IDs or private code to public searches.

Report query gaps against the decision they affect. Preserve a ref when its current outgoing request state, qualifying merge, or unique work cannot be verified. A limitation in enumerating old terminal requests does not by itself invalidate an authoritative merge of the exact current source tip when all its work is accounted for and supported current-state queries find no active outgoing request. Disclose that limitation without claiming exhaustive history or repeatedly probing unsupported filters. Stop if a relevant unresolved request could still need the proposed source ref.

## Build the cleanup gate

List each discovered request with provider, repository, identifier, URL, direction, source and target branches, source commit when available, and live state. Distinguish merged, open, draft, closed or declined without merge, and unknown.

Cleanup is eligible when:

- at least one outgoing request is authoritatively merged into an established remote trunk, and its merge result is in that trunk's current tip;
- the local tip and every proposed branch contain no work unaccounted for in the verified merge;
- no proposed branch is default, protected, release, a separately established shared/base branch, checked out by another worktree, or still needed by an open, draft, or unresolved outgoing request;
- the target has no staged, unstaged, untracked, ignored, submodule, linked-worktree, or in-progress state that could be lost; and
- each deletion is allowed by repository instructions and names an exact path or full ref and current OID.

Honor a user's stricter delivery rule, such as requiring all outgoing requests to be merged; report any exception rather than silently relaxing it to the one-trunk criterion.

For ignored or other local files, list exact paths and their intended disposition. Execute already-authorized file deletion or preservation without asking again. Otherwise include their disposition in the same reviewable confirmation instead of ending the audit with an empty manifest; the local safety gate must pass after that disposition and before branch/worktree removal. Do not assume ignored files are disposable or use forced worktree removal to bypass them.

For a safety branch, verify its exact ref still points to the report's original `HEAD`, and that the original work is accounted for in the rebased branch and merged trunk. Preserve an unverified safety candidate.

Use ordinary ancestry when it proves inclusion. For squash or rebase merges, account for every branch-only commit with stable patch IDs or range-diff and verify the resulting changes in the current target tree. A changed commit message is not lost work. Compare the affected paths rather than requiring whole-tree equality with a trunk that has unrelated changes. Provider status alone is insufficient.

## Keep the audit bounded

Batch independent local reads and provider queries. When delegation is available and required or useful, give one executor the complete provider audit while the lead checks local safety and merge inclusion; avoid multiple short handoffs for the same investigation.

Keep merge evidence keyed by source, base, and target OIDs. Reuse patch/tree evidence while those OIDs are unchanged. Fetch only missing relevant objects; an isolated temporary repository is a fallback when shared-repository writes are unavailable, not a mandatory extra audit.

Complete one initial audit and one refresh immediately before deletion. Between them, re-evaluate changed scope or supplied authorization using the existing evidence; repeat only checks whose state or inputs changed. Required instruction reloads still apply. Keep raw evidence in a compact artifact when useful; report the decision, exact manifest, exclusions, and relevant gaps without repeatedly dumping full ref lists or logs.

## Confirm one exact manifest

Before branch/worktree deletion, present the eligibility evidence, full observed request-status list, exact paths, local branch refs/OIDs (including verified safety refs), remote names and full refs/OIDs, related administrative metadata, local-file dispositions, and expected provider effects. Keep unsafe or uncertain resources outside the manifest.

Ask for confirmation of that exact manifest unless it was already explicitly confirmed in the conversation. Inspection alone is not deletion authorization. Authorization to delete specified ignored files does not authorize deleting branches or worktrees.

Before mutation, changes to relevant request states, branch OIDs, worktree contents, or the confirmed manifest require a refreshed report and confirmation. An unrelated background fetch is not a manifest change.

## Execute and verify

Immediately before mutation, refresh the relevant outgoing request states, discovered incoming request states/effects, and exact proposed remote refs. Repeat local safety, OID, protection and worktree-use checks, including safety refs. Preserve disclosed gaps and exclusions. Stop before partial cleanup if a gate or confirmed item changed. Record surviving worktrees and candidate refs for final comparison close to this mutation boundary.

- Operate from a surviving worktree. In generic mode, delete only confirmed remote source refs through the resolved mappings, never force-push, and verify each exact remote ref is absent before removing its local recovery copy. In project mode, retain every remote ref and remove only confirmed local resources.
- Remove registered worktrees with `git worktree remove`, not `rm -rf`, `git clean`, or forced removal for unresolved contents. Delete confirmed local branches normally when ancestry permits; use forced local deletion only when the confirmed provider state, per-commit patch comparison, and target tree jointly prove that a squash or rebase merge preserved the work.
- Remove only administrative metadata made stale by these exact deletions. Do not delete unrelated tracking refs, tags, stashes, other worktrees, request objects, or configuration. Observe and report any provider-driven request transition after deleting a source or target; do not call request-mutation APIs or reopen a request without authorization.
- If an operation fails or an unexpected change affects remaining cleanup safety, stop and report the partial state and recovery options. Do not broaden deletion or recreate resources automatically.

Completion requires worktree/branch re-enumeration, target path and registration absence, live absence of each deleted remote ref, and comparison of surviving worktrees and retained candidate refs. Other sessions may advance unrelated remote-tracking refs; inspect reflog timing to distinguish those updates from this cleanup, preserve them, and report the distinction rather than reverting them or failing an assertion that every ref must be unchanged. Report each removed, retained, or failed item and material provider effects; command exit codes alone do not prove completion.
