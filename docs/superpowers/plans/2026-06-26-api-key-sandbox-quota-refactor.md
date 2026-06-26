# API Key Sandbox Quota Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move API-key quota domain types and dynamic Redis enforcement out of the E2B server layer into sandbox-manager, leaving E2B responsible only for API-key storage and public HTTP wire shape.

**Architecture:** Keep the existing Redis live-set/upsert implementation, but relocate it under `pkg/sandbox-manager/quota` and make sandbox-manager construct `infra.SandboxAdmission` internally from `(User, QuotaSpec)`. E2B passes static quota data parsed from the API key and no longer calls dynamic Redis quota APIs or builds admission hooks. Cache and quota share lifecycle predicates through a leaf package so neither imports the other.

**Tech Stack:** Go, controller-runtime cache, Kubernetes CRDs, `github.com/redis/go-redis/v9`, client-go leader election, table-driven unit tests.

## Plan Execution Constraints

Each task must leave the tree **compilable** and its focused `go test` scope **passing** before commit. In particular:

- **Task 2** moves the quota model types out of `pkg/servers/e2b/models`, but `pkg/servers/e2b/quota/*.go` and `pkg/servers/e2b/create.go` keep referencing `models.Quota*` until Tasks 3–4 migrate them. To keep the tree compilable after Task 2, leave **transitional type/const aliases** in `pkg/servers/e2b/models/quota.go` (Task 2 Step 4) and remove them only in Task 9 once no `models.Quota*` reference remains. The per-task focused `go test` scopes do **not** compile the whole `pkg/servers/e2b` subtree, so a task that removes a symbol from a shared package must add an explicit compile gate (`go build ./pkg/servers/e2b/...`), otherwise the break is masked.
- **Task 3** must land `SubjectLister` decoupling in the **same** task as the dynamic-quota package move so `pkg/sandbox-manager/quota` never imports `pkg/servers/e2b/...` (avoids the import cycle created when Task 2 makes `e2b/models` import `sandbox-manager/quota`).
- **Task 4** introduces `quotaEnforcer` on `SandboxManager` before admission tests assign a fake.
- **Task 6** (primary-aware anti-drift) is a **behavior change**; keep it as its own commit/PR slice after the structural refactor (Tasks 1–5).

## Global Constraints

- Final answers to the user are in Simplified Chinese unless explicitly requested otherwise.
- Every new `.go` file starts with the Apache 2.0 license header.
- Use `gofmt` and `goimports` on changed Go files.
- Do not edit generated directories: `client/`, `proto/`, `config/crd/`.
- Go tests are only under `pkg/`; do not run E2E tests under `test/`.
- Table-driven tests use descriptive `name` fields and `expectError string` for expected errors.
- `pkg/features` must not be imported by `pkg/sandbox-manager` or `pkg/servers`.
- New shared helpers must live in purpose-specific packages, not `pkg/utils`.
- The public quota wire uses full dimension keys only: `sandbox.count`, `limits.cpu`, `limits.memory`.
- sandbox-manager must not import or know E2B API-key storage types.
- E2B must not construct `infra.SandboxAdmission` or call dynamic Redis quota APIs.
- Always commit with sign-off: `git commit -s`.

---

## File Structure

- Create `pkg/sandbox/lifecycle/predicates.go`: neutral Sandbox lifecycle predicate shared by cache and quota.
- Create `pkg/sandbox/lifecycle/predicates_test.go`: table-driven lifecycle predicate tests.
- Create `pkg/sandbox-manager/quota/*.go`: move current `pkg/servers/e2b/quota` implementation here and add quota model/validation types currently in `pkg/servers/e2b/models/quota.go`.
- Modify `pkg/servers/e2b/models/quota.go`: keep only public nested quota wire parsing/formatting and stored internal marshal/decode wrappers that call sandbox-manager quota normalization.
- Modify `pkg/servers/e2b/models/api_key.go`: change `QuotaSpec` fields to `*quota.QuotaSpec`.
- Modify `pkg/servers/e2b/keys/*.go`: store static `*quota.QuotaSpec`; implement `quota.SubjectLister` adapter without exposing key storage to sandbox-manager.
- Modify `pkg/cache/cache.go` and `pkg/cache/interface.go`: use shared lifecycle predicate; keep `ListLiveSandboxesByOwner` cache-local.
- Modify `pkg/sandbox-manager/api.go`: add manager-level wrapper options, build quota admission internally, and release quota after accepted delete.
- Create `pkg/servers/e2b/keys/quota_subjects.go`: E2B `SubjectLister` adapter (Task 3).
- Modify `pkg/sandbox-manager/core.go`: `quotaEnforcer` field (Task 4); anti-drift/Redis runtime fields (Task 5).
- Modify `pkg/sandbox-manager/leader.go`: add a blocking primary wait/notification surface used by anti-drift.
- Modify `pkg/sandbox-manager/config/manager.go`: add quota config primitives to sandbox-manager options.
- Modify `pkg/servers/e2b/core.go`, `pkg/servers/e2b/create.go`, `pkg/servers/e2b/services.go`, `cmd/sandbox-manager/main.go`: remove E2B dynamic quota ownership and pass static quota into sandbox-manager calls.
- Modify affected tests under `pkg/cache`, `pkg/sandbox-manager`, `pkg/sandbox-manager/quota`, `pkg/servers/e2b`, and `pkg/servers/e2b/keys`.

---

### Task 1: Shared Sandbox Lifecycle Predicate

**Files:**
- Create: `pkg/sandbox/lifecycle/predicates.go`
- Create: `pkg/sandbox/lifecycle/predicates_test.go`
- Modify: `pkg/cache/cache.go`
- Modify: `pkg/servers/e2b/quota/predicates.go`
- Test: `pkg/sandbox/lifecycle/predicates_test.go`
- Test: `pkg/cache/cache_test.go`
- Test: `pkg/servers/e2b/quota/predicates_test.go`

**Interfaces:**
- Produces: `lifecycle.IsNotTerminating(sbx *agentsv1alpha1.Sandbox) bool`
- Consumes: only `api/v1alpha1`; no cache, quota, or E2B imports.

- [ ] **Step 1: Write shared predicate tests**

Add table-driven tests:

```go
func TestIsNotTerminating(t *testing.T) {
	now := metav1.Now()
	tests := []struct {
		name string
		sbx  *agentsv1alpha1.Sandbox
		want bool
	}{
		{name: "nil sandbox is not active", sbx: nil, want: false},
		{name: "running sandbox is active", sbx: &agentsv1alpha1.Sandbox{Status: agentsv1alpha1.SandboxStatus{Phase: agentsv1alpha1.SandboxRunning}}, want: true},
		{name: "failed sandbox still counts until deletion", sbx: &agentsv1alpha1.Sandbox{Status: agentsv1alpha1.SandboxStatus{Phase: agentsv1alpha1.SandboxFailed}}, want: true},
		{name: "deletion timestamp is not active", sbx: &agentsv1alpha1.Sandbox{ObjectMeta: metav1.ObjectMeta{DeletionTimestamp: &now}}, want: false},
		{name: "terminating phase is not active", sbx: &agentsv1alpha1.Sandbox{Status: agentsv1alpha1.SandboxStatus{Phase: agentsv1alpha1.SandboxTerminating}}, want: false},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assert.Equal(t, tt.want, IsNotTerminating(tt.sbx))
		})
	}
}
```

- [ ] **Step 2: Run the focused failing test**

Run: `go test ./pkg/sandbox/lifecycle`

Expected before implementation: package missing or `IsNotTerminating` undefined.

- [ ] **Step 3: Implement the leaf package**

Create:

