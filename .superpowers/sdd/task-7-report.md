# Task 7 Report: Bidirectional anti-drift reconcile + cache API

## Status
DONE_WITH_CONCERNS

## RED evidence
Command:
```bash
GOCACHE=/private/tmp/go-build-cache /Users/sophon/Bin/go test ./pkg/cache/ ./pkg/servers/e2b/quota/ -run 'AntiDrift|Live|Healthy' -v
```
Observed failure:
- `pkg/cache/cache_health_test.go`: `c.SandboxInformerHealthy undefined`
- `pkg/servers/e2b/quota/antidrift_test.go`: `*fakeLiveSandboxCache does not implement LiveLockstringCache (missing method ListLiveLockstringsByOwner)`
- `pkg/servers/e2b/quota/antidrift_test.go`: `driver.now undefined`
- `pkg/servers/e2b/quota/antidrift_test.go`: `driver.seenLeaked undefined`

Interpretation:
- RED was caused by the required cache API change and the missing real anti-drift reconcile state, which is the intended TDD failure for Task 7.

## GREEN evidence
Command:
```bash
GOCACHE=/private/tmp/go-build-cache /Users/sophon/Bin/go test ./pkg/cache/ ./pkg/servers/e2b/quota/ ./pkg/servers/e2b/ -v
```
Observed result:
- Exit code `0`
- `PASS`
- `ok   github.com/openkruise/agents/pkg/servers/e2b`
- The same run included `pkg/cache` and `pkg/servers/e2b/quota`; command success confirms all three package targets passed.

## Files changed
- `pkg/cache/interface.go`
- `pkg/cache/cache.go`
- `pkg/cache/cache_test.go`
- `pkg/cache/cache_health_test.go`
- `pkg/servers/e2b/quota/antidrift.go`
- `pkg/servers/e2b/quota/antidrift_test.go`
- `pkg/servers/e2b/quota/interface.go`
- `pkg/servers/e2b/core_test.go`

## What changed
- Replaced the quota cache surface with `ListLiveSandboxesByOwner(ctx, owner)` and `SandboxInformerHealthy()`.
- Implemented cache live-sandbox enumeration with informer `IndexUser` and `cache.IsLiveForQuota`, without Sandbox APIReader fallback.
- Replaced the anti-drift stub with:
  - event reconcile: live sandbox -> `Backend.Acquire(Enforce=false)` with predicate-derived footprint/scopes; not-live sandbox -> `Backend.Release`, gated by `SandboxInformerHealthy()`
  - periodic bidirectional diff per limited key from key storage
  - missing live CR charge only after `CreationTimestamp` age exceeds grace
  - immediate correction for present-but-wrong footprint/scope entries
  - leaked entry release only after prior-pass observation, grace expiry, and healthy sandbox informer
  - leaked-memory reset on leader demotion and on stop
- Migrated tests and the `pkg/servers/e2b` cache fake to the new cache API.

## Self-review
- `pkg/cache/cache.go` uses informer-backed `client.List(... MatchingFields{IndexUser: owner})` only; it does not read Sandbox CRs through APIReader.
- `pkg/servers/e2b/quota/antidrift.go` calls `Backend` directly for event and diff reconcile; it does not route through `Manager.AcquireReconcile`.
- Leaked-entry release is cadence-independent with explicit first-seen tracking and grace.
- Reappearing live entries clear leaked memory before release logic runs.
- Event-side release stays conservative behind cache health.

## Concerns
- Current cache internals do not expose exact relist/watch health beyond initial sync, the watch-error hook, and raw sandbox handler sync state.
- `SandboxInformerHealthy()` therefore uses the smallest conservative truthful signal available today: initial cache sync completed, no recent watch error within `watchErrorSettle`, and the registered raw sandbox event handler has synced.
- This satisfies Task 7 without broadening outside the owned files, but it is still conservative rather than a perfect watch/relist health oracle.

## 2026-06-23 Task 7 fix follow-up: consecutive leaked-pass confirmation

### Status
DONE

### RED evidence
Command:
```bash
GOCACHE=/private/tmp/go-build-cache /Users/sophon/Bin/go test ./pkg/servers/e2b/quota/ -run 'AntiDrift|Leaked|KeyStore' -v
```
Observed failure:
- `TestAntiDriftKeyStoreErrorDoesNotCountAsPreviousPass`: leaked entry was incorrectly released as `[lock-1]` after a key-store error cycle.
- `TestAntiDriftListEntriesErrorDoesNotCountAsPreviousPass`: the injected `listEntries` error surfaced, proving the skipped/error cycle path existed and needed leaked-state invalidation before the next healthy pass.

### GREEN evidence
Command:
```bash
GOCACHE=/private/tmp/go-build-cache /Users/sophon/Bin/go test ./pkg/servers/e2b/quota/ -run 'AntiDrift|Leaked|KeyStore' -v
```
Observed result:
- Exit code `0`
- `PASS`
- Both new regressions passed together with the existing second-consecutive-pass release and reappearing-live-entry coverage.

### Files changed
- `pkg/servers/e2b/quota/antidrift.go`
- `pkg/servers/e2b/quota/antidrift_test.go`
- `.superpowers/sdd/task-7-report.md`

### Self-review
- Leaked release now requires the same lockstring to be observed in two consecutive successful diff passes; grace age still uses the original first-seen timestamp.
- A `ListLimited` failure clears leaked confirmation state globally, so a later healthy pass cannot reuse stale history.
- A per-key `ListLiveSandboxesByOwner` or `ListEntries` failure clears leaked confirmation state for that key only, preserving minimal scope while blocking stale maturation.
- Reappearing live entries still clear leaked memory immediately.
- Leader demotion and `Stop()` still clear leaked state.
