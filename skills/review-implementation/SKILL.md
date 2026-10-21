---
name: review-implementation
description: Independently assess an implementation against its approved contract and final code evidence in single-agent or multi-agent mode. Use when explicitly requested or delegated by an authorized project workflow. Keep source read-only and cover correctness, quality, security and tests.
---

# Review Implementation

Assess complete, correct and maintainable behavior against the confirmed design and original requirements. Code and tests are evidence; an unsafe design does not excuse unsafe implementation.

## Prepare, review, then synthesize

Read [discussion and authorization](../advance-project/references/discussion-and-authorization.md) and the complete [review standard](references/review-standard.md). First gather the shared original context and prepare a review plan covering the relevant dimensions without forming code findings or a verdict. Then apply the [mode contract](references/review-standard.md#resolve-review-mode): honor the user's choice, default to in-place `single-agent` when unspecified, and use `single-agent` for `advance-project`.

In `multi-agent`, dispatch multiple read-only reviewers by the plan from eligible shared original context before assessing code yourself or sharing reviewer conclusions. After the assigned reviews finish, personally inspect critical changed behavior and surrounding code, assess test oracles and omissions, validate candidates and synthesize the report, even when reviewers return no findings. In `single-agent`, perform the planned assessment in place and report. Preserve the resolved mode for re-review.

## Select the operating context

- **Autonomous stage executor:** Read [stage-executor](../advance-project/references/stage-executor.md) and [project review](references/project-mode.md). Use `single-agent` without a mode question. As the qualified independent reviewer, cover correctness, implementation quality, security, tests and high-risk boundaries yourself; no review descendants are required. Review one stable target and return the actual report and identity. Missing essential capability prevents Pass.
- **Project controller or ordinary project review:** Read [project review](references/project-mode.md). The controller passes the resolved mode and persists evidence; a delegated reviewer performs the assessment. An authorized project workflow is sufficient to invoke this skill.
- **Outside a managed project:** Apply the resolved mode and review standard and report in conversation. Native Plan remains read-only, including delegated work; no source, status, draft or report writes through delegation.

A fresh reviewer independent of implementation and fixes must assess the actual final dirty contents. An implementer or fixer cannot independently accept its own work. Preserve valid unaffected evidence after fixes; repeat only invalidated review. Pass means the stated coverage and mode-specific gates found no blocking introduced defect; it is not human acceptance or delivery.
