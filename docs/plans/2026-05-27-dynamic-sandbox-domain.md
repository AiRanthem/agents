# Dynamic Sandbox Domain Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the E2B Sandbox response `domain` field resolve from the current HTTP request when `--e2b-domain` is not set, fix the `BrowserUse` websocket URL for customized deployments, and make the standard kustomize manifest default to dynamic resolution.

**Architecture:** Domain resolution stays in the Controller layer. The `proxy.RequestAdapter` interface (and its `E2BAdapter` implementation) is reused only for `ParseRequest` — no new adapter methods. A new `resolveSandboxDomain(r *http.Request)` helper runs at the very top of every response-affecting handler, before any state-changing operation. `BrowserUse` gains a customized URL builder so customized deployments stop returning a non-routable native-style websocket URL.

**Tech Stack:** Go, controller-runtime fake client (`sigs.k8s.io/controller-runtime/pkg/client/fake`), `httptest`, `testify` (`assert`/`require`), `proxyutils.DefaultRequestFunc` (global function pointer used to mock the upstream sandbox HTTP call inside `BrowserUse` tests).

**Source spec:** `docs/specs/2026-05-27-dynamic-sandbox-domain-design.md`.

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `pkg/utils/sandbox-manager/e2b.go` | Native + customized sandbox address builders | Modify (add new func) |
| `pkg/utils/sandbox-manager/e2b_test.go` | Unit tests for both builders | Create |
| `pkg/servers/e2b/core.go` | Controller struct, `NewController`, `Init` | Modify (add `requestAdapter` field, hoist adapter construction) |
| `pkg/servers/e2b/sandbox.go` | Domain resolution helpers, sandbox conversion | Modify (add helpers, change `convertToE2BSandbox` signature) |
| `pkg/servers/e2b/sandbox_test.go` | Unit tests for new helpers | Modify (add `TestSplitHostPort`, `TestIsCustomizedRequest`, `TestResolveSandboxDomain`, `TestResolveSandboxDomain_NilAdapter`) |
| `pkg/servers/e2b/create.go` | `CreateSandbox`, claim, clone | Modify (resolve domain at top, thread through helpers) |
| `pkg/servers/e2b/create_test.go` | `CreateSandbox` integration tests | Modify (add domain cases) |
| `pkg/servers/e2b/services.go` | `DescribeSandbox`, `BrowserUse` | Modify (resolve domain, BrowserUse picks address shape) |
| `pkg/servers/e2b/services_test.go` | `DescribeSandbox` / `BrowserUse` integration tests | Modify (add domain cases) |
| `pkg/servers/e2b/pause_resume.go` | `ConnectSandbox` | Modify (resolve domain) |
| `pkg/servers/e2b/pause_resume_test.go` | `ConnectSandbox` integration tests | Modify (add domain cases) |
| `pkg/servers/e2b/list.go` | `ListSandboxes` | Modify (resolve once, reuse for each entry) |
| `pkg/servers/e2b/list_test.go` | `ListSandboxes` integration tests | Modify (add domain case) |
| `cmd/sandbox-manager/main.go` | Flag definitions | Modify (flip `--e2b-domain` default) |
| `config/sandbox-manager/deployment.yaml` | Default kustomize manifest | Modify (drop `--e2b-domain` arg) |
| `config/sandbox-manager/configuration_patch.yaml` | JSONPatch overlay | Modify (drop domain patch, renumber admin-key path) |
| `docs/best-practices/use-e2b.md` | User-facing config guide | Modify (describe new default and override cases) |

---

## Task 1: Add `GetCustomizedSandboxAddress` helper

**Files:**
- Modify: `pkg/utils/sandbox-manager/e2b.go`
- Create: `pkg/utils/sandbox-manager/e2b_test.go`

- [ ] **Step 1: Write the failing tests**

Create `pkg/utils/sandbox-manager/e2b_test.go`:

```go
/*
Copyright 2026.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

package utils

import (
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestGetSandboxAddress(t *testing.T) {
	tests := []struct {
		name      string
		sandboxID string
		domain    string
		port      int32
		expect    string
	}{
		{"basic", "abc123", "example.com", 8080, "8080-abc123.example.com"},
		{"with port in domain", "abc123", "example.com:8443", 8080, "8080-abc123.example.com:8443"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assert.Equal(t, tt.expect, GetSandboxAddress(tt.sandboxID, tt.domain, tt.port))
		})
	}
}

func TestGetCustomizedSandboxAddress(t *testing.T) {
	tests := []struct {
		name      string
		sandboxID string
		domain    string
		port      int32
		expect    string
	}{
		{"basic", "abc123", "gateway.example.com", 8080, "gateway.example.com/kruise/abc123/8080"},
		{"with port in domain", "abc123", "gateway.example.com:8443", 8080, "gateway.example.com:8443/kruise/abc123/8080"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assert.Equal(t, tt.expect, GetCustomizedSandboxAddress(tt.sandboxID, tt.domain, tt.port))
		})
	}
}
```

- [ ] **Step 2: Run to verify failure**

```
go test ./pkg/utils/sandbox-manager/ -run TestGetCustomizedSandboxAddress -v
```

Expected: FAIL with `undefined: GetCustomizedSandboxAddress`.

- [ ] **Step 3: Implement the new builder**

Edit `pkg/utils/sandbox-manager/e2b.go`. Append after the existing `GetSandboxAddress`:

```go
// GetCustomizedSandboxAddress returns the customized path-style sandbox
// address: "<domain>/kruise/<sandboxId>/<port>". Used by deployments that
// route sandbox traffic by path prefix rather than by subdomain.
func GetCustomizedSandboxAddress(sandboxId, domain string, port int32) string {
	return fmt.Sprintf("%s/kruise/%s/%d", domain, sandboxId, port)
}
```

- [ ] **Step 4: Verify tests pass**

```
go test ./pkg/utils/sandbox-manager/ -run TestGetCustomizedSandboxAddress -v
go test ./pkg/utils/sandbox-manager/ -run TestGetSandboxAddress -v
```

Expected: PASS for both.

- [ ] **Step 5: Commit**

```
git add pkg/utils/sandbox-manager/e2b.go pkg/utils/sandbox-manager/e2b_test.go
git commit -m "feat(utils): add GetCustomizedSandboxAddress for path-style sandbox URL"
```

---

## Task 2: Thread an explicit `domain` parameter through `convertToE2BSandbox` callers

This task is a mechanical refactor only — existing behavior is preserved by passing `sc.domain` everywhere. The dynamic resolver replaces these placeholder values in later tasks.

**Files:**
- Modify: `pkg/servers/e2b/sandbox.go`
- Modify: `pkg/servers/e2b/create.go`
- Modify: `pkg/servers/e2b/services.go`
- Modify: `pkg/servers/e2b/list.go`
- Modify: `pkg/servers/e2b/pause_resume.go`