```go
package lifecycle

import agentsv1alpha1 "github.com/openkruise/agents/api/v1alpha1"

func IsNotTerminating(sbx *agentsv1alpha1.Sandbox) bool {
	if sbx == nil {
		return false
	}
	return sbx.GetDeletionTimestamp() == nil && sbx.Status.Phase != agentsv1alpha1.SandboxTerminating
}
```

- [ ] **Step 4: Replace cache inline predicate**

In `pkg/cache/cache.go`, delete the exported `cache.IsLiveForQuota` function and make `ListLiveSandboxesByOwner`
call the shared predicate directly:

```go
if !lifecycle.IsNotTerminating(sbx) {
	continue
}
```

Move the existing `cache.TestIsLiveForQuota` cases into `pkg/sandbox/lifecycle/predicates_test.go` as
`TestIsNotTerminating`, then delete the cache test that references `cache.IsLiveForQuota`.

Do not change `CountActiveSandboxes`; it deliberately uses different "not dead" semantics.

- [ ] **Step 5: Replace quota predicate wrappers and drop cache import**

In the current quota predicate file (`pkg/servers/e2b/quota/predicates.go` until Task 3 moves it), update **both** wrappers and remove the `pkg/cache` import:

```go
import (
	agentsv1alpha1 "github.com/openkruise/agents/api/v1alpha1"
	"github.com/openkruise/agents/pkg/sandbox/lifecycle"
)

func IsLiveForQuota(sbx *agentsv1alpha1.Sandbox) bool {
	return lifecycle.IsNotTerminating(sbx)
}

// InRunningScope uses Spec.Paused (pause request), matching current production behavior.
// Design §5 pseudocode uses Status.Phase; §15 leaves the exact transition-phase boundary to
// implementation. Do not change this predicate during the refactor.
func InRunningScope(sbx *agentsv1alpha1.Sandbox) bool {
	return lifecycle.IsNotTerminating(sbx) && !sbx.Spec.Paused
}
```

`ConditionalScopesOf` and `FootprintOf` stay in this file; only lifecycle imports change.

- [ ] **Step 6: Run focused tests**

Run:

```bash
go test ./pkg/sandbox/lifecycle ./pkg/cache ./pkg/servers/e2b/quota
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add pkg/sandbox/lifecycle pkg/cache pkg/servers/e2b/quota
git commit -s -m "refactor: share sandbox lifecycle predicate"
```

---

### Task 2: Move Static Quota Model Into Sandbox-Manager

**Files:**
- Create: `pkg/sandbox-manager/quota/model.go`
- Create: `pkg/sandbox-manager/quota/model_test.go`
- Modify: `pkg/servers/e2b/models/quota.go`
- Modify: `pkg/servers/e2b/models/api_key.go`
- Modify: `pkg/servers/e2b/keys/interface.go`
- Modify: `pkg/servers/e2b/keys/secret.go`
- Modify: `pkg/servers/e2b/keys/mysql.go`
- Test: `pkg/sandbox-manager/quota/model_test.go`
- Test: `pkg/servers/e2b/models/quota_test.go`

**Interfaces:**
- Produces: `quota.QuotaSpec`, `quota.QuotaLimit`, `quota.QuotaDimension`, `quota.QuotaScope`
- Produces: `quota.NormalizeQuotaSpec`, `quota.DecodeQuotaSpec`, `quota.MarshalQuotaSpec`
- E2B consumes these types for static key storage only.

- [ ] **Step 1: Write model tests in sandbox-manager quota**

Move validation cases from `pkg/servers/e2b/models/quota_test.go` into `pkg/sandbox-manager/quota/model_test.go` and add full-key validation:

```go
func TestNormalizeQuotaSpec(t *testing.T) {
	tests := []struct {
		name        string
		in          *QuotaSpec
		want        *QuotaSpec
		expectError string
	}{
		{name: "nil is unlimited", in: nil, want: nil},
		{name: "empty is unlimited", in: &QuotaSpec{}, want: nil},
		{name: "zero limit is valid", in: &QuotaSpec{Limits: []QuotaLimit{{Dimension: DimSandboxCount, Scope: ScopeRunning, Limit: 0}}}, want: &QuotaSpec{Limits: []QuotaLimit{{Dimension: DimSandboxCount, Scope: ScopeRunning, Limit: 0}}}},
		{name: "negative limit rejected", in: &QuotaSpec{Limits: []QuotaLimit{{Dimension: DimSandboxCount, Scope: ScopeRunning, Limit: -1}}}, expectError: "quota limit must be non-negative"},
		{name: "duplicate pair rejected", in: &QuotaSpec{Limits: []QuotaLimit{{Dimension: DimSandboxCount, Scope: ScopeRunning, Limit: 1}, {Dimension: DimSandboxCount, Scope: ScopeRunning, Limit: 2}}}, expectError: "duplicate quota limit"},
		{name: "unsupported dimension rejected", in: &QuotaSpec{Limits: []QuotaLimit{{Dimension: QuotaDimension("cpu"), Scope: ScopeRunning, Limit: 1}}}, expectError: "unsupported quota dimension"},
		{name: "unsupported scope rejected", in: &QuotaSpec{Limits: []QuotaLimit{{Dimension: DimSandboxCount, Scope: QuotaScope("template:python"), Limit: 1}}}, expectError: "unsupported quota scope"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, err := NormalizeQuotaSpec(tt.in)
			if tt.expectError != "" {
				require.Error(t, err)
				assert.Contains(t, err.Error(), tt.expectError)
				return
			}
			require.NoError(t, err)
			assert.Equal(t, tt.want, got)
		})
	}
}
```

- [ ] **Step 2: Run the focused failing test**

Run: `go test ./pkg/sandbox-manager/quota -run 'TestNormalizeQuotaSpec|TestDecodeQuotaSpec|TestMarshalQuotaSpec'`

Expected before implementation: package or symbols missing.

- [ ] **Step 3: Move model code**

Move the following from `pkg/servers/e2b/models/quota.go` into `pkg/sandbox-manager/quota/model.go`:

```go
type QuotaDimension string
const (
	DimSandboxCount QuotaDimension = "sandbox.count"
	DimLimitsCPU    QuotaDimension = "limits.cpu"
	DimLimitsMemory QuotaDimension = "limits.memory"
)

type QuotaScope string
const (
	ScopeAll     QuotaScope = "all"
	ScopeRunning QuotaScope = "running"
)

var ErrQuotaLimitNegative = errors.New("quota limit must be non-negative")

type QuotaLimit struct {
	Dimension QuotaDimension `json:"dimension"`
	Scope     QuotaScope     `json:"scope"`
	Limit     int64          `json:"limit"`
}

type QuotaSpec struct {
	Limits []QuotaLimit `json:"limits,omitempty"`
}
```

Move `IsLimited`, `LimitedPairs`, `DeepCopy`, `NormalizeQuotaSpec`, `DecodeQuotaSpec`, `MarshalQuotaSpec`, and validation helpers with them.

- [ ] **Step 4: Keep E2B wire functions only**

In `pkg/servers/e2b/models/quota.go`, keep only:

```go
func QuotaSpecFromWire(raw json.RawMessage) (*quota.QuotaSpec, error)
func WireFromQuotaSpec(spec *quota.QuotaSpec) json.RawMessage
func DecodeQuotaSpec(raw []byte) (*quota.QuotaSpec, error) { return quota.DecodeQuotaSpec(raw) }
func MarshalQuotaSpec(spec *quota.QuotaSpec) ([]byte, error) { return quota.MarshalQuotaSpec(spec) }
```

Use full wire keys in deterministic input/output order:

```go
var quotaWireDimensions = []quota.QuotaDimension{
	quota.DimSandboxCount,
	quota.DimLimitsCPU,
	quota.DimLimitsMemory,
}
```

