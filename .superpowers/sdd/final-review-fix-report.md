# Final review fix report

## Findings fixed

1. Create limiter ordering on quota-protected create paths
- `pkg/sandbox-manager/infra/sandboxcr/claim.go`
  - create-on-no-stock now chooses the attempt lockstring first, runs `Admission.Acquire` before touching the global create limiter, and only consumes limiter capacity when `lockType == create` and the flow is actually proceeding to CR create.
  - if limiter rejection happens after admission and before any CR write, the existing deferred release path now frees the admission.
- `pkg/sandbox-manager/infra/sandboxcr/clone.go`
  - clone now acquires quota admission before `waitCloneCreateLimiter`.
  - limiter failure and other pre-create failures release admission because no CR create was attempted.
  - known rejected create errors still release admission; ambiguous post-create errors still retain the charge for anti-drift, preserving conservative semantics.

2. Anti-drift event reconcile skips unlimited owners
- `pkg/servers/e2b/quota/antidrift.go`
  - added a minimal in-memory limited-owner set on `AntiDriftDriver`.
  - the set is refreshed only after successful `ListLimited()` cycles.
  - event reconcile now returns early for owners not in that set, so unlimited owners do not trigger Redis `Acquire`/`Release` IO.

## RED evidence

1. `GOCACHE=/private/tmp/go-build-cache /Users/sophon/Bin/go test ./pkg/sandbox-manager/infra/sandboxcr -run 'TestTryClaimSandbox_QuotaDeniedCreateOnNoStockDoesNotConsumeCreateLimiter|TestCloneSandbox_AdmissionQuotaExceededIsTerminalBeforeCreate' -v`
- `TestTryClaimSandbox_QuotaDeniedCreateOnNoStockDoesNotConsumeCreateLimiter`: failed because `limiter.Allow()` became false after quota rejection.
- `TestCloneSandbox_AdmissionQuotaExceededIsTerminalBeforeCreate`: still passed, showing the existing test did not yet prove limiter ordering on clone.

2. `GOCACHE=/private/tmp/go-build-cache /Users/sophon/Bin/go test ./pkg/servers/e2b/quota -run 'TestAntiDriftEventReconcile' -v`
- `TestAntiDriftEventReconcile/owner_not_in_limited_set_skipped`: failed because backend `Acquire` was still called for `lock-unlimited`.

## GREEN evidence

1. `GOCACHE=/private/tmp/go-build-cache /Users/sophon/Bin/go test ./pkg/sandbox-manager/infra/sandboxcr -run 'TestTryClaimSandbox_QuotaDeniedCreateOnNoStockDoesNotConsumeCreateLimiter|TestCloneSandbox_AdmissionQuotaExceededIsTerminalBeforeCreate' -v`
- both focused sandboxcr regressions passed.

2. `GOCACHE=/private/tmp/go-build-cache /Users/sophon/Bin/go test ./pkg/servers/e2b/quota -run 'TestAntiDriftEventReconcile' -v`
- focused anti-drift event guard regression passed.

3. Final covering
- `GOCACHE=/private/tmp/go-build-cache /Users/sophon/Bin/go test ./pkg/sandbox-manager/infra/sandboxcr ./pkg/servers/e2b/quota -run 'Quota|Limiter|AntiDrift|Event|Clone|Claim' -v`
- passed for both packages.

## Files changed

- `pkg/sandbox-manager/infra/sandboxcr/claim.go`
- `pkg/sandbox-manager/infra/sandboxcr/claim_test.go`
- `pkg/sandbox-manager/infra/sandboxcr/clone.go`
- `pkg/sandbox-manager/infra/sandboxcr/clone_test.go`
- `pkg/servers/e2b/quota/antidrift.go`
- `pkg/servers/e2b/quota/antidrift_test.go`

## Self-review

- Scope stayed within the two Important findings only.
- No public quota API, quota model, or Redis Lua changed.
- Claim and clone both keep the same attempt lockstring from acquire through CR stamping and later release.
- Release semantics remain conservative: release only on no-create-attempt / known rejected write / successful cleanup deletion, not on ambiguous create failures.
- Anti-drift periodic reconcile remains the source of truth for limited subjects; the event guard only suppresses unlimited-owner Redis IO.

## Concerns

- None beyond existing branch behavior. The limited-owner event guard is intentionally memory-backed and only refreshes after successful `ListLimited()` cycles; that matches the requested smallest safe fix.