- [ ] **Step 1: Change `convertToE2BSandbox` signature**

Edit `pkg/servers/e2b/sandbox.go`. Find:

```go
func (sc *Controller) convertToE2BSandbox(sbx infra.Sandbox, accessToken string) *models.Sandbox {
	sandbox := &models.Sandbox{
		SandboxID:       sbx.GetSandboxID(),
		TemplateID:      sbx.GetTemplate(),
		Domain:          sc.domain,
```

Replace with:

```go
func (sc *Controller) convertToE2BSandbox(sbx infra.Sandbox, accessToken, domain string) *models.Sandbox {
	sandbox := &models.Sandbox{
		SandboxID:       sbx.GetSandboxID(),
		TemplateID:      sbx.GetTemplate(),
		Domain:          domain,
```

- [ ] **Step 2: Thread `domain` through `createSandboxWithClaim` / `createSandboxWithClone`**

Edit `pkg/servers/e2b/create.go`. In `CreateSandbox`, immediately after the `if ... HasTemplate ...` decision (before each `return sc.createSandboxWith*` call), the dispatch becomes:

```go
domain := sc.domain
if sc.manager.GetInfra().HasTemplate(ctx, infra.HasTemplateOptions{
	Namespace: namespace,
	Name:      request.TemplateID,
}) {
	log.Info("infra has template, will create sandbox with claim", "templateID", request.TemplateID)
	return sc.createSandboxWithClaim(ctx, request, user, domain)
} else if sc.manager.GetInfra().HasCheckpoint(ctx, infra.HasCheckpointOptions{
	Namespace:    namespace,
	CheckpointID: request.TemplateID,
}) {
	log.Info("infra has checkpoint, will create sandbox with clone", "templateID", request.TemplateID)
	return sc.createSandboxWithClone(ctx, request, user, domain)
}
```

Update helper signatures and call sites:

```go
func (sc *Controller) createSandboxWithClaim(ctx context.Context, request models.NewSandboxRequest, user *models.CreatedTeamAPIKey, domain string) (web.ApiResponse[*models.Sandbox], *web.ApiError) {
```

```go
func (sc *Controller) createSandboxWithClone(ctx context.Context, request models.NewSandboxRequest, user *models.CreatedTeamAPIKey, domain string) (web.ApiResponse[*models.Sandbox], *web.ApiError) {
```

In `createSandboxWithClaim`, change the success return to pass `domain`:

```go
return web.ApiResponse[*models.Sandbox]{
	Code: http.StatusCreated,
	Body: sc.convertToE2BSandbox(sbx, accessToken, domain),
}, nil
```

In `createSandboxWithClone`, the analogous change:

```go
return web.ApiResponse[*models.Sandbox]{
	Code: http.StatusCreated,
	Body: sc.convertToE2BSandbox(sbx, sandboxutils.GetAccessToken(sbx), domain),
}, nil
```

- [ ] **Step 3: Update `DescribeSandbox`**

Edit `pkg/servers/e2b/services.go`. Find:

```go
return web.ApiResponse[*models.Sandbox]{
	Body: sc.convertToE2BSandbox(sbx, sandboxutils.GetAccessToken(sbx)),
}, nil
```

Replace with:

```go
return web.ApiResponse[*models.Sandbox]{
	Body: sc.convertToE2BSandbox(sbx, sandboxutils.GetAccessToken(sbx), sc.domain),
}, nil
```

- [ ] **Step 4: Update `ListSandboxes`**

Edit `pkg/servers/e2b/list.go`. Replace the conversion loop (around line 160):

```go
domain := sc.domain
e2bSandboxes := make([]*models.Sandbox, 0, len(sandboxes))
for _, sbx := range sandboxes {
	e2bSandboxes = append(e2bSandboxes, sc.convertToE2BSandbox(sbx, "", domain))
}
```

- [ ] **Step 5: Update `ConnectSandbox`**

Edit `pkg/servers/e2b/pause_resume.go`. Find the success return (around line 236):

```go
return web.ApiResponse[*models.Sandbox]{
	Code: statusCode,
	Body: sc.convertToE2BSandbox(sbx, sandboxutils.GetAccessToken(sbx)),
}, nil
```

Replace with:

```go
return web.ApiResponse[*models.Sandbox]{
	Code: statusCode,
	Body: sc.convertToE2BSandbox(sbx, sandboxutils.GetAccessToken(sbx), sc.domain),
}, nil
```

- [ ] **Step 6: Compile-check**

```
go vet ./pkg/servers/e2b/...
```

Expected: no errors.

- [ ] **Step 7: Run existing tests to confirm behavior unchanged**

```
go test ./pkg/servers/e2b/ -count=1
```

Expected: PASS — every handler still returns the original `sc.domain`.

- [ ] **Step 8: Commit**

```
git add pkg/servers/e2b/sandbox.go pkg/servers/e2b/create.go pkg/servers/e2b/services.go pkg/servers/e2b/list.go pkg/servers/e2b/pause_resume.go
git commit -m "refactor(e2b): thread explicit domain through convertToE2BSandbox callers"
```

---

## Task 3: Move request-adapter construction into `NewController`

The integration tests in `core_test.go::Setup` build a `Controller` via `NewController` and skip `Init()`. Constructing the adapter in `NewController` ensures `sc.requestAdapter` is always non-nil before any handler runs, so test setups do not need to be updated.

**Files:**
- Modify: `pkg/servers/e2b/core.go`

- [ ] **Step 1: Add the field and hoist construction**

Edit `pkg/servers/e2b/core.go`. The `proxy` package is already implicit through `sandboxmanager` but the field needs an explicit import. In the import block add:

```go
"github.com/openkruise/agents/pkg/proxy"
```

(Keep `"github.com/openkruise/agents/pkg/servers/e2b/adapters"` as-is.)

Add field to the `Controller` struct, alongside `mux`/`server`/`stop`:

```go
requestAdapter proxy.RequestAdapter
```

Modify the struct literal inside `NewController` (insert just after `mux: http.NewServeMux(),`):

```go
sc := &Controller{
	mux:                   http.NewServeMux(),
	requestAdapter:        adapters.DefaultAdapterFactory(port),
	domain:                domain,
	clientConfig:          clientConfig,
	port:                  port,
	maxTimeout:            maxTimeout,
	// ...remaining fields unchanged...
}
```

- [ ] **Step 2: Consume the stored adapter in `Init`**

In `Init()`, delete the local `adapter := adapters.DefaultAdapterFactory(sc.port)` line and pass `sc.requestAdapter` to the builder:

```go
func (sc *Controller) Init() error {
	ctx := logs.NewContext()
	log := klog.FromContext(ctx)
	log.Info("init controller")

	sandboxManager, err := sandboxmanager.NewSandboxManagerBuilder(sc.sandboxManagerOptions()).
		WithSandboxInfra().
		WithMemberlistPeers().
		WithRequestAdapter(sc.requestAdapter).
		Build()
	if err != nil {
		return err
	}

	sc.manager = sandboxManager
	sc.cache = sandboxManager.GetInfra().GetCache()
	sc.storageRegistry = storages.NewStorageProvider()
	sc.registerRoutes()

	return sc.initKeyStorage(ctx)
}
```

- [ ] **Step 3: Compile-check**

```
go vet ./pkg/servers/e2b/...
go vet ./cmd/sandbox-manager/...
```

Expected: no errors.

- [ ] **Step 4: Run existing tests**

```
go test ./pkg/servers/e2b/ -count=1
```

Expected: PASS — `Setup()` calls `NewController` so `sc.requestAdapter` is populated automatically.

- [ ] **Step 5: Commit**

```
git add pkg/servers/e2b/core.go
git commit -m "refactor(e2b): hoist request adapter construction into NewController"
```

---

## Task 4: Add `isCustomizedRequest` helper and unit test

**Files:**
- Modify: `pkg/servers/e2b/sandbox.go`
- Modify: `pkg/servers/e2b/sandbox_test.go`

- [ ] **Step 1: Write the failing test**

Append to `pkg/servers/e2b/sandbox_test.go` (if the file lacks the necessary imports, add `net/http`, `net/http/httptest`, `testing`, and `github.com/stretchr/testify/assert`):

```go
func TestIsCustomizedRequest(t *testing.T) {
	tests := []struct {
		name string
		path string
		want bool
	}{
		{"native path", "/sandboxes", false},
		{"native root", "/", false},
		{"kruise api", "/kruise/api/sandboxes", true},
		{"kruise sandbox path", "/kruise/abc/3000/foo", true},
		{"empty path", "", false},
		{"path starting with kruise text but no slash", "/kruisefoo", false},
	}
	sc := &Controller{}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodGet, "http://example.com/", nil)
			req.URL.Path = tt.path
			assert.Equal(t, tt.want, sc.isCustomizedRequest(req))
		})
	}
}
```

- [ ] **Step 2: Run to verify failure**

```
go test ./pkg/servers/e2b/ -run TestIsCustomizedRequest -v
```

Expected: FAIL with `sc.isCustomizedRequest undefined`.

- [ ] **Step 3: Implement the helper**

Edit `pkg/servers/e2b/sandbox.go`. Add `"github.com/openkruise/agents/pkg/servers/e2b/adapters"` to the import block. Append at the bottom of the file:

```go
// isCustomizedRequest reports whether the inbound request uses the customized
// path-prefix adapter (e.g. /kruise/api/...). It mirrors
// adapters.E2BAdapter.ChooseAdapter so that resolveSandboxDomain and BrowserUse
// agree on the deployment shape for the same request.
func (sc *Controller) isCustomizedRequest(r *http.Request) bool {
	return strings.HasPrefix(r.URL.Path, adapters.CustomPrefix)
}
```

- [ ] **Step 4: Verify the test passes**

```
go test ./pkg/servers/e2b/ -run TestIsCustomizedRequest -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```
git add pkg/servers/e2b/sandbox.go pkg/servers/e2b/sandbox_test.go
git commit -m "feat(e2b): add isCustomizedRequest helper for native/customized dispatch"
```

---

## Task 5: Add `splitHostPort` and `resolveSandboxDomain` helpers, with unit tests

**Files:**
- Modify: `pkg/servers/e2b/sandbox.go`
- Modify: `pkg/servers/e2b/sandbox_test.go`

- [ ] **Step 1: Write the failing tests**

Append to `pkg/servers/e2b/sandbox_test.go`. Add `github.com/openkruise/agents/pkg/servers/e2b/adapters` and `github.com/stretchr/testify/require` to imports if missing.

```go
func TestSplitHostPort(t *testing.T) {
	tests := []struct {
		name     string
		in       string
		wantHost string
		wantPort string
	}{
		{"no port", "example.com", "example.com", ""},
		{"with port", "example.com:8443", "example.com", "8443"},
		{"trailing colon", "example.com:", "example.com", ""},
		{"empty", "", "", ""},
		{"port only", ":8080", "", "8080"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			host, port := splitHostPort(tt.in)
			assert.Equal(t, tt.wantHost, host)
			assert.Equal(t, tt.wantPort, port)
		})
	}
}

func TestResolveSandboxDomain(t *testing.T) {
	tests := []struct {
		name        string
		scDomain    string
		host        string
		path        string
		expect      string
		expectError string
	}{
		{"static configured wins", "example.com", "api.foo.com", "/sandboxes", "example.com", ""},
		{"native strip api with port", "", "api.example.com:8443", "/sandboxes", "example.com:8443", ""},
		{"native strip api no port", "", "api.example.com", "/sandboxes", "example.com", ""},
		{"native strip uppercase api", "", "API.example.com", "/sandboxes", "example.com", ""},
		{"native strip uppercase with port", "", "API.example.com:8443", "/sandboxes", "example.com:8443", ""},
		{"native no api prefix", "", "example.com", "/sandboxes", "example.com", ""},
		{"native localhost with port", "", "localhost:7788", "/sandboxes", "localhost:7788", ""},
		{"native apiserver not stripped", "", "apiserver.example.com", "/sandboxes", "apiserver.example.com", ""},
		{"customized host as-is", "", "gateway.example.com", "/kruise/api/sandboxes", "gateway.example.com", ""},
		{"customized api host not stripped", "", "api.gateway.example.com", "/kruise/api/sandboxes", "api.gateway.example.com", ""},
		{"customized case preserved", "", "Gateway.example.com", "/kruise/api/sandboxes", "Gateway.example.com", ""},
		{"empty host returns 500", "", "", "/sandboxes", "", "empty host"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			sc := &Controller{
				domain:         tt.scDomain,
				requestAdapter: adapters.NewE2BAdapter(0),
			}
			req := httptest.NewRequest(http.MethodGet, "http://placeholder"+tt.path, nil)
			req.Host = tt.host
			domain, apiErr := sc.resolveSandboxDomain(req)
			if tt.expectError != "" {
				require.NotNil(t, apiErr)
				assert.Equal(t, http.StatusInternalServerError, apiErr.Code)
				assert.Contains(t, apiErr.Message, tt.expectError)
				return
			}
			require.Nil(t, apiErr)
			assert.Equal(t, tt.expect, domain)
		})
	}
}