**Compile bridge (required).** `pkg/servers/e2b/quota/*.go` and `pkg/servers/e2b/create.go` still reference
`models.Quota*` until Tasks 3–4 migrate them, so dropping the types from `models` here breaks the build the moment
Task 2 commits. In addition to the four functions above, add **transitional re-export aliases** for every moved
symbol, and delete this block in Task 9 once
`rg 'models\.(QuotaSpec|QuotaLimit|QuotaDimension|QuotaScope|Dim[A-Za-z]+|Scope[A-Za-z]+|NormalizeQuotaSpec|ErrQuotaLimitNegative)' pkg/servers/e2b`
returns nothing:

```go
// Transitional re-exports so existing models.Quota* references keep compiling during
// the quota relocation. Removed in Task 9 after every caller migrates to quota.*.
type (
	QuotaSpec      = quota.QuotaSpec
	QuotaLimit     = quota.QuotaLimit
	QuotaDimension = quota.QuotaDimension
	QuotaScope     = quota.QuotaScope
)

const (
	DimSandboxCount = quota.DimSandboxCount
	DimLimitsCPU    = quota.DimLimitsCPU
	DimLimitsMemory = quota.DimLimitsMemory
	ScopeAll        = quota.ScopeAll
	ScopeRunning    = quota.ScopeRunning
)

var (
	ErrQuotaLimitNegative = quota.ErrQuotaLimitNegative
	NormalizeQuotaSpec    = quota.NormalizeQuotaSpec
)
```

- [ ] **Step 5: Parse and emit only full wire keys**

Replace the current short-key mapper with full-key validation:

```go
func quotaDimensionFromWireKey(key string) (quota.QuotaDimension, error) {
	switch quota.QuotaDimension(key) {
	case quota.DimSandboxCount, quota.DimLimitsCPU, quota.DimLimitsMemory:
		return quota.QuotaDimension(key), nil
	case "count", "cpu", "memory":
		return "", fmt.Errorf("unsupported quota dimension %q; use full key", key)
	default:
		return "", fmt.Errorf("unsupported quota dimension %q", key)
	}
}
```

Then rewrite the `QuotaSpecFromWire` construction loop so it no longer scans `[]string{"count", "cpu", "memory"}`.
It must look up the full dimension strings:

```go
spec := &quota.QuotaSpec{}
for _, scope := range []quota.QuotaScope{quota.ScopeRunning, quota.ScopeAll} {
	dims, ok := wire[string(scope)]
	if !ok {
		continue
	}
	for _, dimension := range quotaWireDimensions {
		limit, exists := dims[string(dimension)]
		if !exists {
			continue
		}
		spec.Limits = append(spec.Limits, quota.QuotaLimit{
			Dimension: dimension,
			Scope:     scope,
			Limit:     limit,
		})
	}
}
return quota.NormalizeQuotaSpec(spec)
```

Remove `quotaDimensionWireKey`, or reduce it to `return string(dimension)`. `WireFromQuotaSpec` must write full
keys such as `limits.cpu`; it must never emit `cpu`, `memory`, or `count`.

- [ ] **Step 6: Update E2B static types**

Change:

```go
QuotaSpec *QuotaSpec `json:"-"`
Quota    *models.QuotaSpec
```

to:

```go
QuotaSpec *quota.QuotaSpec `json:"-"`
Quota     *quota.QuotaSpec
```

in API-key models and key storage options, importing `github.com/openkruise/agents/pkg/sandbox-manager/quota`.

- [ ] **Step 7: Update tests and branch fixtures using short keys**

Replace public wire expectations:

```json
{"running":{"count":2}}
```

with:

```json
{"running":{"sandbox.count":2}}
```

Replace cpu/memory expectations:

```json
{"running":{"cpu":8000,"memory":16384},"all":{"count":50}}
```

with:

```json
{"running":{"limits.cpu":8000,"limits.memory":16384},"all":{"sandbox.count":50}}
```

Add a positive E2B wire test proving `{"running":{"sandbox.count":2}}` returns one limited pair, not unlimited.
Add negative cases for short `count`, `cpu`, and `memory`. Add a `WireFromQuotaSpec` case proving the response
uses full keys.

- [ ] **Step 8: Run focused tests**

Run:

```bash
go test ./pkg/sandbox-manager/quota ./pkg/servers/e2b/models ./pkg/servers/e2b/keys
```

Expected: PASS.

- [ ] **Step 8a: Compile-gate the whole E2B subtree**

The focused `go test` scope above does **not** compile `pkg/servers/e2b` (root) or `pkg/servers/e2b/quota`, which
still reference the moved symbols through the Step 4 bridge. Add an explicit compile check so a missed reference
cannot be masked by the narrow test scope:

```bash
go build ./pkg/servers/e2b/... ./cmd/sandbox-manager
```

Expected: PASS (build only; `_test.go` files are not compiled here, so the bridge must cover production references).

- [ ] **Step 9: Commit**

```bash
git add pkg/sandbox-manager/quota pkg/servers/e2b/models pkg/servers/e2b/keys
git commit -s -m "refactor: move quota model to sandbox manager"
```

---

### Task 3: Move Dynamic Quota + SubjectLister Decoupling (single compile-safe slice)

**Files:**
- Move: `pkg/servers/e2b/quota/{antidrift,breaker,errors,interface,manager,metrics,noop,predicates,redis}.go`
- Move tests: `pkg/servers/e2b/quota/*_test.go`
- Create: `pkg/servers/e2b/keys/quota_subjects.go`
- Create: `pkg/servers/e2b/keys/quota_subjects_test.go`
- Modify imports across `pkg/servers/e2b`, `cmd/sandbox-manager`, and tests
- Delete: old `pkg/servers/e2b/quota` package after imports are gone
- Test: `pkg/sandbox-manager/quota`, `pkg/servers/e2b/keys`

**Interfaces:**
- Produces in `pkg/sandbox-manager/quota`:
  - `type Subject struct { User string; Quota *QuotaSpec }`
  - `type SubjectLister interface { ListLimited(ctx); Load(ctx, user) }`
  - `type Manager struct`, `NewManager`, `Acquire`, `Release`, `Cleanup`
  - `FootprintFromResource(resource infra.SandboxResource) map[QuotaDimension]int64`
- E2B produces `keys.NewQuotaSubjectLister(KeyStorage) quota.SubjectLister`.
- **`pkg/sandbox-manager/quota` must not import `pkg/servers/e2b` or `pkg/servers/e2b/models`** after this task.

This task intentionally adds `pkg/sandbox-manager/quota -> pkg/sandbox-manager/infra` for
`SandboxResource` and `CalculateResourceFromContainers`. Keep `pkg/sandbox-manager/infra` independent of quota.

- [ ] **Step 1: Add `Subject` / `SubjectLister` to quota interface before the move**

In `pkg/servers/e2b/quota/interface.go` (still at the old path), add and wire `SubjectLister` **before** `git mv`,
replacing `LimitedKeyStore`. `Subject.Quota` uses `*smquota.QuotaSpec` via import alias
`smquota "github.com/openkruise/agents/pkg/sandbox-manager/quota"` (model types only — no import cycle):

```go
type Subject struct {
	User  string
	Quota *smquota.QuotaSpec
}

type SubjectLister interface {
	ListLimited(ctx context.Context) ([]Subject, error)
	Load(ctx context.Context, user string) (Subject, bool)
}
```

Update `AntiDriftDriver` to hold `subjects SubjectLister` instead of `keys LimitedKeyStore`. Replace
`reconcileLimitedKey(ctx, key *models.CreatedTeamAPIKey, ...)` with `reconcileLimitedSubject(ctx, subject Subject, ...)`.
Replace `limitedOwnerIDs(limitedKeys []*models.CreatedTeamAPIKey)` with `limitedOwnerIDs(subjects []Subject)`.
Replace `ensureKnownLimited` / event handler lookups to use `SubjectLister.Load`. **Delete `LimitedKeyStore` and all
`models.CreatedTeamAPIKey` references from the quota package** in this step so the move does not carry E2B coupling.
Rewrite `antidrift_test.go` fakes (`fakeKeyStore` → `fakeSubjectLister` returning `[]Subject`).

