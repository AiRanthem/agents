# Git publication and single-writer coordination

Git is authoritative. A checkpoint succeeds only when its final revision is verified on the chosen remote branch and all enabled backends have verified the intended business revision. Intermediate local drafts are allowed. A push alone with pending Aone synchronization is partial persistence, not completed persistence.

## Prepare without racing the workspace

Use a unique session ID and per-claim random token. Store local identity and drafts under `.project-local/`. Do not let multiple agents edit tracked files directly in the same checkout. Prepare a bundle from an observed clean snapshot; let the publication helper serialize local Git operations using a lock in the actual Git common directory. The lock is released by process lifetime, not elapsed-time stealing. Guard sources, intent schema, digest sourcing and receipt batching follow [publish-cookbook](publish-cookbook.md); `scripts/make_bundle.py` assembles bundles from committed and working-tree state.

Example bundle shape (hashes shown here are explanatory placeholders):

```json
{
  "checks": {"workitems/1-quota-lock/item.json": "sha256-of-observed-bytes", "workitems/1-quota-lock/requirement.md": null},
  "writes": {"workitems/1-quota-lock/item.json": "complete JSON text", "workitems/1-quota-lock/requirement.md": "Complete requirement text\n"},
  "message": "Align 1-quota-lock acceptance",
  "session": "current-session-id",
  "token": "current-owner-token"
}
```

Every write has an observed SHA-256 guard, or `null` when absence was observed. Every item-file or `.project/sync/<id>.json` mutation also guards that item's `item.json` and obeys its ownership; guard other records on whose unchanged state the decision depends. Use Python to encode exact text and hashes, not shell interpolation. `writes` replaces complete UTF-8 files. Deletion of work-item history is not supported. Invoke `project_runtime.py publish --bundle <local-json-path>` from the project root, or put `--root <workspace>` before the subcommand.

The helper obtains the latest selected remote ref, checks all guards/ownership, validates the prospective complete DAG, creates a commit with an alternate index, and non-force pushes exactly that ref. It then fetches that ref again and checks commit inclusion, intended writes, remaining guards and storage authority. Success returns both the candidate `commit` and `verified_remote_commit`; an unrelated later remote commit may legitimately be present. It refuses a dirty/staged management checkout, an in-progress Git operation, unsafe paths or a changed storage authority. It fast-forwards the local checkout to the verified remote state; it never auto-stashes, resets, force-pushes or overwrites a conflicting item.

Disjoint stale-clone changes may replay against a newer remote revision when every guard still holds. A concurrent same-item claim has one winner. Non-fast-forward or ambiguous transport outcomes require fetching the selected ref and verifying exact ancestry/content before any retry. Do not interpret failed push output as proof the remote was unchanged. Preserve the bundle and intended commit identity for recovery.

Hierarchy codes are allocated by successful Git publication, without a separate reservation or lock. The merged-tree validator rejects duplicate codes even when their phrases and file paths differ, such as `12-alpha` and `12-beta`. If a candidate loses to another published allocation, verify that its own publication did not succeed, refresh the selected remote state, and regenerate the unpublished IDs and all corresponding paths, dependencies and `split_from` references together. Publish the revised batch with fresh byte guards; never renumber the winning records or create an external backend item before its Git identity is durable.

## Checkpoint protocol

For a Git-only item, a guarded publication can claim, change and release ordinary short-lived ownership in one checkpoint, provided an active remote owner is never bypassed. For development or a multi-step backend operation, publish and retain an owner across the operation. Do not start implementation merely because a local claim exists.

With Aone, use this ordered protocol:

1. Publish owner + final business revision + a unique pending sync intent. No Aone mutation occurs before the Git claim succeeds.
2. Synchronize the immutable business revision to Aone using [the backend contract](aone.md). Compare remote fields to the last verified baseline first. Keep the same intent ID across retries and recovery.
3. Read back the actual Aone result and publish a receipt with its external ID, confirmed fields and matching business digest. Release short-lived ownership when appropriate; retain development ownership. Verify the selected remote Git result before reporting full success.

Git and Aone have no distributed transaction. If any stage fails, preserve the active claim and pending/unknown operation. Do not roll back a remote claim merely because a later step failed. An `unknown` create must be reconciled by correlation marker and actual Aone lookup before another create is considered. Do not silently disable a configured backend.

Every final business update, including status, acceptance, dependency and full spec changes, follows this protocol. Batch exploratory edits at meaningful closure points such as aligned requirements, agreed decomposition, completed design or implementation handoff. Do not push every sentence, and do not leave a completed task represented only by local edits.

For an explicitly authorized shared development, each participating item remains independently gated and keeps its own owner and backend receipt. Claim all items atomically in one guarded bundle, using the same machine/session/token and development identity. Do not mix credentials or begin shared code writes if any item is owned by another writer. Include all business changes in the pending revisions before backend synchronization; publish one pending intent per item, synchronize each configured backend item, then publish the verified receipts together. Once all readbacks match and the writer stops, eligible owners may be released in that same receipt bundle. A later owner-only batch also needs no backend sync.

## Limits and handoff

The runtime validates record structure and concurrency guards; an agent must verify review, delivery and external-service evidence. Tokens coordinate cooperating agents; access controls remain those of Git and Aone. Aone's API has no verified compare-and-swap in this version, so field comparison cannot prevent a human write racing between comparison and update.

An item's records may only be written by a bundle whose session and token equal the current owner, or by a new claim when the item is unowned; a claim's `owner.session` must equal the bundle session. A guarded bundle can claim or update several items atomically, with ownership checked independently for each item. There is no mid-implementation takeover, because `developing` requires a non-null owner and a release is only valid once the target status accepts a null owner. When an active writer stops, a user-authorized recovery coordinator confirms the writer stopped, settles in-flight or unknown backend outcomes, and catches up every participating item's business records before backend synchronization. While the old owner remains recorded, every guarded recovery write to those items, including business catch-up, uses that owner's recorded session and token. At handoff, publish the status advance and final business revisions together, synchronize them, then publish verified receipts. Once every readback matches and the writer has stopped, eligible owners may be released in that receipt bundle. Preserve the handoff reason and evidence. Never infer that an owner stopped from age or silence. This version does not provide forced or automatic claim takeover.

The helper deliberately does not reconfigure `storage` during publication. Changing the authoritative remote requires a separately agreed migration with writers stopped and verified history; editing a JSON field is insufficient.