func TestResolveSandboxDomain_NilAdapter(t *testing.T) {
	sc := &Controller{requestAdapter: nil}
	req := httptest.NewRequest(http.MethodGet, "http://example.com/sandboxes", nil)
	req.Host = "api.example.com"
	domain, apiErr := sc.resolveSandboxDomain(req)
	require.NotNil(t, apiErr)
	assert.Equal(t, http.StatusInternalServerError, apiErr.Code)
	assert.Contains(t, apiErr.Message, "request adapter not initialized")
	assert.Empty(t, domain)
}
```

- [ ] **Step 2: Run to verify failure**

```
go test ./pkg/servers/e2b/ -run TestSplitHostPort -v
go test ./pkg/servers/e2b/ -run TestResolveSandboxDomain -v
```

Expected: FAIL with `splitHostPort undefined` and `resolveSandboxDomain undefined`.

- [ ] **Step 3: Implement the helpers**

Edit `pkg/servers/e2b/sandbox.go`. Add `"github.com/openkruise/agents/pkg/servers/web"` to imports (`"net/http"` and `"strings"` are already present). Append at the bottom of the file:

```go
// splitHostPort splits a "host[:port]" authority on the last colon. When no
// colon is present, port is returned as "". Unlike net.SplitHostPort this
// does not error on inputs without a port, which is the normal case for an
// HTTP Host header without an explicit port.
func splitHostPort(authority string) (host, port string) {
	idx := strings.LastIndex(authority, ":")
	if idx < 0 {
		return authority, ""
	}
	return authority[:idx], authority[idx+1:]
}

