---
name: review-implementation
description: Independently review an implementation against its approved contract and final code when the user requests or authorizes that review and no other review skill or workflow has been selected for it. Keep source read-only. The lead covers correctness, quality, security and tests in either review mode.
---

# Review Implementation

Assess complete, correct and maintainable behavior against the confirmed design and original requirements. Code and tests are evidence; an unsafe design does not excuse unsafe implementation.

## Use a single review workflow

If another review skill or workflow has been selected to conduct this implementation review, use that workflow alone. When using `review-implementation`, use it as the sole review skill and workflow for the lead assessment and all delegated aspects. Include this constraint in each reviewer assignment.

## Plan, assess and synthesize

Start [each review from original evidence](references/review-standard.md#start-each-review-from-original-evidence), including after fixes. Keep historical review results out of reviewer context and assess the complete current change against its comparison base.

Read [discussion and authorization](../../references/discussion-and-authorization.md) and the complete [review standard](references/review-standard.md). Gather the shared original context and prepare a neutral review plan covering the relevant dimensions. Apply the [mode contract](references/review-standard.md#resolve-review-mode): honor the explicit mode supplied by the user or caller; ask once on direct invocation with no choice, or return a delegated missing-mode decision to the caller.

In either mode, personally perform the complete planned assessment across all review dimensions. The lead may form and test hypotheses privately at any point. In `multi-agent`, dispatch multiple targeted read-only reviewers with neutral assignments and original evidence so they can reach their own conclusions. Once your assessment and all required assignments finish, validate candidates before reporting your synthesis. In `single-agent`, report your complete assessment directly. Preserve the resolved mode for re-review.

## Select the operating context

- For a managed work item, read [project review](references/project-mode.md). The person or agent requesting a delegated review provides the resolved mode and stable target. The independent reviewer returns the assessment and its actual authorship.
- For a standalone review, use the resolved mode and report in conversation.

In read-only planning, report in conversation and keep all files unchanged, including when delegating.

A qualified reviewer independent of implementation and fixes must assess the actual final contents, including in-scope uncommitted changes. Pass records the independent review outcome for that target. Human acceptance and delivery require their own evidence.
