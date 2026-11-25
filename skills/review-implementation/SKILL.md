---
name: review-implementation
description: Independently review an implementation against its approved contract and final code when the user requests or authorizes that review. Keep source read-only. The lead covers correctness, quality, security and tests in either review mode.
---

# Review Implementation

Assess complete, correct and maintainable behavior against the confirmed design and original requirements. Code and tests are evidence; an unsafe design does not excuse unsafe implementation.

## Prepare, review, then synthesize

Read [discussion and authorization](../../references/discussion-and-authorization.md) and the complete [review standard](references/review-standard.md). First gather the shared original context and prepare a review plan covering the relevant dimensions without forming code findings or a verdict. Before assessment or reviewer dispatch, apply the [mode contract](references/review-standard.md#resolve-review-mode): honor the explicit mode supplied by the user or caller; ask once on direct invocation with no choice, or return a delegated missing-mode decision to the caller.

In either mode, personally perform the complete planned assessment across all review dimensions. `multi-agent` adds targeted reviews: after planning, dispatch multiple read-only reviewers from eligible shared original context before assessing code yourself or sharing reviewer conclusions, then perform your full review while they assess their assigned aspects. Once your assessment and all required assignments finish, validate candidates and synthesize your own conclusions with the reviewers' reports. In `single-agent`, report your complete assessment directly. Preserve the resolved mode for re-review.

## Select the operating context

- For a managed work item, read [project review](references/project-mode.md). The person or agent requesting a delegated review provides the resolved mode and stable target. The independent reviewer returns the assessment and its actual authorship.
- For a standalone review, use the resolved mode and report in conversation.

In read-only planning, report in conversation and keep all files unchanged, including when delegating.

A qualified reviewer independent of implementation and fixes must assess the actual final contents, including in-scope uncommitted changes. On re-review, prefer the original reviewer while independent and apply the [coverage-reuse rules](references/review-standard.md#re-review-only-what-changed-but-invalidate-honestly). Pass records the independent review outcome for that target. Human acceptance and delivery require their own evidence.