- [ ] **Step 2: Move package files**

```bash
mkdir -p pkg/sandbox-manager/quota
git mv pkg/servers/e2b/quota/*.go pkg/sandbox-manager/quota/
```

- [ ] **Step 3: Rename quota types and `APIKeyID` → `User` (full checklist)**

Replace all `models.QuotaSpec` / `models.QuotaDimension` / `models.QuotaScope` with local package types.

Manager-facing request types:

```go
type AcquireRequest struct {
	User       string
	LockString string
	Quota      *QuotaSpec
	Footprint  map[QuotaDimension]int64
	Scopes     []QuotaScope
}

type ReleaseRequest struct {
	User       string
	LockString string
}
```

Backend / Redis rename checklist (every occurrence in `pkg/sandbox-manager/quota`):

| Old | New |
|-----|-----|
| `AcquireParams.APIKeyID` | `AcquireParams.User` |
| `Backend.Release(ctx, apiKeyID, lockString)` | `Backend.Release(ctx, user, lockString)` |
| `Backend.ListEntries(ctx, apiKeyID)` | `Backend.ListEntries(ctx, user)` |
| `Backend.Cleanup(ctx, apiKeyID)` | `Backend.Cleanup(ctx, user)` |
| `Manager.Cleanup(ctx, apiKeyID)` | `Manager.Cleanup(ctx, user)` |
| `redisKeys` / `liveKey` / `sumKey` parameter `apiKeyID` | `user` |
| `Manager.Acquire` missing-identity log field `apiKeyID` | `user` |
| Anti-drift locals `apiKeyID` | `user` (lockstring keys unchanged) |

Update all `*_test.go` fakes and table cases in the same pass. Do **not** add `Enforce` to `AcquireRequest`.

- [ ] **Step 4: Preserve fail-open manager behavior**

Keep the current no-op fast path and backend error behavior:

```go
if req.Quota == nil || !req.Quota.IsLimited() {
	acquireTotal.WithLabelValues("unlimited").Inc()
	return nil
}
```

`Manager.Acquire` must continue calling the backend with `Enforce: true`; anti-drift calls the backend directly with
`AcquireParams{Enforce: false}`.

- [ ] **Step 5: Add resource footprint mapper**

```go
func FootprintFromResource(resource infra.SandboxResource) map[QuotaDimension]int64 {
	return map[QuotaDimension]int64{
		DimLimitsCPU:    resource.Limits.CPUMilli,
		DimLimitsMemory: resource.Limits.MemoryMB,
	}
}
```

- [ ] **Step 6: Make `FootprintOf` use the shared infra extraction path**

```go
func FootprintOf(sbx *agentsv1alpha1.Sandbox) map[QuotaDimension]int64 {
	if sbx == nil || sbx.Spec.Template == nil {
		return FootprintFromResource(infra.SandboxResource{})
	}
	return FootprintFromResource(infra.CalculateResourceFromContainers(sbx.Spec.Template.Spec.Containers))
}
```

- [ ] **Step 7: Implement E2B `SubjectLister` adapter**

Create `pkg/servers/e2b/keys/quota_subjects.go`:

```go
type quotaSubjectLister struct {
	storage KeyStorage
}

func NewQuotaSubjectLister(storage KeyStorage) quota.SubjectLister {
	return quotaSubjectLister{storage: storage}
}

func (l quotaSubjectLister) ListLimited(ctx context.Context) ([]quota.Subject, error) {
	keys, err := l.storage.ListLimited(ctx)
	if err != nil {
		return nil, err
	}
	out := make([]quota.Subject, 0, len(keys))
	for _, key := range keys {
		if key == nil || key.QuotaSpec == nil || !key.QuotaSpec.IsLimited() {
			continue
		}
		out = append(out, quota.Subject{User: key.ID.String(), Quota: key.QuotaSpec.DeepCopy()})
	}
	return out, nil
}

func (l quotaSubjectLister) Load(ctx context.Context, user string) (quota.Subject, bool) {
	key, ok := l.storage.LoadByID(ctx, user)
	if !ok || key == nil || key.QuotaSpec == nil || !key.QuotaSpec.IsLimited() {
		return quota.Subject{}, false
	}
	return quota.Subject{User: key.ID.String(), Quota: key.QuotaSpec.DeepCopy()}, true
}
```

Add `quota_subjects_test.go` with a fake `KeyStorage` (table-driven).

- [ ] **Step 8: Update E2B callers and import paths**

Replace `"github.com/openkruise/agents/pkg/servers/e2b/quota"` with
`"github.com/openkruise/agents/pkg/sandbox-manager/quota"` in:

- `pkg/servers/e2b/create.go`, `services.go`, `core.go`, `api_key.go`, and their tests
- `cmd/sandbox-manager/main.go` (still uses `quota.Config` until Task 5)

Update acquire/release call sites to `User` field names:

```go
quota.AcquireRequest{
	User:       apiKeyID,
	LockString: lockString,
	Quota:      quotaSpec,
	Footprint:  quota.FootprintFromResource(resource),
	Scopes:     []quota.QuotaScope{quota.ScopeRunning},
}
```

In `core.go` `initQuota`, pass `keys.NewQuotaSubjectLister(sc.keys)` as the `SubjectLister` argument to
`NewAntiDriftDriver` (replacing the old `sc.keys` `LimitedKeyStore`).

Move `TestQuotaFootprintFromResourceUsesLimits` and
`TestQuotaFootprintFromCalculatedResourceRoundsLimitMemoryUp` from `pkg/servers/e2b/create_test.go` to
`pkg/sandbox-manager/quota`.

- [ ] **Step 9: Run focused tests**

```bash
go test ./pkg/sandbox-manager/quota ./pkg/servers/e2b/keys ./pkg/servers/e2b
```

Expected: PASS.

- [ ] **Step 10: Verify dependency and rename boundaries**

```bash
rg 'pkg/servers/e2b' pkg/sandbox-manager/quota
rg 'pkg/servers/e2b/quota|models\.Quota(Spec|Limit|Dimension|Scope)|CreatedTeamAPIKey|LimitedKeyStore|APIKeyID' pkg/sandbox-manager/quota pkg cmd
```

Expected: no `pkg/servers/e2b` imports under `pkg/sandbox-manager/quota`; no `APIKeyID` / `LimitedKeyStore` /
`CreatedTeamAPIKey` left in quota; no old `pkg/servers/e2b/quota` import paths.

- [ ] **Step 11: Commit**

```bash
git add pkg/sandbox-manager/quota pkg/servers/e2b/keys pkg/servers/e2b cmd/sandbox-manager
git commit -s -m "refactor: move dynamic quota and decouple subject lister"
```

---

### Task 4: Sandbox-Manager Builds Quota Admission

**Files:**
- Modify: `pkg/sandbox-manager/api.go`
- Modify: `pkg/sandbox-manager/core.go`
- Modify: `pkg/sandbox-manager/api_test.go`
- Modify: `pkg/servers/e2b/create.go`
- Modify: `pkg/servers/e2b/create_test.go`
- Modify: `pkg/servers/e2b/services.go`
- Modify: `pkg/servers/e2b/services_test.go`

**Interfaces:**
- Produces:

