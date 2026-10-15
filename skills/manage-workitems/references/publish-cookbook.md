# Publish cookbook

This reference is the operational contract for assembling guarded publication bundles. [persistence](persistence.md) defines why checkpoints, ownership and backend ordering exist; this file defines how bundle fields derive from repository state so publication succeeds on the first attempt. `scripts/make_bundle.py` implements the derivation; `project_runtime.py publish` remains the only publisher.

## Observe committed bytes, write through the bundle

The publication helper refuses a dirty management checkout. Observe the committed bytes of every touched path at the selected remote revision and carry intended content in bundle `writes`. A guard is the SHA-256 of those committed bytes, or `null` when the path is absent there. When using working-tree edits as input, save and inspect the bundle before restoring only the captured paths to the clean snapshot; preserve unrelated edits and recovery evidence.

Fetch only the configured storage ref, inspect its resulting commit, and pass that full commit to `make_bundle.py --base <commit>`. The helper resolves the base once and uses that snapshot for guards, pending intents and digest inputs even when local HEAD is older. `--base` defaults to HEAD for a checkout already at the intended snapshot. If a touched path changed remotely, reconcile that content with the intended write before construction; choosing a newer guard alone must not overwrite an unseen change. A remote change after construction still requires reconciliation rather than a blind retry.

## Item coupling

Every write under `workitems/<id>/` and every write to `.project/sync/<id>.json` must guard `workitems/<id>/item.json` with its committed bytes, in addition to the ownership rules in [persistence](persistence.md). A bundle carries one session and one token. For explicitly authorized shared development, claim every participating item with that same owner and shared development identity in one bundle before code edits. Keep separate item intents and receipts, but batch their Git publication at each protocol stage. Existing different owners must be resolved through the ownership protocol before this shared claim; never leave an item unowned and rely on a prose instruction to freeze it.

## Sync intents and receipts

A sync intent or receipt at `.project/sync/<id>.json` carries the keys `intent_id`, `content_sha256`, `state`, `operation`, `external_id`, `baseline_fields`, `git_source_commit` and `checked_at`. The last three may be null for pending operations but must be present. The helper computes the business digest; never hand-simulate it. A pending intent can accompany the business writes it describes. A verified receipt must describe the immutable business revision already synchronized to the backend.

Batch final business edits at meaningful checkpoints: publish business writes and pending intents, synchronize that committed revision, then publish verified receipts from actual readback. Do not add business edits while completing its receipts. Owner-only release and semantically unchanged `item.json` formatting preserve the digest and can accompany a receipt without another backend synchronization. New requirements, design, handoff or status changes require a new business revision and sync. Git-only items need no backend intent or receipt.

Readback evidence is a local JSON file containing `intent_id`, `external_id`, `git_source_commit`, `content_sha256`, `baseline_fields` and `checked_at`; optional `space_id` identifies the backend space. Use the pending intent's identity and digest, the full commit actually synchronized, all normalized owned fields from the confirmed backend response, and its timezone-aware readback timestamp. Normalize `baseline_fields.status` to the backend status ID and match the intent's target. Compare all owned fields with the intended projection before passing the file to `--receipt <item>:<readback-json>`. The next update compares against these confirmed fields, including the updated title and managed description; never reconstruct them by patching an older baseline.

The helper rejects mismatched evidence identities, source revisions or digests, and rejects a receipt bundle that would change the synchronized business content. A rejected construction makes no publication or backend call. `--assert-note` may add context but cannot replace readback evidence. known-limit: the helper verifies local evidence consistency, not the truth of a backend response; the agent must perform and check the readback. An automated adapter can replace that step only after its API and recovery contracts are established.

## Ownership gates

The prospective graph validates owner against status: `developing` requires repository, development and owner, while `awaiting_delivery` and terminal states accept a null owner. A write to an owned item requires the bundle session and token to match its recorded owner. When that writer stops, use the authorized recovery path in [persistence](persistence.md): settle unknown backend outcomes, finish the business handoff under the recorded owner, synchronize it, then verify receipts and release ownership. A new writer may claim only after release; do not infer that an owner stopped from age or silence.

## Construction helper

`scripts/make_bundle.py --root <project> --base <commit> --session <id> --token <token> --message <text> --out <local-bundle.json>` assembles a bundle. Repeated `--write <path>` options capture working-tree content guarded by base bytes; `--new <path>` additionally requires absence at the base. Repeated `--intent <item>:<external>:<status>:<status-id>` options add pending update intents with prospective digests and item guards. Repeated `--receipt <item>:<readback-json>` options complete pending intents from checked readback evidence, preserving their operation identities. The helper performs no Git writes; `project_runtime.py publish` remains the only publisher.