// resolveSandboxDomain derives the user-facing E2B domain for the response
// body or sandbox URL. When --e2b-domain is configured (sc.domain != ""),
// that static value is returned as-is. Otherwise the request adapter parses
// the inbound Host header and the resolver applies native vs. customized
// rules per docs/specs/2026-05-27-dynamic-sandbox-domain-design.md.
//
// Returns *web.ApiError with HTTP 500 when no domain can be derived. The
// resolver never mutates server state; callers must invoke it before any
// state-changing operation so that a 500 cannot leave behind a partially
// created or resumed sandbox.
func (sc *Controller) resolveSandboxDomain(r *http.Request) (string, *web.ApiError) {
	if sc.domain != "" {
		return sc.domain, nil
	}
	if sc.requestAdapter == nil {
		return "", &web.ApiError{
			Code:    http.StatusInternalServerError,
			Message: "sandbox-manager misconfigured: request adapter not initialized",
		}
	}
	parsed := sc.requestAdapter.ParseRequest(map[string]string{
		":path": r.URL.Path,
		"host":  r.Host,
	})
	if parsed.Authority == "" {
		return "", &web.ApiError{
			Code:    http.StatusInternalServerError,
			Message: "cannot resolve sandbox domain: empty host",
		}
	}
	if strings.HasPrefix(parsed.Path, adapters.CustomPrefix) {
		return parsed.Authority, nil
	}
	host, port := splitHostPort(parsed.Authority)
	host = strings.ToLower(host)
	host = strings.TrimPrefix(host, "api.")
	if port == "" {
		return host, nil
	}
	return host + ":" + port, nil
}
```

- [ ] **Step 4: Verify tests pass**

```
go test ./pkg/servers/e2b/ -run TestSplitHostPort -v
go test ./pkg/servers/e2b/ -run TestResolveSandboxDomain -v
```

Expected: PASS for every row (including `TestResolveSandboxDomain_NilAdapter`).

- [ ] **Step 5: Commit**

```
git add pkg/servers/e2b/sandbox.go pkg/servers/e2b/sandbox_test.go
git commit -m "feat(e2b): add resolveSandboxDomain and splitHostPort helpers"
```

---

## Task 6: Wire `DescribeSandbox` through the dynamic resolver

**Files:**
- Modify: `pkg/servers/e2b/services.go`
- Modify: `pkg/servers/e2b/services_test.go`

- [ ] **Step 1: Write the failing test**

Append to `pkg/servers/e2b/services_test.go`:

```go
func TestDescribeSandbox_Domain(t *testing.T) {
	tests := []struct {
		name        string
		scDomain    string
		reqHost     string
		wantDomain  string
		expectError string
	}{
		{"static configured", "example.com", "api.foo.com", "example.com", ""},
		{"dynamic success", "", "api.foo.com", "foo.com", ""},
		{"empty host returns 500", "", "", "", "empty host"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			controller, _, teardown := Setup(t)
			defer teardown()
			controller.domain = tt.scDomain

			user := &models.CreatedTeamAPIKey{
				ID:   keys.AdminKeyID,
				Key:  InitKey,
				Name: "test-user",
			}
			templateName := "describe-domain-template"
			cleanup := CreateSandboxPool(t, controller, templateName, 1)
			defer cleanup()

			createResp, createErr := controller.CreateSandbox(NewRequest(t, nil, models.NewSandboxRequest{
				TemplateID: templateName,
				Metadata: map[string]string{
					models.ExtensionKeySkipInitRuntime: v1alpha1.True,
				},
			}, nil, user))
			require.Nil(t, createErr)
			sandboxID := createResp.Body.SandboxID

			req := NewRequest(t, nil, nil, map[string]string{"sandboxID": sandboxID}, user)
			req.Host = tt.reqHost

			resp, apiErr := controller.DescribeSandbox(req)
			if tt.expectError != "" {
				require.NotNil(t, apiErr)
				assert.Equal(t, http.StatusInternalServerError, apiErr.Code)
				assert.Contains(t, apiErr.Message, tt.expectError)
				return
			}
			require.Nil(t, apiErr)
			require.NotNil(t, resp.Body)
			assert.Equal(t, tt.wantDomain, resp.Body.Domain)
		})
	}
}
```

- [ ] **Step 2: Run to verify failure**

```
go test ./pkg/servers/e2b/ -run TestDescribeSandbox_Domain -v
```

Expected: FAIL — the dynamic case still returns the static `Setup` default (`example.com`); the empty-host case proceeds without resolving and returns 200.

- [ ] **Step 3: Wire the resolver into the handler**

Edit `pkg/servers/e2b/services.go`. Replace the body of `DescribeSandbox`:

```go
func (sc *Controller) DescribeSandbox(r *http.Request) (web.ApiResponse[*models.Sandbox], *web.ApiError) {
	id := r.PathValue("sandboxID")
	log := klog.FromContext(r.Context())
	log.Info("describe sandbox", "id", id)

	domain, apiErr := sc.resolveSandboxDomain(r)
	if apiErr != nil {
		return web.ApiResponse[*models.Sandbox]{}, apiErr
	}

	sbx, apiErr := sc.getSandboxOfUser(r.Context(), id)
	if apiErr != nil {
		log.Error(apiErr, "failed to get sandbox", "id", id)
		return web.ApiResponse[*models.Sandbox]{}, apiErr
	}

	return web.ApiResponse[*models.Sandbox]{
		Body: sc.convertToE2BSandbox(sbx, sandboxutils.GetAccessToken(sbx), domain),
	}, nil
}
```

- [ ] **Step 4: Verify tests pass**

```
go test ./pkg/servers/e2b/ -run TestDescribeSandbox -v
```

Expected: PASS for new `TestDescribeSandbox_Domain` and any existing `TestDescribeSandbox*`.

- [ ] **Step 5: Commit**

```
git add pkg/servers/e2b/services.go pkg/servers/e2b/services_test.go
git commit -m "feat(e2b): resolve DescribeSandbox response domain from request host"
```

---

## Task 7: Wire `CreateSandbox` (claim + clone) through the dynamic resolver

**Files:**
- Modify: `pkg/servers/e2b/create.go`
- Modify: `pkg/servers/e2b/create_test.go`

- [ ] **Step 1: Write the failing test**

Append to `pkg/servers/e2b/create_test.go`:

```go
func TestCreateSandbox_Domain(t *testing.T) {
	tests := []struct {
		name        string
		scDomain    string
		reqHost     string
		wantDomain  string
		wantStatus  int
		expectError string
	}{
		{
			name:       "dynamic success on claim path",
			scDomain:   "",
			reqHost:    "api.dynamic.example.com",
			wantDomain: "dynamic.example.com",
			wantStatus: http.StatusCreated,
		},
		{
			name:        "empty host returns 500 and does not claim",
			scDomain:    "",
			reqHost:     "",
			wantStatus:  http.StatusInternalServerError,
			expectError: "empty host",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			controller, fc, teardown := Setup(t)
			defer teardown()
			controller.domain = tt.scDomain

			user := &models.CreatedTeamAPIKey{
				ID:   keys.AdminKeyID,
				Key:  InitKey,
				Name: "test-user",
			}
			templateName := "create-domain-template"
			cleanup := CreateSandboxPool(t, controller, templateName, 1)
			defer cleanup()

			req := NewRequest(t, nil, models.NewSandboxRequest{
				TemplateID: templateName,
				Metadata: map[string]string{
					models.ExtensionKeySkipInitRuntime: v1alpha1.True,
				},
			}, nil, user)
			req.Host = tt.reqHost

			resp, apiErr := controller.CreateSandbox(req)
			if tt.expectError != "" {
				require.NotNil(t, apiErr)
				assert.Equal(t, tt.wantStatus, apiErr.Code)
				assert.Contains(t, apiErr.Message, tt.expectError)
				// Verify no sandbox was claimed: pool entries stay unclaimed.
				sbxList := &v1alpha1.SandboxList{}
				require.NoError(t, fc.List(t.Context(), sbxList))
				claimed := 0
				for _, sbx := range sbxList.Items {
					if sbx.Labels[v1alpha1.LabelSandboxIsClaimed] == v1alpha1.True {
						claimed++
					}
				}
				assert.Zero(t, claimed, "no sandbox should be claimed when domain resolution fails")
				return
			}
			require.Nil(t, apiErr)
			assert.Equal(t, tt.wantStatus, resp.Code)
			require.NotNil(t, resp.Body)
			assert.Equal(t, tt.wantDomain, resp.Body.Domain)
		})
	}
}
```

- [ ] **Step 2: Run to verify failure**

```
go test ./pkg/servers/e2b/ -run TestCreateSandbox_Domain -v
```

Expected: FAIL — the dynamic case still returns the static `Setup` default; the empty-host case proceeds to claim and returns 201 instead of 500.

- [ ] **Step 3: Wire the resolver at the top of `CreateSandbox`**

Edit `pkg/servers/e2b/create.go`. Replace `CreateSandbox`:

```go
func (sc *Controller) CreateSandbox(r *http.Request) (web.ApiResponse[*models.Sandbox], *web.ApiError) {
	ctx := r.Context()
	log := klog.FromContext(ctx)
	user := GetUserFromContext(ctx)
	if user == nil {
		return web.ApiResponse[*models.Sandbox]{}, &web.ApiError{
			Code:    http.StatusUnauthorized,
			Message: "User is empty",
		}
	}
	domain, apiErr := sc.resolveSandboxDomain(r)
	if apiErr != nil {
		return web.ApiResponse[*models.Sandbox]{}, apiErr
	}
	request, parseErr := sc.parseCreateSandboxRequest(r)
	if parseErr != nil {
		return web.ApiResponse[*models.Sandbox]{}, parseErr
	}
	namespace := sc.getNamespaceOfUser(user)
	log.Info("create sandbox request received", "request", request)
	if sc.manager.GetInfra().HasTemplate(ctx, infra.HasTemplateOptions{
		Namespace: namespace,
		Name:      request.TemplateID,
	}) {
		log.Info("infra has template, will create sandbox with claim", "templateID", request.TemplateID)
		return sc.createSandboxWithClaim(ctx, request, user, domain)
	} else if sc.manager.GetInfra().HasCheckpoint(ctx, infra.HasCheckpointOptions{
		Namespace:    namespace,
		CheckpointID: request.TemplateID,
	}) {
		log.Info("infra has checkpoint, will create sandbox with clone", "templateID", request.TemplateID)
		return sc.createSandboxWithClone(ctx, request, user, domain)
	}
	return web.ApiResponse[*models.Sandbox]{}, &web.ApiError{
		Code:    http.StatusBadRequest,
		Message: "Template or Checkpoint not found",
	}
}
```

The local `domain := sc.domain` introduced in Task 2 is replaced by the resolver call above.

- [ ] **Step 4: Verify tests pass**

```
go test ./pkg/servers/e2b/ -run TestCreateSandbox -v
```

Expected: PASS for the new `TestCreateSandbox_Domain` and the existing `TestCreateSandbox*` family.

- [ ] **Step 5: Commit**

```
git add pkg/servers/e2b/create.go pkg/servers/e2b/create_test.go
git commit -m "feat(e2b): resolve CreateSandbox response domain before claim/clone"
```

---

## Task 8: Wire `ConnectSandbox` through the dynamic resolver

**Files:**
- Modify: `pkg/servers/e2b/pause_resume.go`
- Modify: `pkg/servers/e2b/pause_resume_test.go`

- [ ] **Step 1: Write the failing test**

Append to `pkg/servers/e2b/pause_resume_test.go`:

```go
func TestConnectSandbox_Domain(t *testing.T) {
	tests := []struct {
		name        string
		scDomain    string
		reqHost     string
		wantDomain  string
		wantStatus  int
		expectError string
	}{
		{"static configured", "static.example.com", "api.dynamic.example.com", "static.example.com", http.StatusOK, ""},
		{"dynamic success", "", "api.dynamic.example.com", "dynamic.example.com", http.StatusOK, ""},
		{"empty host returns 500 without mutating sandbox", "", "", "", http.StatusInternalServerError, "empty host"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			controller, fc, teardown := Setup(t)
			defer teardown()
			controller.domain = tt.scDomain

			user := &models.CreatedTeamAPIKey{
				ID:   keys.AdminKeyID,
				Key:  InitKey,
				Name: "test-user",
			}
			templateName := "connect-domain-template"
			cleanup := CreateSandboxPool(t, controller, templateName, 1)
			defer cleanup()

			createResp, createErr := controller.CreateSandbox(NewRequest(t, nil, models.NewSandboxRequest{
				TemplateID: templateName,
				Timeout:    600,
				Metadata: map[string]string{
					models.ExtensionKeySkipInitRuntime: v1alpha1.True,
				},
			}, nil, user))
			require.Nil(t, createErr)
			sandboxID := createResp.Body.SandboxID

			// Snapshot all Sandbox resourceVersions to detect any mutation
			// on the failure path.
			preList := &v1alpha1.SandboxList{}
			require.NoError(t, fc.List(t.Context(), preList))
			preVersions := map[string]string{}
			for _, sbx := range preList.Items {
				preVersions[sbx.Name] = sbx.ResourceVersion
			}

			req := NewRequest(t, nil, models.SetTimeoutRequest{TimeoutSeconds: 300}, map[string]string{
				"sandboxID": sandboxID,
			}, user)
			req.Host = tt.reqHost

			resp, apiErr := controller.ConnectSandbox(req)
			if tt.expectError != "" {
				require.NotNil(t, apiErr)
				assert.Equal(t, tt.wantStatus, apiErr.Code)
				assert.Contains(t, apiErr.Message, tt.expectError)
				postList := &v1alpha1.SandboxList{}
				require.NoError(t, fc.List(t.Context(), postList))
				for _, sbx := range postList.Items {
					assert.Equal(t, preVersions[sbx.Name], sbx.ResourceVersion,
						"sandbox %s must not be mutated on failed resolve", sbx.Name)
				}
				return
			}
			require.Nil(t, apiErr)
			assert.Equal(t, tt.wantStatus, resp.Code)
			require.NotNil(t, resp.Body)
			assert.Equal(t, tt.wantDomain, resp.Body.Domain)
		})
	}
}
```

- [ ] **Step 2: Run to verify failure**

```
go test ./pkg/servers/e2b/ -run TestConnectSandbox_Domain -v
```

Expected: FAIL — dynamic case returns the static `Setup` default; empty-host case proceeds and mutates sandbox state.

- [ ] **Step 3: Wire the resolver into `ConnectSandbox`**

Edit `pkg/servers/e2b/pause_resume.go`. Replace the head of `ConnectSandbox` (everything from the function signature up to and including the `sbx, apiErr := sc.getSandboxOfUser(...)` block) with:

```go
func (sc *Controller) ConnectSandbox(r *http.Request) (web.ApiResponse[*models.Sandbox], *web.ApiError) {
	id := r.PathValue("sandboxID")
	ctx := r.Context()
	log := klog.FromContext(ctx).WithValues("sandboxID", id)
	log.Info("connecting sandbox")

	domain, domainErr := sc.resolveSandboxDomain(r)
	if domainErr != nil {
		return web.ApiResponse[*models.Sandbox]{}, domainErr
	}

	request, apiErr := ParseSetTimeoutRequest(r, sc.maxTimeout)
	if apiErr != nil {
		return web.ApiResponse[*models.Sandbox]{}, apiErr
	}

	sbx, apiErr := sc.getSandboxOfUser(ctx, id)
	if apiErr != nil {
		return web.ApiResponse[*models.Sandbox]{}, apiErr
	}
```

(The rest of the function — `state, pauseResumeReason := sbx.GetState()` onward — is unchanged.)

Update the success return at the bottom of the function to pass the resolved domain:

```go
return web.ApiResponse[*models.Sandbox]{
	Code: statusCode,
	Body: sc.convertToE2BSandbox(sbx, sandboxutils.GetAccessToken(sbx), domain),
}, nil
```

- [ ] **Step 4: Verify tests pass**

```
go test ./pkg/servers/e2b/ -run TestConnectSandbox -v
```

Expected: PASS for the new `TestConnectSandbox_Domain` and the existing `TestConnectSandbox*` family.

- [ ] **Step 5: Commit**

```
git add pkg/servers/e2b/pause_resume.go pkg/servers/e2b/pause_resume_test.go
git commit -m "feat(e2b): resolve ConnectSandbox response domain before resume"
```

---

## Task 9: Wire `ListSandboxes` through the dynamic resolver

**Files:**
- Modify: `pkg/servers/e2b/list.go`
- Modify: `pkg/servers/e2b/list_test.go`

- [ ] **Step 1: Write the failing test**

Append to `pkg/servers/e2b/list_test.go`:

```go
func TestListSandboxes_Domain(t *testing.T) {
	controller, _, teardown := Setup(t)
	defer teardown()
	controller.domain = ""

	user := &models.CreatedTeamAPIKey{
		ID:   keys.AdminKeyID,
		Key:  InitKey,
		Name: "test-user",
	}
	templateName := "list-domain-template"
	cleanup := CreateSandboxPool(t, controller, templateName, 2)
	defer cleanup()

	for i := 0; i < 2; i++ {
		_, createErr := controller.CreateSandbox(NewRequest(t, nil, models.NewSandboxRequest{
			TemplateID: templateName,
			Metadata: map[string]string{
				models.ExtensionKeySkipInitRuntime: v1alpha1.True,
			},
		}, nil, user))
		require.Nil(t, createErr)
	}

	req := NewRequest(t, nil, nil, nil, user)
	req.Host = "api.list.example.com"
	resp, apiErr := controller.ListSandboxes(req)
	require.Nil(t, apiErr)
	require.NotEmpty(t, resp.Body)
	for _, sbx := range resp.Body {
		assert.Equal(t, "list.example.com", sbx.Domain)
	}
}
```

The test file already imports `keys`, `models`, and `v1alpha1`; ensure `github.com/stretchr/testify/require` is imported (add if missing).

- [ ] **Step 2: Run to verify failure**

```
go test ./pkg/servers/e2b/ -run TestListSandboxes_Domain -v
```

Expected: FAIL — entries carry the static `Setup` default domain.

- [ ] **Step 3: Resolve once before the conversion loop**

Edit `pkg/servers/e2b/list.go`. Inside `ListSandboxes`, immediately after the empty-user guard and before `request := ListSandboxesRequest{ ... }`, insert:

```go
domain, apiErr := sc.resolveSandboxDomain(r)
if apiErr != nil {
	return web.ApiResponse[[]*models.Sandbox]{}, apiErr
}
```

Replace the prior `domain := sc.domain` line (introduced in Task 2) before the conversion loop. The loop body becomes:

```go
e2bSandboxes := make([]*models.Sandbox, 0, len(sandboxes))
for _, sbx := range sandboxes {
	e2bSandboxes = append(e2bSandboxes, sc.convertToE2BSandbox(sbx, "", domain))
}
```

- [ ] **Step 4: Verify tests pass**

```
go test ./pkg/servers/e2b/ -run TestListSandboxes -v
```

Expected: PASS for the new `TestListSandboxes_Domain` and the existing `TestListSandboxes*` family.

- [ ] **Step 5: Commit**

```
git add pkg/servers/e2b/list.go pkg/servers/e2b/list_test.go
git commit -m "feat(e2b): resolve ListSandboxes response domain per request"
```

---

## Task 10: Wire `BrowserUse` (URL shape split + dynamic resolver)

**Files:**
- Modify: `pkg/servers/e2b/services.go`
- Modify: `pkg/servers/e2b/services_test.go`

- [ ] **Step 1: Write the failing test**

Append to `pkg/servers/e2b/services_test.go`:

```go
func TestBrowserUse_DomainAndShape(t *testing.T) {
	controller, _, teardown := Setup(t)
	defer teardown()
	controller.domain = ""

	user := &models.CreatedTeamAPIKey{
		ID:   keys.AdminKeyID,
		Key:  InitKey,
		Name: "test-user",
	}
	templateName := "browseruse-shape-template"
	cleanup := CreateSandboxPool(t, controller, templateName, 1)
	defer cleanup()

	createReq := NewRequest(t, nil, models.NewSandboxRequest{
		TemplateID: templateName,
		Metadata: map[string]string{
			models.ExtensionKeySkipInitRuntime: v1alpha1.True,
		},
	}, nil, user)
	createReq.Host = "api.create.example.com"
	createResp, createErr := controller.CreateSandbox(createReq)
	require.Nil(t, createErr)
	sandboxID := createResp.Body.SandboxID

	fakeBody := `{"Browser":"Chrome","Protocol-Version":"1.3","User-Agent":"Test","V8-Version":"12.0","WebKit-Version":"537.36","webSocketDebuggerUrl":"ws://127.0.0.1:9222/devtools/browser/abc"}`
	origRequest := proxyutils.DefaultRequestFunc
	t.Cleanup(func() { proxyutils.DefaultRequestFunc = origRequest })

	tests := []struct {
		name        string
		host        string
		path        string
		wantSnippet string
		wantStatus  int
		expectError string
		expectProxy bool
	}{
		{
			name:        "native shape uses subdomain",
			host:        "api.use.example.com",
			path:        "/sandboxes/" + sandboxID + "/browser",
			wantSnippet: "wss://9222-" + sandboxID + ".use.example.com",
			wantStatus:  http.StatusOK,
			expectProxy: true,
		},
		{
			name:        "customized shape uses path",
			host:        "gateway.example.com",
			path:        "/kruise/api/browser/" + sandboxID,
			wantSnippet: "wss://gateway.example.com/kruise/" + sandboxID + "/9222",
			wantStatus:  http.StatusOK,
			expectProxy: true,
		},
		{
			name:        "empty host returns 500 and does not proxy",
			host:        "",
			path:        "/sandboxes/" + sandboxID + "/browser",
			wantStatus:  http.StatusInternalServerError,
			expectError: "empty host",
			expectProxy: false,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			proxyCalled := false
			proxyutils.DefaultRequestFunc = func(ctx context.Context, sbx *v1alpha1.Sandbox, method, path string, port int, body io.Reader) (*http.Response, error) {
				proxyCalled = true
				return &http.Response{
					StatusCode: http.StatusOK,
					Body:       io.NopCloser(strings.NewReader(fakeBody)),
				}, nil
			}

			req := NewRequest(t, nil, nil, map[string]string{"sandboxID": sandboxID}, user)
			req.Host = tt.host
			req.URL.Path = tt.path

			resp, apiErr := controller.BrowserUse(req)
			assert.Equal(t, tt.expectProxy, proxyCalled, "upstream proxy invocation mismatch")
			if tt.expectError != "" {
				require.NotNil(t, apiErr)
				assert.Equal(t, tt.wantStatus, apiErr.Code)
				assert.Contains(t, apiErr.Message, tt.expectError)
				return
			}
			require.Nil(t, apiErr)
			assert.Equal(t, tt.wantStatus, resp.Code)
			require.NotNil(t, resp.Body)
			assert.Contains(t, resp.Body.WebSocketDebuggerURL, tt.wantSnippet)
		})
	}
}
```

- [ ] **Step 2: Run to verify failure**

```
go test ./pkg/servers/e2b/ -run TestBrowserUse_DomainAndShape -v
```

Expected: FAIL — customized shape returns a native subdomain URL; empty-host case proxies upstream and returns 200.

- [ ] **Step 3: Wire the resolver and split URL builder**

Edit `pkg/servers/e2b/services.go`. Replace the body of `BrowserUse`:

```go
func (sc *Controller) BrowserUse(r *http.Request) (web.ApiResponse[*browserHandShake], *web.ApiError) {
	sandboxID := r.PathValue("sandboxID")

	domain, resolveErr := sc.resolveSandboxDomain(r)
	if resolveErr != nil {
		return web.ApiResponse[*browserHandShake]{}, resolveErr
	}

	cdpPort, apiErr := parseCDPPort(r)
	if apiErr != nil {
		return web.ApiResponse[*browserHandShake]{}, apiErr
	}
	sbx, apiErr := sc.getSandboxOfUser(r.Context(), sandboxID)
	if apiErr != nil {
		return web.ApiResponse[*browserHandShake]{}, apiErr
	}

	resp, err := sbx.Request(r.Context(), r.Method, "/json/version", cdpPort, r.Body)
	if err != nil {
		return web.ApiResponse[*browserHandShake]{}, &web.ApiError{
			Message: fmt.Sprintf("Failed to proxy request to sandbox port %d: %v", cdpPort, err),
		}
	}
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return web.ApiResponse[*browserHandShake]{}, &web.ApiError{
			Message: fmt.Sprintf("Failed to read response body: %v", err),
		}
	}
	var h browserHandShake
	if err = json.Unmarshal(body, &h); err != nil {
		return web.ApiResponse[*browserHandShake]{}, &web.ApiError{
			Message: fmt.Sprintf("Failed to unmarshal response body: %v", err),
		}
	}

	var sandboxAddr string
	if sc.isCustomizedRequest(r) {
		sandboxAddr = managerutils.GetCustomizedSandboxAddress(sandboxID, domain, int32(cdpPort))
	} else {
		sandboxAddr = managerutils.GetSandboxAddress(sandboxID, domain, int32(cdpPort))
	}
	h.WebSocketDebuggerURL = browserWebSocketReplacer.ReplaceAllString(h.WebSocketDebuggerURL,
		fmt.Sprintf("wss://%s", sandboxAddr))
	return web.ApiResponse[*browserHandShake]{
		Code: resp.StatusCode,
		Body: &h,
	}, nil
}
```

- [ ] **Step 4: Verify tests pass**

```
go test ./pkg/servers/e2b/ -run TestBrowserUse -v
```

Expected: PASS for new `TestBrowserUse_DomainAndShape` and the existing `TestBrowserUseCDPPort` (which uses the configured static `controller.domain` plus a native path, so its URL still matches the native builder).

- [ ] **Step 5: Commit**

```
git add pkg/servers/e2b/services.go pkg/servers/e2b/services_test.go
git commit -m "feat(e2b): BrowserUse picks native/customized URL shape and resolves domain"
```

---

## Task 11: Flip `--e2b-domain` default to empty

**Files:**
- Modify: `cmd/sandbox-manager/main.go`

- [ ] **Step 1: Update the flag registration**

Edit `cmd/sandbox-manager/main.go`. Find:

```go
pflag.StringVar(&domain, "e2b-domain", "localhost", "E2B domain")
```

Replace with:

```go
pflag.StringVar(&domain, "e2b-domain", "",
	"Static E2B domain. When empty, the domain is resolved per-request from "+
		"the HTTP Host header (api. prefix stripped for native paths; host "+
		"preserved for /kruise/* customized paths).")