```go
// quotaEnforcer is the minimal surface sandbox-manager needs for admission and delete release.
// Use an interface so api_test can inject fakes before InitQuota wires a real *quota.Manager.
type quotaEnforcer interface {
	Acquire(ctx context.Context, req quota.AcquireRequest) error
	Release(ctx context.Context, req quota.ReleaseRequest) error
}

type ClaimSandboxOptions struct {
	Infra infra.ClaimSandboxOptions
	Quota *quota.QuotaSpec
}

type CloneSandboxOptions struct {
	Infra infra.CloneSandboxOptions
	Quota *quota.QuotaSpec
}

type DeleteSandboxOptions struct {
	Sandbox infra.Sandbox
	User    string
	Quota   *quota.QuotaSpec
}
```

- `SandboxManager.ClaimSandbox(ctx, opts ClaimSandboxOptions)`
- `SandboxManager.CloneSandbox(ctx, opts CloneSandboxOptions)`
- `SandboxManager.DeleteSandbox(ctx, opts DeleteSandboxOptions)`

- [ ] **Step 1: Add `quotaEnforcer` field to `SandboxManager`**

In `pkg/sandbox-manager/core.go`, add a private interface and field (no anti-drift / Redis fields yet — those land in Task 5):

```go
type quotaEnforcer interface {
	Acquire(ctx context.Context, req quota.AcquireRequest) error
	Release(ctx context.Context, req quota.ReleaseRequest) error
}

type SandboxManager struct {
	// ...existing fields...
	quota quotaEnforcer // nil until InitQuota (Task 5) or test injection
}
```

- [ ] **Step 2: Write manager admission tests**

Add table-driven tests that verify sandbox-manager overwrites any caller-provided `Infra.Admission`:

```go
type fakeManagerQuota struct {
	lastAcquire quota.AcquireRequest
}

func (f *fakeManagerQuota) Acquire(_ context.Context, req quota.AcquireRequest) error {
	f.lastAcquire = req
	return nil
}

func (f *fakeManagerQuota) Release(context.Context, quota.ReleaseRequest) error { return nil }

func TestSandboxManagerBuildsQuotaAdmission(t *testing.T) {
	quotaMgr := &fakeManagerQuota{}
	manager := newTestSandboxManager(t)
	manager.quota = quotaMgr

	opts := sandbox_manager.ClaimSandboxOptions{
		Infra: infra.ClaimSandboxOptions{
			Namespace: "default",
			User:      "user-1",
			Template:  "template-1",
			Admission: &infra.SandboxAdmission{Acquire: func(context.Context, string, infra.SandboxResource) error {
				t.Fatal("caller admission must be overwritten")
				return nil
			}},
		},
		Quota: &quota.QuotaSpec{Limits: []quota.QuotaLimit{{Dimension: quota.DimSandboxCount, Scope: quota.ScopeAll, Limit: 1}}},
	}

	_, _ = manager.ClaimSandbox(t.Context(), opts)
	assert.Equal(t, "user-1", quotaMgr.lastAcquire.User)
}
```

- [ ] **Step 3: Add wrapper option types**

Add the three manager-level option structs near the manager API methods. Keep the embedded infra option names explicit as `Infra`.

- [ ] **Step 4: Add internal admission builder**

In sandbox-manager:

```go
func (m *SandboxManager) quotaAdmission(user string, spec *quota.QuotaSpec) *infra.SandboxAdmission {
	if m == nil || m.quota == nil || spec == nil || !spec.IsLimited() {
		return nil
	}
	quotaSpec := spec.DeepCopy()
	return &infra.SandboxAdmission{
		Acquire: func(ctx context.Context, lockString string, resource infra.SandboxResource) error {
			err := m.quota.Acquire(ctx, quota.AcquireRequest{
				User:       user,
				LockString: lockString,
				Quota:      quotaSpec,
				Footprint:  quota.FootprintFromResource(resource),
				Scopes:     []quota.QuotaScope{quota.ScopeRunning},
			})
			if errors.Is(err, quota.ErrQuotaExceeded) {
				return managererrors.NewError(managererrors.ErrorQuotaExceeded, "api-key quota exceeded")
			}
			return err
		},
		Release: func(ctx context.Context, lockString string) error {
			return m.quota.Release(ctx, quota.ReleaseRequest{User: user, LockString: lockString})
		},
	}
}
```

- [ ] **Step 5: Wrap claim and clone infra options**

In `ClaimSandbox`, convert:

```go
infraOpts := opts.Infra
infraOpts.Admission = m.quotaAdmission(infraOpts.User, opts.Quota)
sandbox, claimMetrics, err := m.infra.ClaimSandbox(ctx, infraOpts)
```

Do the same for clone.

- [ ] **Step 6: Move delete release into sandbox-manager**

After `Kill` or successful reuse trigger returns nil, release with bounded context:

```go
func (m *SandboxManager) releaseQuotaAfterDelete(ctx context.Context, opts DeleteSandboxOptions) {
	if m == nil || m.quota == nil || opts.Quota == nil || !opts.Quota.IsLimited() || opts.Sandbox == nil {
		return
	}
	annotations := opts.Sandbox.GetAnnotations()
	if annotations[agentsv1alpha1.AnnotationOwner] != opts.User {
		return
	}
	lockString := annotations[agentsv1alpha1.AnnotationLock]
	if lockString == "" {
		return
	}
	releaseCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), infra.SandboxAdmissionReleaseTimeout)
	defer cancel()
	if err := m.quota.Release(releaseCtx, quota.ReleaseRequest{User: opts.User, LockString: lockString}); err != nil {
		klog.FromContext(ctx).Error(err, "failed to release quota after accepted sandbox delete", "owner", opts.User, "lockString", lockString)
	}
}
```

Wire it in: change `DeleteSandbox(ctx, sbx infra.Sandbox)` to `DeleteSandbox(ctx, opts DeleteSandboxOptions)`, replace
the body's `sbx` with `opts.Sandbox`, and call `m.releaseQuotaAfterDelete(ctx, opts)` on **both** accepted-delete
return paths — after `deleteRouteAndSync` on the reuse-trigger success branch **and** after `deleteRouteAndSync` on the
`Kill` success branch. This preserves today's behavior (the E2B handler releases whenever the manager returns nil on
either path). Do **not** release on the early error returns.

- [ ] **Step 7: Update E2B create paths**

Remove `sc.quotaAdmission`, `quotaFootprintFromResource`, and `quotaRequestReleaseContext` from E2B. Build manager options:

```go
opts := sandboxmanager.ClaimSandboxOptions{
	Infra: infra.ClaimSandboxOptions{
		Namespace: sc.getNamespaceOfUser(user),
		Template:  request.TemplateID,
		User:      user.ID.String(),
		Modifier:  func(sbx infra.Sandbox) { ... },
	},
	Quota: user.QuotaSpec.DeepCopy(),
}
```

and:

```go
sbx, err := sc.manager.ClaimSandbox(ctx, opts)
```

- [ ] **Step 8: Update E2B delete path**

Replace direct quota release in `pkg/servers/e2b/services.go` with:

```go
if err := sc.manager.DeleteSandbox(r.Context(), sandboxmanager.DeleteSandboxOptions{
	Sandbox: sbx,
	User:    user.ID.String(),
	Quota:   user.QuotaSpec.DeepCopy(),
}); err != nil {
	...
}
```

- [ ] **Step 9: Batch migrate sandbox-manager API tests**

Update every direct manager API call in `pkg/sandbox-manager/api_test.go` to the wrapper options. Examples:

```go
manager.ClaimSandbox(ctx, sandbox_manager.ClaimSandboxOptions{Infra: infra.ClaimSandboxOptions{...}})
manager.CloneSandbox(ctx, sandbox_manager.CloneSandboxOptions{Infra: infra.CloneSandboxOptions{...}})
manager.DeleteSandbox(ctx, sandbox_manager.DeleteSandboxOptions{Sandbox: sbx, User: user, Quota: quotaSpec})
```

