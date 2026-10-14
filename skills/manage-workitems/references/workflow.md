# Project development workflow

One development is tied to one development item and one worktree. The project coordinates context and delivery; the existing design and implementation skills retain their substantive responsibilities.

## Dependencies and decomposition

Use a DAG: if B lists A in `depends_on`, A must deliver before B starts implementation. Independent nodes can develop in parallel from the same suitable trunk. Shared prerequisites can unlock several dependents; no duplicated dependency work or artificial single-parent restriction is needed. A provenance link does not schedule anything.

`split-workitem` has two entry points. A clearly large request can undergo enough `explore-design` to settle outcomes, boundaries, dependencies and acceptance, then split without a parent spec or parent review. A later design review can also identify excessive scope and route to splitting. Each resulting development item must obtain its own reviewed current spec; copying part of an old spec does not inherit approval.

Assess scope using expected production-code change (roughly 1,500 changed lines per PR triggers reconsideration), cohesion, independent acceptance, component ownership, review load, risky state transitions and independently releasable units. A count is evidence, not a reason to obscure necessary changes. Splits must be independently verifiable and avoid overlapping ownership that would make supposedly parallel changes conflict. Integration that remains after prerequisites is a development item; an original requirement fully covered by delivered dependencies becomes an aggregate. Verify coverage explicitly before an aggregate completes.

## Design and review

Prepare or recover the item's worktree before code exploration. Before creating a new worktree or publishing its branch, win a durable preparation claim in `in_progress`; persist its branch and full baseline identity, then release that owner at a completed design handoff. This preparation claim is distinct from the later `developing` gate. Readonly exploration may precede prerequisite delivery. An initial design records what is known and which prerequisite assumptions remain; it must not claim readiness to implement.

`explore-design` retains a single `workitems/<id>/spec.md` with current Why/What and its ordinary three-section contract. Preserve `design_status: draft` for unapproved text, or `review-pending` for an approved design awaiting independent review. Requirement/contract edits invalidate the corresponding review. Store user choices, superseded alternatives, source snapshots and review history separately; going from review back to exploration rewrites the current end state instead of appending the conversation to the spec.

When prerequisites deliver, verify their actual results and refresh the code baseline relevant to review. Have the user start `review-design` in a fresh context. Do not auto-start that review. The reviewer reads the original requirement, current full spec and relevant source before prior findings. Evidence cards can accelerate navigation but never supply an inherited verdict. Pass requires a current spec and baseline with no blocking findings. Record reviewed identities and evidence; only this independent pass changes the spec to `implementable`.

If review finds contract problems, return to exploration and user alignment. If scope is excessive, split; do not force a complete monolithic design merely to cut it into documents later. A design update, relevant baseline change, or dependency change requires assessing which review conclusions are invalidated before implementation; a stale label alone is never sufficient.

## Exclusive implementation gate

Before the first code edit:

1. Confirm the current spec is approved and independently `implementable`, the reviewed scope still applies, and all prerequisites have delivered.
2. Reconcile pending remote state. If another owner is present, stop writes and report its machine/session. Resume the same development instead of creating a duplicate worktree.
3. Publish an item owner with unique token and `status: developing`, with its actual worktree and branch. Use [persistence](persistence.md); win the Git claim, synchronize every enabled backend, and verify the final remote state before touching code.

Retain this claim through implementation and its final review/handoff. A crashed session does not expire ownership. Another agent may read or review with explicitly read-only scope; only the owner coordinates writes to item records. After an authorized session transfer, continue the same development with the new owner, preserving the previous work and branch.

`implement-design` uses the full design and current handoff. At the end, invoke `review-implementation` through a fresh independent subagent on a stable final diff, with project/item identity and source workdir. Selecting this project workflow authorizes that quality review. Persist only relevant findings/coverage; supported fixes get a focused recheck. Leave code uncommitted for user inspection and submission.

## Delivery and cleanup

After implementation and quality review, checkpoint `awaiting_delivery` and the current handoff. Once all backends verify it and this writer has stopped, release the owner so a later delivery session can claim the item. Preserve its development/worktree identity; an unowned item awaiting delivery is not a new development. The default delivery criterion is actual inclusion in the configured remote trunk; local tests, a local commit or a pushed feature branch do not establish it. Also satisfy any release/deploy criteria in the requirement.

`complete-workitem` records actual delivery and sets `done`; delivered prerequisites can unlock dependents immediately. Cleanup is tracked separately and cannot keep an already delivered dependency blocked. An aggregate completes only when its dependencies deliver and their combined evidence covers its own acceptance.

Use `cleanup-worktree` for eligible merged worktrees, retaining its PR/MR evidence gates and exact deletion approval. Direct-merge evidence can establish project delivery even if it does not satisfy that skill's cleanup gate. Keep cleanup pending and explain the unmet gate; never remove dirty, untracked or unpublished work merely because the item is done.