```

- [ ] **Step 2: Compile-check**

```
go vet ./cmd/sandbox-manager/...
```

Expected: no errors.

- [ ] **Step 3: Run e2b package tests**

```
go test ./pkg/servers/e2b/ -count=1
```

Expected: PASS — `main.go` change does not affect the test package.

- [ ] **Step 4: Commit**

```
git add cmd/sandbox-manager/main.go
git commit -m "feat(sandbox-manager): default --e2b-domain to empty for dynamic resolution"
```

---

## Task 12: Update kustomize manifests

**Files:**
- Modify: `config/sandbox-manager/deployment.yaml`
- Modify: `config/sandbox-manager/configuration_patch.yaml`

- [ ] **Step 1: Drop the `--e2b-domain` argument from `deployment.yaml`**

Edit `config/sandbox-manager/deployment.yaml`. Find:

```yaml
            - --kube-client-burst=30000
            - --e2b-domain=replace.with.your.domain
            - --e2b-admin-key=some-api-key
```

Replace with (drop the `--e2b-domain` line):

```yaml
            - --kube-client-burst=30000
            - --e2b-admin-key=some-api-key
```

- [ ] **Step 2: Drop the domain patch and renumber the admin-key patch path**

Replace the entire contents of `config/sandbox-manager/configuration_patch.yaml` with:

```yaml
# E2B API Key (now configured via command line args)
- op: replace
  path: /spec/template/spec/containers/0/args/6
  value: --e2b-admin-key=some-api-key