This is a mechanical migration across all claim/clone/delete manager tests, not only the new admission tests.

- [ ] **Step 10: Run focused tests**

Run:

```bash
go test ./pkg/sandbox-manager ./pkg/servers/e2b
```

Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add pkg/sandbox-manager pkg/servers/e2b
git commit -s -m "refactor: build quota admission in sandbox manager"
```

---

### Task 5: Move Quota Runtime Ownership Into Sandbox-Manager

**Files:**
- Modify: `pkg/sandbox-manager/config/manager.go`
- Modify: `pkg/sandbox-manager/core.go`
- Modify: `pkg/sandbox-manager/core_test.go`
- Modify: `pkg/sandbox-manager/quota/interface.go`
- Modify: `pkg/servers/e2b/api_key.go`
- Modify: `pkg/servers/e2b/api_key_test.go`
- Modify: `pkg/servers/e2b/core.go`
- Modify: `pkg/servers/e2b/core_test.go`
- Modify: `cmd/sandbox-manager/main.go`

**Interfaces:**
- Produces:

```go
type QuotaOptions struct {
	RedisAddr         string
	RedisUsername     string
	RedisPassword     string
	RedisDB           int
	OperationTimeout  time.Duration
	BreakerN          int
	BreakerD          time.Duration
	AntiDriftInterval time.Duration
	AntiDriftGrace    time.Duration
}
```

- Extends `quotaEnforcer` with `Cleanup` for `CleanupQuota` (or add a separate unexported `quotaCleaner` interface).
- Produces: `func (m *SandboxManager) InitQuota(ctx context.Context, opts config.QuotaOptions, subjects quota.SubjectLister) error`
- Produces: `func (m *SandboxManager) CleanupQuota(ctx context.Context, user string) error`

- [ ] **Step 1: Add config tests**

Add table-driven tests for default quota values:

```go
func TestInitOptionsQuotaDefaults(t *testing.T) {
	opts := InitOptions(SandboxManagerOptions{})
	assert.Equal(t, 50*time.Millisecond, opts.Quota.OperationTimeout)
	assert.Equal(t, 3, opts.Quota.BreakerN)
	assert.Equal(t, 30*time.Second, opts.Quota.BreakerD)
	assert.Equal(t, 5*time.Minute, opts.Quota.AntiDriftInterval)
	assert.Equal(t, 10*time.Minute, opts.Quota.AntiDriftGrace)
}
```

- [ ] **Step 2: Add runtime fields to `SandboxManager`**

`m.quota quotaEnforcer` already exists from Task 4. Add only:

```go
quotaAntiDrift   *quota.AntiDriftDriver
quotaRedisClient interface{ Close() error }
```

Extend `quotaEnforcer` (or add `quotaCleaner`) so `CleanupQuota` can call `Cleanup`:

```go
type quotaEnforcer interface {
	Acquire(ctx context.Context, req quota.AcquireRequest) error
	Release(ctx context.Context, req quota.ReleaseRequest) error
	Cleanup(ctx context.Context, user string) error
}
```

`*quota.Manager` satisfies the extended interface.

- [ ] **Step 3: Implement `InitQuota` in sandbox-manager**

Move the logic currently in E2B `initQuota` into sandbox-manager. Precondition: call `InitQuota` only after
`Build()` has initialized `m.infra`, and register anti-drift on `m.infra.GetCache()` so the driver uses the same
informer instance as the hot path.

```go
func (m *SandboxManager) InitQuota(ctx context.Context, opts config.QuotaOptions, subjects quota.SubjectLister) error {
	if opts.RedisAddr == "" {
		m.quota = quota.NewManager(quota.NoopBackend{})
		return nil
	}
	if m.infra == nil || m.infra.GetCache() == nil {
		return fmt.Errorf("api-key quota Redis is configured but cache is not available")
	}
	redisClient := redis.NewClient(&redis.Options{
		Addr:     opts.RedisAddr,
		Username: opts.RedisUsername,
		Password: opts.RedisPassword,
		DB:       opts.RedisDB,
	})
	redisBackend := quota.NewRedisBackend(redisClient, opts.OperationTimeout)
	hotBackend := quota.NewBreakerBackend(redisBackend, opts.BreakerN, opts.BreakerD)
	driver := quota.NewAntiDriftDriver(quota.AntiDriftConfig{
		Interval: opts.AntiDriftInterval,
		Grace:    opts.AntiDriftGrace,
	}, m, subjects, m.infra.GetCache(), redisBackend)
	registration, err := m.infra.GetCache().AddSandboxEventHandler(ctx, driver.SandboxEventHandler())
	if err != nil {
		_ = redisClient.Close()
		return err
	}
	driver.SetEventRegistration(registration)
	m.quota = quota.NewManager(hotBackend)
	m.quotaAntiDrift = driver
	m.quotaRedisClient = redisClient
	return nil
}
```

- [ ] **Step 4: Run quota driver from manager lifecycle**

`SandboxManager.Run` currently ends with `return m.infra.Run(ctx)` (non-blocking — the E2B `Run` continues to start
the HTTP server after `sc.manager.Run` returns). Capture that error first, then start the driver, so a failed infra
start still propagates:

```go
if err := m.infra.Run(ctx); err != nil {
	return err
}
if m.quotaAntiDrift != nil {
	m.quotaAntiDrift.Run(ctx)
}
return nil
```

In `Stop`, stop the driver then close the Redis client, mirroring the E2B `shutdown` ordering removed in Step 6
(`m.quotaAntiDrift.Stop()` before `m.quotaRedisClient.Close()`).

- [ ] **Step 5: Implement `CleanupQuota`**

Add:

```go
func (m *SandboxManager) CleanupQuota(ctx context.Context, user string) error {
	if m == nil || m.quota == nil || user == "" {
		return nil
	}
	return m.quota.Cleanup(ctx, user)
}
```

- [ ] **Step 6: Update E2B controller initialization**

E2B should build keys, then initialize manager quota. Replace the old E2B quota config field with a sandbox-manager
config field:

```go
type Controller struct {
	quotaOpts config.QuotaOptions
}

func NewController(..., quotaOpts config.QuotaOptions) *Controller {
	return &Controller{
		quotaOpts: quotaOpts,
	}
}

