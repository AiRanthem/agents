# Task 6 Report: cpu/memory footprint resolution at admit

## Status
GREEN

## Scope
Implemented Task 6 within the owned write set only:
- `pkg/servers/e2b/create.go`
- `pkg/servers/e2b/create_test.go`
- `pkg/servers/e2b/services_test.go`

## RED evidence
Command:
```bash
GOCACHE=/private/tmp/go-build-cache /Users/sophon/Bin/go test ./pkg/servers/e2b -run 'ResolveCreateFootprint|ResolverFailure|UnlimitedKeyDoesNotCallQuota' -v
```
Result:
- FAIL during build as expected before implementation.
- Missing production behavior/signature showed up as:
  - `controller.resolveCreateFootprint undefined`
  - `too many arguments in call to controller.quotaAdmission`
- One test-fixture type typo (`models.Resources`) was corrected before implementing production code; after that, the missing resolver/signature remained the intended RED signal.

## GREEN evidence
Focused GREEN command:
```bash
GOCACHE=/private/tmp/go-build-cache /Users/sophon/Bin/go test ./pkg/servers/e2b -run 'ResolveCreateFootprint|ResolverFailure|UnlimitedKeyDoesNotCallQuota' -v
```
Result:
- PASS
- Covered the five brief cases plus the pre-Acquire abort path.

Covering GREEN command:
```bash
GOCACHE=/private/tmp/go-build-cache /Users/sophon/Bin/go test ./pkg/servers/e2b/ -run 'Quota|APIKey|Footprint|Create' -v
```
Result:
- PASS
- Re-ran after `gofmt` to ensure final formatted code still passed.

Formatting command:
```bash
/Users/sophon/Bin/go fmt ./pkg/servers/e2b/create.go ./pkg/servers/e2b/create_test.go ./pkg/servers/e2b/services_test.go
```
Result:
- `pkg/servers/e2b/create.go`

## Files changed
- `pkg/servers/e2b/create.go`
- `pkg/servers/e2b/create_test.go`
- `pkg/servers/e2b/services_test.go`

## What changed
- Added `resolveCreateFootprint(ctx, request, user) (map[models.QuotaDimension]int64, error)`.
- Returned `nil, nil` immediately for count-only limited keys, without template/checkpoint reads.
- Resolved claim footprints from cached `SandboxSet` -> `TemplateRef` -> `SandboxTemplate`.
- Resolved clone footprints from cached `Checkpoint` -> same-name `SandboxTemplate`.
- Kept `quotaAdmission` error-free and changed its signature to accept the resolved `footprint`.
- Wired resolved footprint into `quota.AcquireRequest.Footprint`.
- Moved footprint resolution before `quotaAdmission`/`Acquire` in both claim and clone paths.
- Returned the existing template-not-found style `400 Template or Checkpoint not found` on resolution failure, so quota errors are not misreported as `403 quota exceeded`.
- Updated the direct `quotaAdmission` call in `services_test.go`.

## Self-review
- Kept the implementation in `create.go` only; no new cache layer or abstraction was added.
- Resolver uses cache-backed reads (`PickSandboxSet`, `GetCheckpoint`, `GetClient().Get`) rather than API-reader round trips.
- Claim override handling mirrors the existing hot-path behavior by only changing the first container's CPU limit when the current template already carries that limit.
- Footprint conversion uses the same basis as Task 3 by routing through `quota.FootprintOf`.

## Concerns
- Claim-side resource override intentionally mirrors current infra behavior: only the first container's CPU limit is override-effective today. Memory override is not applied because the existing create hot path's `SetResources` logic does not apply it either.