```

- [ ] **Step 3: Sanity-check kustomize build**

```
kubectl kustomize config/sandbox-manager/ > /tmp/kustomize-build.yaml
```

Expected: exit 0.

```
grep -- "--e2b-domain" /tmp/kustomize-build.yaml; echo "exit=$?"
```

Expected: prints `exit=1` (grep finds nothing).

```
grep -- "--e2b-admin-key=some-api-key" /tmp/kustomize-build.yaml
```

Expected: matches the line in the deployment args.

```
rm /tmp/kustomize-build.yaml
```

- [ ] **Step 4: Commit**

```
git add config/sandbox-manager/deployment.yaml config/sandbox-manager/configuration_patch.yaml
git commit -m "build(manifests): drop --e2b-domain so default deploy uses dynamic resolution"
```

---

## Task 13: Update `use-e2b.md` for the new default

**Files:**
- Modify: `docs/best-practices/use-e2b.md`

- [ ] **Step 1: Rewrite the `E2B_DOMAIN` note**

Edit `docs/best-practices/use-e2b.md`. Find:

```markdown
## Important Notes on E2B_DOMAIN Environment Variable

**VERY IMPORTANT**: The `E2B_DOMAIN` environment variable of sandbox-manager must be set to the same as the client.
You can edit the deployment with `kubectl edit deploy -n sandbox-system sandbox-manager`
```

Replace with:

```markdown
## Important Notes on the `--e2b-domain` Flag

