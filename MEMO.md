# MEMO

Last updated: 2026-05-06T18:59:44+08:00

## Current Topic

Evaluate whether the resume owner lease-renewal approach in `MEMO`/`pause_resume` fully addresses the 3 reviewer findings, and record remaining risks before deciding next changes.

## Latest Progress

- Problem background: resume requests can run concurrently; old logic only set `AnnotationResumingSince` once, so long waits/retries could be misclassified as stale and allow a second owner; stale/follower owners could also overwrite timeout after losing ownership.
- Plan: keep lease renewal design but verify two critical gaps from review: (1) data safety and synchronization, (2) permanent post-resume errors handling.
- Code edits in tree: lease keeper and owner checks were added in `pkg/sandbox-manager/infra/sandboxcr/sandbox.go`, new completion wait/task error typing in `pkg/cache/tasks.go`, wait constants/errors in `pkg/cache/utils/wait.go`, and resume-state tests in `pkg/sandbox-manager/infra/sandboxcr` (`pause_resume_test.go`, `resume_state_test.go`).
- Review findings: 1) split ownership prevention is implemented (renewing `AnnotationResumingSince` + owner validation before final clear), 2) finish path now checks owner before setting timeout/clearing lock, so stale owner overwrite is blocked. 3) two unresolved issues remain: data race because keeper goroutine mutates `s.Sandbox` concurrently with owner flow (`InplaceRefresh`/runtime refresh), and permanent post-resume parse/config failures still keep retrying indefinitely under non-deadline contexts.
- Next steps: decide whether to block merge until both issues are fixed (recommended); then add tests for bounded/non-retry classification and race-safe keeper behavior.
- Review focus: confirm race-free shared-state model under follower/owner concurrency and ensure `retryPostResumeOperations` stops unboundedly on permanent errors.