func (sc *Controller) sandboxManagerOptions() config.SandboxManagerOptions {
	return config.SandboxManagerOptions{
		// existing fields...
		Quota: sc.quotaOpts,
	}
}
```

Then initialize runtime quota from that same option value:

```go
if sc.keys != nil {
	if err := sc.manager.InitQuota(ctx, sc.quotaOpts, keys.NewQuotaSubjectLister(sc.keys)); err != nil {
		return err
	}
} else {
	if err := sc.manager.InitQuota(ctx, config.QuotaOptions{}, nil); err != nil {
		return err
	}
}
```

Move deleted-key dynamic cleanup in this same task, before removing `sc.quota`:

```go
err := sc.manager.CleanupQuota(cleanupCtx, apiKeyID)
```

Update the cleanup tests in `pkg/servers/e2b/api_key_test.go` to fake sandbox-manager cleanup instead of an E2B
quota manager. The bounded retry and "unlimited key deletion does not cleanup" assertions stay in this task.

After `api_key.go` no longer references them, remove from E2B `Controller`:

- `quota`, `quotaAntiDrift`, `quotaRedisClient` fields
- `quotaManager` and `redisClientCloser` interfaces (dead after the move)
- `initQuota` and anti-drift `Run`/`Stop` wiring in `core.go`

Do not create a second cache in E2B; quota runtime initialization must use the manager-owned infra cache.
Delete the moved `quota.Config` type from `pkg/sandbox-manager/quota/interface.go`; `config.QuotaOptions` is the
only remaining runtime config struct after this task.

Adjust `NewController` so it no longer accepts a `quota.Config` argument from the quota package. It should accept
`config.QuotaOptions`, store it on the controller, and feed it into `sandboxManagerOptions().Quota` and
`SandboxManager.InitQuota`. Do not leave `sandboxManagerOptions().Quota` at its zero value when Redis flags were
set.

- [ ] **Step 7: Update cmd wiring**

In `cmd/sandbox-manager/main.go`, stop importing E2B quota config. Build one `config.QuotaOptions{...}` from the
parsed Redis flags, pass it to `e2b.NewController(..., quotaOpts)`, and ensure `sandboxManagerOptions()` copies it
into `config.SandboxManagerOptions{Quota: quotaOpts}`.

- [ ] **Step 8: Run focused tests**

Run:

```bash
go test ./pkg/sandbox-manager ./pkg/servers/e2b
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add pkg/sandbox-manager pkg/servers/e2b cmd/sandbox-manager
git commit -s -m "refactor: move quota runtime ownership to sandbox manager"
```

---

### Task 6: Primary-Aware Anti-Drift Wait And Cancel

**Files:**
- Modify: `pkg/sandbox-manager/leader.go`
- Modify: `pkg/sandbox-manager/leader_test.go`
- Modify: `pkg/sandbox-manager/quota/interface.go`
- Modify: `pkg/sandbox-manager/quota/antidrift.go`
- Modify: `pkg/sandbox-manager/quota/antidrift_test.go`

**Interfaces:**
- Produces on sandbox-manager:

```go
func (m *SandboxManager) WaitPrimary(ctx context.Context) error
func (m *SandboxManager) PrimaryChanged() <-chan struct{}
```

- Quota consumes:

```go
type PrimaryChecker interface {
	IsPrimary() bool
	WaitPrimary(ctx context.Context) error
	PrimaryChanged() <-chan struct{}
}
```

This task is a **behavior change** (not a file-move cleanup): anti-drift today runs interval cycles whenever
`stillPrimary()` is true at cycle start, but does **not** block until primary or cancel promptly on primary loss.
Keep it as its own commit after Tasks 1–5. Preserve existing `AntiDriftDriver.Stop()` semantics (`stopCh`,
`cycleCancel`, event registration removal).

Do **not** drop the existing leaked-release grace. The current driver gates a leaked-entry release on
`AntiDriftConfig.Grace` **plus** a two-consecutive-pass (`seenPreviousSuccessfulPass`) check. Design §6.4.2 phrases the
gate as "two consecutive passes, no per-entry `ts`"; the current grace+two-pass behavior is a strictly more
conservative superset, so this refactor must keep it as-is (retain `QuotaOptions.AntiDriftGrace` and the
`firstSeen`/`confirmed` logic).

- [ ] **Step 1: Write primary notification tests**

Add tests that verify wait blocks until primary and returns on context cancellation:

```go
func TestPrimaryStateWaitPrimary(t *testing.T) {
	state := &primaryState{}
	ctx, cancel := context.WithTimeout(t.Context(), time.Second)
	defer cancel()

	done := make(chan error, 1)
	go func() { done <- state.WaitPrimary(ctx) }()

	select {
	case <-done:
		t.Fatal("WaitPrimary returned before primary")
	case <-time.After(20 * time.Millisecond):
	}

	state.set(true)
	require.NoError(t, <-done)
}
```

- [ ] **Step 2: Implement primary state notification with lazy channel init**

Extend `primaryState` (do **not** assume builder initialization — tests and `core.go` use `&primaryState{}`):

```go
type primaryState struct {
	primary atomic.Bool
	mu      sync.Mutex
	changed chan struct{} // lazily allocated; never nil after first PrimaryChanged()
}

func (s *primaryState) PrimaryChanged() <-chan struct{} {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.changed == nil {
		s.changed = make(chan struct{})
	}
	return s.changed
}

func (s *primaryState) set(v bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.primary.Load() == v {
		return
	}
	s.primary.Store(v)
	if s.changed != nil {
		close(s.changed)
	}
	s.changed = make(chan struct{})
}

func (s *primaryState) WaitPrimary(ctx context.Context) error {
	if s.IsPrimary() {
		return nil
	}
	for {
		ch := s.PrimaryChanged()
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-ch:
			if s.IsPrimary() {
				return nil
			}
		}
	}
}
```

- [ ] **Step 3: Add manager forwarding methods**

```go
func (m *SandboxManager) WaitPrimary(ctx context.Context) error {
	if m == nil || m.primary == nil {
		return nil
	}
	return m.primary.WaitPrimary(ctx)
}

func (m *SandboxManager) PrimaryChanged() <-chan struct{} {
	if m == nil || m.primary == nil {
		ch := make(chan struct{})
		close(ch)
		return ch
	}
	return m.primary.PrimaryChanged()
}
```

- [ ] **Step 4: Update anti-drift run loop**

Replace interval-only `runLoop` with a primary-gated loop. **Preserve** `Stop()`, `runDone`, `stopCh`, and
`setCycleCancel` / `clearCycleCancel` integration:

```go
func (d *AntiDriftDriver) runLoop(ctx context.Context) {
	for {
		if err := d.primary.WaitPrimary(ctx); err != nil {
			return
		}
		if !d.runWhilePrimary(ctx) {
			return
		}
	}
}