By default (`--e2b-domain` unset or empty), sandbox-manager derives the
response `domain` field from the inbound HTTP `Host` header on every request:

- Native paths (e.g. `api.example.com/sandboxes`): a leading `api.` segment
  is stripped and the host is lowercased, yielding `example.com`.
- Customized paths (e.g. `gateway.example.com/kruise/api/sandboxes`): the
  host is echoed verbatim, yielding `gateway.example.com`.

With this default, the client and server no longer need to share the same
`E2B_DOMAIN` value — the client controls the response by choosing the Host
it sends.

Explicitly set `--e2b-domain=<value>` only when:

1. The client must reach sandboxes on a host different from the API host
   (e.g., separate API and data planes).
2. A reverse proxy rewrites the upstream `Host` header to an internal value
   that the client cannot reach.
3. You are using the port-forward scenario in §4 below and want responses
   to advertise `localhost`.
```

- [ ] **Step 2: Add the port-forward note**

In the same file, find the §4 ("Port forward sandbox-manager to local machine") section. After the last step in that section (after the `patch_e2b(https=False)` snippet), append:

```markdown
> **Note:** Set `--e2b-domain=localhost` in your kustomization overlay if you
> want responses to advertise `localhost`. Without it, the dynamic resolver
> echoes `127.0.0.1` (the port-forwarded Host), which most E2B clients also
> handle but does not match the historical literal-`localhost` behavior.
```

- [ ] **Step 3: Commit**

```
git add docs/best-practices/use-e2b.md
git commit -m "docs(best-practices): describe new --e2b-domain dynamic default"
```

---

## Task 14: Final verification

- [ ] **Step 1: Run the e2b package test suite**

```
go test ./pkg/servers/e2b/... -count=1
```

Expected: PASS.

- [ ] **Step 2: Run the utils package tests**

```
go test ./pkg/utils/sandbox-manager/ -count=1
```

Expected: PASS.

- [ ] **Step 3: Build the sandbox-manager binary**

```
go build -o /tmp/sandbox-manager-verify ./cmd/sandbox-manager/
rm /tmp/sandbox-manager-verify
```

Expected: build succeeds (binary produced and removed).

- [ ] **Step 4: Confirm git history matches the task sequence**

```
git log --oneline feature/remove-e2b-domain-260527 -n 16
```

Expected: the latest 14 commits correspond, in order, to Tasks 1–13 plus this final verification (no commit for Task 14 unless verification turned up an issue that required a fix); the two earlier commits are the design docs (`docs(spec): add ...` and `docs(spec): cover ...`).