func (d *AntiDriftDriver) runWhilePrimary(ctx context.Context) bool {
	d.runCycle(ctx) // immediate cycle on primary acquire

	ticker := time.NewTicker(d.cfg.Interval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return false
		case <-d.stopCh:
			return false
		case <-d.primary.PrimaryChanged():
			if !d.primary.IsPrimary() {
				d.cancelActiveCycleAndClearLeaked()
				return true // outer loop waits for primary again
			}
		case <-ticker.C:
			d.runCycle(ctx)
		}
	}
}
```

`cancelActiveCycleAndClearLeaked` must invoke the existing `cycleCancel`, clear `seenLeaked`, and increment the
existing `not_primary` skip metric — same as today's `stillPrimary()` early returns.

`AntiDriftConfig.CycleTimeout` stays on the driver (default 30s); it is not exposed on `config.QuotaOptions`.

- [ ] **Step 5: Keep event handlers primary-gated**

Keep `reconcileSandboxEvent` no-op when `!IsPrimary()`. No workqueue is added.

- [ ] **Step 6: Add anti-drift tests**

Cover:

```go
func TestAntiDriftRunWaitsForPrimary(t *testing.T)
func TestAntiDriftPrimaryLossCancelsCycleAndClearsLeaked(t *testing.T)
func TestAntiDriftRunsImmediateCycleOnPrimaryAcquire(t *testing.T)
```

Use fake primary with channels; avoid real leader election.

- [ ] **Step 7: Run focused tests**

Run:

```bash
go test ./pkg/sandbox-manager ./pkg/sandbox-manager/quota
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add pkg/sandbox-manager pkg/sandbox-manager/quota
git commit -s -m "refactor: gate quota anti-drift on primary signal"
```

---

### Task 7: Clone Lockstring Precondition Regression

**Files:**
- Modify: `pkg/sandbox-manager/infra/sandboxcr/clone.go`
- Modify: `pkg/sandbox-manager/infra/sandboxcr/clone_test.go`
- Review only: `pkg/servers/e2b/create.go`

**Interfaces:**
- Preserves infra admission signature:

```go
type SandboxAdmission struct {
	Acquire func(ctx context.Context, lockString string, resource SandboxResource) error
	Release func(ctx context.Context, lockString string) error
}
```

- [ ] **Step 1: Add clone regression test**

Ensure admission sees the same lockstring that is persisted on the CR:

```go
func TestCloneSandboxAdmissionUsesPersistedLockString(t *testing.T) {
	var acquired string
	opts := infra.CloneSandboxOptions{
		User: "user-1",
		Admission: &infra.SandboxAdmission{
			Acquire: func(_ context.Context, lockString string, _ infra.SandboxResource) error {
				acquired = lockString
				return nil
			},
		},
	}
	sbx, _, err := CloneSandbox(t.Context(), opts, cache)
	require.NoError(t, err)
	require.NotEmpty(t, acquired)
	assert.Equal(t, acquired, sbx.GetAnnotations()[agentsv1alpha1.AnnotationLock])
}
```

- [ ] **Step 2: Verify existing clone behavior (no code change expected)**

Current `clone.go` already calls `chooseCloneAttemptLockString` before `Admission.Acquire` and persists the same
`opts.LockString` on the CR. If the new regression test passes without edits, leave implementation unchanged. Only
add stamping if the test proves a gap.

- [ ] **Step 3: Run focused tests**

Run:

```bash
go test ./pkg/sandbox-manager/infra/sandboxcr
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add pkg/sandbox-manager/infra/sandboxcr
git commit -s -m "test: cover clone quota lockstring precondition"
```

---

### Task 8: E2B Static Wire Finalization

**Files:**
- Modify: `pkg/servers/e2b/api_key_test.go`
- Modify: `pkg/servers/e2b/models/quota_test.go`
- Modify: `pkg/servers/e2b/keys/secret_test.go`
- Modify: `pkg/servers/e2b/keys/mysql_test.go`

**Interfaces:**
- E2B public quota wire accepts only full dimension keys.

- [ ] **Step 1: Update wire tests for short-key rejection**

Add explicit cases:

```go
{
	name:        "short count key is rejected",
	raw:         json.RawMessage(`{"running":{"count":2}}`),
	expectError: `unsupported quota dimension "count"`,
}
```

and equivalent `cpu` / `memory` cases.

- [ ] **Step 2: Confirm stored format unchanged**

Keep stored internal JSON expectations as:

```json
{"limits":[{"dimension":"sandbox.count","scope":"all","limit":50}]}
```

Do not store nested public wire shape in key storage.

- [ ] **Step 3: Run focused tests**

Run:

```bash
go test ./pkg/servers/e2b ./pkg/servers/e2b/models ./pkg/servers/e2b/keys
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add pkg/servers/e2b
git commit -s -m "refactor: keep e2b quota handling static"
```

---

### Task 9: Final Verification And Review Cleanup

**Files:**
- Inspect all changed files.
- No generated file edits.

**Interfaces:**
- No new public interface beyond tasks above.

- [ ] **Step 1: Search for forbidden layering**

Run:

```bash
rg 'pkg/servers/e2b/quota|pkg/servers/e2b/(keys|models)' pkg/sandbox-manager
```

Expected: no output.

- [ ] **Step 2: Search for old short-key fixtures**

Run:

```bash
rg '"(count|cpu|memory)"' pkg/servers/e2b pkg/sandbox-manager docs/specs/2026-06-17-api-key-sandbox-quota-redis.md
```

Expected: no public quota JSON fixtures using short keys. Non-quota text and Go identifiers are acceptable after manual review.

- [ ] **Step 2a: Remove the Task 2 compile bridge**

Confirm nothing still depends on the transitional aliases, then delete the bridge block from
`pkg/servers/e2b/models/quota.go`:

```bash
rg 'models\.(QuotaSpec|QuotaLimit|QuotaDimension|QuotaScope|Dim[A-Za-z]+|Scope[A-Za-z]+|NormalizeQuotaSpec|ErrQuotaLimitNegative)' pkg/servers/e2b
```

Expected: no output. If empty, remove the alias `type`/`const`/`var` block added in Task 2 Step 4 (keep only the four
wire/wrapper functions). If non-empty, migrate those callers to `quota.*` first. Step 6/Step 7 below re-verify
compilation after removal.

- [ ] **Step 3: Search for duplicated live predicate**

Run:

```bash
rg 'IsLiveForQuota|IsNotTerminating' pkg/cache pkg/sandbox pkg/sandbox-manager/quota
```

Expected: `IsNotTerminating` implementation appears only in `pkg/sandbox/lifecycle`; quota has only a wrapper; cache imports lifecycle directly.

- [ ] **Step 4: Search for unsafe manager-level enforce flags and stale `APIKeyID`**

Run:

```bash
rg 'req\.Enforce|Enforce\s+bool' pkg/sandbox-manager/quota
rg 'APIKeyID' pkg/sandbox-manager/quota pkg/sandbox-manager cmd
```

Expected: no `AcquireRequest.Enforce` or `req.Enforce` in `Manager.Acquire`; `AcquireParams.Enforce` may still
exist for the backend and anti-drift. No `APIKeyID` outside comments/docs.

- [ ] **Step 5: Search for stale E2B dynamic quota ownership**

Run:

```bash
rg 'sc\.quota|quotaCfg|quota\.Config' pkg/servers/e2b cmd/sandbox-manager
```

Expected: no output. E2B may keep `quotaOpts config.QuotaOptions`, but it must not own a dynamic quota manager or
use the old quota package config type.

- [ ] **Step 6: Run focused package tests**

Run:

```bash
go test ./pkg/sandbox/lifecycle ./pkg/cache ./pkg/sandbox-manager ./pkg/sandbox-manager/quota ./pkg/sandbox-manager/infra/sandboxcr ./pkg/servers/e2b ./pkg/servers/e2b/models ./pkg/servers/e2b/keys
```

Expected: PASS.

- [ ] **Step 7: Run final build**

Run:

```bash
go build ./cmd/sandbox-manager
```

Expected: PASS.

- [ ] **Step 8: Check formatting and whitespace**

Run:

```bash
gofmt -w pkg/sandbox/lifecycle pkg/cache pkg/sandbox-manager pkg/servers/e2b cmd/sandbox-manager
git diff --check
```

Expected: no output from `git diff --check`.

- [ ] **Step 9: Commit final cleanup if needed**

Only if Step 8 produced formatting or import cleanup changes:

```bash
git add pkg/sandbox/lifecycle pkg/cache pkg/sandbox-manager pkg/servers/e2b cmd/sandbox-manager
git commit -s -m "chore: clean up quota refactor formatting"
```

---

## Self-Review

- Spec coverage: covered quota type sinking, full wire keys, E2B static-only responsibility, manager wrapper options, manager-built admission, dynamic Redis quota ownership in sandbox-manager, SubjectLister decoupling **in the same task as the quota package move** (no import cycle), shared lifecycle predicate, shared resource footprint mapper, clone lockstring regression, primary-aware anti-drift as a separate behavior slice, cleanup decoupling, and focused verification.
- Compile-safe task boundaries: Task 2 leaves transitional `models.Quota*` aliases (removed in Task 9) plus a `go build ./pkg/servers/e2b/...` gate so moving the model out of `models` does not break the un-migrated dynamic package / `create.go`; Task 3 lands SubjectLister before/alongside the move; Task 4 introduces `quotaEnforcer` before admission fakes and wires `releaseQuotaAfterDelete` into both `DeleteSandbox` success paths; Task 5 wires runtime without redefining the quota field type and captures the `m.infra.Run` error before starting the driver.
- Placeholder scan: no task uses undefined placeholders; each task has concrete files, signatures, commands, and expected results.
- Type consistency: `quota.QuotaSpec` is the single static model type; E2B imports it only for static config; `AcquireRequest.User` replaces `APIKeyID` per the Task 3 rename checklist; `Manager.Acquire` always enforces and only backend `AcquireParams` carries `Enforce`; `config.QuotaOptions` replaces `quota.Config` and is copied through `NewController -> sandboxManagerOptions().Quota -> InitQuota`; manager options wrap infra options under `Infra`; `InRunningScope` intentionally keeps `Spec.Paused` semantics.
