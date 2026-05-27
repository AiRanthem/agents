# Dynamic Sandbox Domain Resolution Design

## Context

The E2B Sandbox response body carries a `domain` field that clients use to
construct sandbox-side URLs such as `wss://{port}-{sandboxID}.{domain}`. Today,
`sandbox-manager` fills this field from a single `--e2b-domain` startup flag
(default `localhost`). A single `sandbox-manager` fronting multiple user-facing
hostnames (e.g., `api.foo.com` and `api.bar.com`) cannot return the host the
client actually used.

This design adds per-request dynamic domain resolution while keeping
`--e2b-domain` as a static override, so single-domain deployments are
unaffected.

The two deployment shapes the resolver must cover (see
`docs/best-practices/use-e2b.md`):

| Shape | API host / path | Sandbox URL pattern |
|---|---|---|
| Native | `api.X` (subdomain) | `<port>-<sid>.X` |
| Customized | `X/kruise/api/...` (path prefix) | `X/kruise/<sid>/<port>` |

`BrowserUse` returns a websocket URL that points at the sandbox, so its URL
shape must follow the same native vs. customized split.

## Goals

- Return a `domain` derived from the current HTTP request when no static
  `--e2b-domain` is configured.
- Preserve `--e2b-domain` as a static override that bypasses dynamic
  resolution. Deployments that explicitly set the flag must keep working
  bit-for-bit.
- Cover both deployment shapes (native and customized) for both the response
  `domain` field and the `BrowserUse` websocket URL.
- Keep `pkg/proxy` and `pkg/servers/e2b/adapters` unchanged. Domain
  resolution is a Controller-layer concern; the adapter only provides
  `ParseRequest` as a parsing utility.
- Make the default `make deploy-sandbox-manager` path produce a deployment
  that uses dynamic resolution out of the box; manifests must not contradict
  the new default.

## Non-Goals

- Do not trust `X-Forwarded-Host`. Reverse-proxy support requires an explicit
  trust / allowlist config and is left for a follow-up PR.
- Do not persist `domain` anywhere on the Sandbox CR, annotations, labels,
  or runtime state.
- Do not change the `proxy.RequestAdapter` interface or the
  `adapters.E2BAdapter` public surface.

## Resolution Rules

When a handler is about to return a `models.Sandbox` (or wires a sandbox URL
into a response, as `BrowserUse` does), the Controller derives the domain as
follows:

1. If `sc.domain` (set from `--e2b-domain`) is non-empty, return it as is.
2. If `sc.requestAdapter` is nil (defensive guard for non-standard
   construction; should not happen after `NewController`), return HTTP 500
   with `sandbox-manager misconfigured: request adapter not initialized`.
3. Build the headers map `{":path": r.URL.Path, "host": r.Host}` and call
   `sc.requestAdapter.ParseRequest` to obtain a `ParsedRequest`.
4. If `parsed.Authority` is empty, return HTTP 500 with
   `cannot resolve sandbox domain: empty host`.
5. If `parsed.Path` starts with `adapters.CustomPrefix` (`/kruise`), the
   customized adapter is in use. Return `parsed.Authority` unchanged — host
   case is preserved because customized routing is path-based, and the
   response must echo the client's request host verbatim.
6. Otherwise (native adapter shape):
   1. Split `host[:port]` on the last colon (no colon → port is empty).
   2. Lowercase `host` (DNS labels are case-insensitive, RFC 4343). The port
      is preserved as written.
   3. Strip a leading `api.` segment from the lowercased `host`. Only a
      literal `api.` segment is stripped, because the dot is part of the
      prefix; `apiserver.example.com` does not match.
   4. Rejoin `host` and `port` (omitting `:` when port is empty).

Without case normalization, a client request to `API.example.com` would
yield response `API.example.com`. The constructed sandbox subdomain
`<port>-<sid>.API.example.com` would then diverge from the actual
(lowercased) DNS name; this confuses TLS SNI validation and some clients.

### Native Examples

| Input `r.Host` | Output |
|---|---|
| `api.example.com` | `example.com` |
| `api.example.com:8443` | `example.com:8443` |
| `API.example.com` | `example.com` |
| `API.example.com:8443` | `example.com:8443` |
| `example.com` | `example.com` |
| `localhost:7788` | `localhost:7788` |
| `apiserver.example.com` | `apiserver.example.com` |
| `""` | HTTP 500 |

### Customized Examples

| Input `r.Host` | `r.URL.Path` | Output |
|---|---|---|
| `gateway.example.com` | `/kruise/api/sandboxes` | `gateway.example.com` |
| `api.gateway.example.com` | `/kruise/api/sandboxes` | `api.gateway.example.com` |
| `Gateway.example.com` | `/kruise/api/sandboxes` | `Gateway.example.com` |
| `""` | `/kruise/api/sandboxes` | HTTP 500 |

## BrowserUse Websocket Shape

`BrowserUse` (`pkg/servers/e2b/services.go`) returns a websocket debugger
URL that points at the sandbox. The URL shape depends on the deployment
style of the inbound request:

- Native request (path does not start with `/kruise`):
  `wss://<port>-<sid>.<domain>`
- Customized request (path starts with `/kruise`):
  `wss://<domain>/kruise/<sid>/<port>`

This requires:

- A second URL builder for the customized shape. Add
  `GetCustomizedSandboxAddress(sandboxID, domain string, port int32) string`
  in `pkg/utils/sandbox-manager/e2b.go`. The existing `GetSandboxAddress`
  keeps the native shape unchanged.
- A small Controller helper `isCustomizedRequest(r *http.Request) bool` that
  returns `strings.HasPrefix(r.URL.Path, adapters.CustomPrefix)` — the same
  check used inside `resolveSandboxDomain`.
- `BrowserUse` picks the address builder based on `isCustomizedRequest(r)`.

Without this split, customized deployments today silently return a
non-routable native-style URL — a latent bug that this design fixes.

## Code Changes

### `pkg/servers/e2b/core.go`

`Controller` gains `requestAdapter proxy.RequestAdapter`. The adapter is
constructed inside `NewController` rather than `Init()`, so any code path
that does not call `Init()` — notably `core_test.go::Setup` — still receives
a usable adapter:

```go
func NewController(...) *Controller {
    sc := &Controller{
        // ...existing fields...
        requestAdapter: adapters.DefaultAdapterFactory(port),
    }
    // ...
}

func (sc *Controller) Init() error {
    // ...
    sandboxManager, err := sandboxmanager.NewSandboxManagerBuilder(sc.sandboxManagerOptions()).
        WithSandboxInfra().
        WithMemberlistPeers().
        WithRequestAdapter(sc.requestAdapter).
        Build()
    // ...
}
```

The field type stays at the `proxy.RequestAdapter` interface because the
Controller only consumes `ParseRequest`.

### `pkg/servers/e2b/sandbox.go`

- Add `resolveSandboxDomain(r *http.Request) (string, *web.ApiError)`
  implementing the rules above. Empty-host and nil-adapter both surface as
  `*web.ApiError` with `Code: http.StatusInternalServerError`.
- Add `splitHostPort(authority string) (host, port string)` as a local
  helper: split on the last `:`; return `(authority, "")` when no colon is
  present. `net.SplitHostPort` is rejected because it errors on inputs like
  `example.com` (no port), which is a normal case here.
- Add `isCustomizedRequest(r *http.Request) bool` returning
  `strings.HasPrefix(r.URL.Path, adapters.CustomPrefix)`.
- Change `convertToE2BSandbox` to
  `func (sc *Controller) convertToE2BSandbox(sbx infra.Sandbox, accessToken, domain string) *models.Sandbox`.
  The body uses the `domain` parameter instead of `sc.domain`; no other
  change.

### `pkg/utils/sandbox-manager/e2b.go`

Add a customized-shape builder alongside the existing native builder:

```go
// GetSandboxAddress returns the native E2B subdomain address:
// "<port>-<sid>.<domain>".
func GetSandboxAddress(sandboxId, domain string, port int32) string {
    return fmt.Sprintf("%d-%s.%s", port, sandboxId, domain)
}

// GetCustomizedSandboxAddress returns the customized path-style address:
// "<domain>/kruise/<sid>/<port>".
func GetCustomizedSandboxAddress(sandboxId, domain string, port int32) string {
    return fmt.Sprintf("%s/kruise/%s/%d", domain, sandboxId, port)
}
```

### Handler Call Sites

For every handler that produces a `models.Sandbox` or a sandbox URL,
`resolveSandboxDomain` is invoked **before any state mutation** (claim,
clone, resume, timeout update, or upstream proxy request). This ensures an
empty-host request never leaves a half-created or resumed sandbox behind.

| File | Handler / Helper | Change |
|---|---|---|
| `create.go` | `CreateSandbox` | Resolve domain at the top; bail with 500 before `ClaimSandbox` / `CloneSandbox` runs. Pass `domain` to `createSandboxWithClaim` / `createSandboxWithClone`. |
| `create.go` | `createSandboxWithClaim` | Accept new `domain string` parameter; forward to `convertToE2BSandbox`. |
| `create.go` | `createSandboxWithClone` | Accept new `domain string` parameter; forward to `convertToE2BSandbox`. |
| `services.go` | `DescribeSandbox` | Resolve domain, pass to `convertToE2BSandbox`. |
| `services.go` | `BrowserUse` | Resolve domain at the top (bail 500 before proxying to the sandbox). Branch on `isCustomizedRequest(r)` to pick `GetSandboxAddress` (native) or `GetCustomizedSandboxAddress`. |
| `list.go` | `ListSandboxes` | Resolve once before the conversion loop; reuse for every entry. |
| `pause_resume.go` | `ConnectSandbox` | Resolve domain at the top; bail with 500 before `ResumeSandbox` / `updateConnectTimeout` runs. Pass to `convertToE2BSandbox`. |

### `cmd/sandbox-manager/main.go`

Flip the flag default and update the help string:

```go
pflag.StringVar(&domain, "e2b-domain", "",
    "Static E2B domain. When empty, the domain is resolved per-request from "+
        "the HTTP Host header (api. prefix stripped for native paths; host "+
        "preserved for /kruise/* customized paths).")
```

### Manifest Updates

Without these, the default `make deploy-sandbox-manager` path would still
inject a non-empty `--e2b-domain` and short-circuit the new logic.

**`config/sandbox-manager/deployment.yaml`** — remove the
`--e2b-domain=replace.with.your.domain` argument (currently at args
index 6). Every argument after it shifts left by one. The new args layout:

```yaml
args:
  - -v=7                              # 0
  - --zap-log-level=7                 # 1
  - --system-namespace=sandbox-system # 2
  - --peer-selector=...               # 3
  - --kube-client-qps=10000           # 4
  - --kube-client-burst=30000         # 5
  - --e2b-admin-key=some-api-key      # 6 (was 7)
  - --e2b-enable-auth=true            # 7 (was 8)
  - --e2b-max-timeout=2592000         # 8 (was 9)
```

**`config/sandbox-manager/configuration_patch.yaml`** — remove the
`--e2b-domain` patch entry entirely. Update the `--e2b-admin-key` patch
path to match the shifted index:

```yaml
# E2B API Key (now configured via command line args)
- op: replace
  path: /spec/template/spec/containers/0/args/6
  value: --e2b-admin-key=some-api-key
```

Operators who still want the previous `localhost` behavior (e.g., the
port-forward scenario in `use-e2b.md` §4) add their own overlay setting
`--e2b-domain=localhost`. The documentation update spells this out.

**`config/sandbox-manager/ingress_patch.yaml`** — unchanged. It configures
ingress host names (a deployment-level concern), not the sandbox-manager
process.

**`docs/best-practices/use-e2b.md`** — update the "E2B_DOMAIN" section to
describe the new default:

- Without `--e2b-domain`, the response `domain` field follows the inbound
  request `Host` header (subject to the resolution rules above), and the
  client and server no longer need to share a `E2B_DOMAIN` env var.
- Explicitly setting `--e2b-domain` is still useful when (a) the client
  must reach sandboxes on a different host than the API host, (b) a reverse
  proxy rewrites the upstream `Host` header to an internal value, or
  (c) the port-forward scenario in §4 needs to advertise `localhost`.

### `pkg/proxy` and `pkg/servers/e2b/adapters`

No changes.

## Error Handling

- Empty `r.Host` (no fallback static domain): HTTP 500 with
  `cannot resolve sandbox domain: empty host`. The 500 is returned before
  any state-mutating operation runs.
- `nil` `sc.requestAdapter` (defensive guard): HTTP 500 with
  `sandbox-manager misconfigured: request adapter not initialized`.
- `X-Forwarded-Host` is not consulted. Reverse proxies that need to
  propagate the inbound host must rewrite the upstream `Host` header.

## Testing

### Unit Tests — `pkg/servers/e2b/sandbox_test.go`

Add `TestResolveSandboxDomain`, table-driven. `sc.requestAdapter` is set to
a real `adapters.NewE2BAdapter(0)` so the test exercises the full
`ParseRequest` path. Cases mirror the resolution tables plus the static
override and case-insensitivity:

| name | sc.domain | r.Host | r.URL.Path | expect (string) | expectError |
|---|---|---|---|---|---|
| static configured wins | `example.com` | `api.foo.com` | `/sandboxes` | `example.com` | `""` |
| native strip api with port | `""` | `api.example.com:8443` | `/sandboxes` | `example.com:8443` | `""` |
| native strip api no port | `""` | `api.example.com` | `/sandboxes` | `example.com` | `""` |
| native strip uppercase api | `""` | `API.example.com` | `/sandboxes` | `example.com` | `""` |
| native strip uppercase with port | `""` | `API.example.com:8443` | `/sandboxes` | `example.com:8443` | `""` |
| native no api prefix | `""` | `example.com` | `/sandboxes` | `example.com` | `""` |
| native localhost with port | `""` | `localhost:7788` | `/sandboxes` | `localhost:7788` | `""` |
| native apiserver not stripped | `""` | `apiserver.example.com` | `/sandboxes` | `apiserver.example.com` | `""` |
| customized host as-is | `""` | `gateway.example.com` | `/kruise/api/sandboxes` | `gateway.example.com` | `""` |
| customized api host not stripped | `""` | `api.gateway.example.com` | `/kruise/api/sandboxes` | `api.gateway.example.com` | `""` |
| customized case preserved | `""` | `Gateway.example.com` | `/kruise/api/sandboxes` | `Gateway.example.com` | `""` |
| empty host returns 500 | `""` | `""` | `/sandboxes` | — | `empty host` |

The `expectError` column follows the project convention (empty string = no
error, non-empty = `assert.Contains(err.Message, expectError)`).

Add `TestIsCustomizedRequest`, table-driven: native path returns `false`,
`/kruise/...` returns `true`, empty path returns `false`.

### Integration Tests

Every response-affecting handler gets coverage for: static configured,
dynamic resolution success, and dynamic resolution failure. The failure
rows additionally assert that no state mutation occurred — implemented by
counting mock-manager calls on `ClaimSandbox`, `CloneSandbox`,
`ResumeSandbox`, etc.

| Test file | Handler | Added cases |
|---|---|---|
| `services_test.go` | `DescribeSandbox` | static → body `Domain` matches configured; dynamic success → body `Domain` matches resolved; empty host → 500 |
| `create_test.go` | `CreateSandbox` (claim path) | dynamic success → body `Domain` matches; empty host → 500 **and** `ClaimSandbox` was not invoked |
| `create_test.go` | `CreateSandbox` (clone path) | empty host → 500 **and** `CloneSandbox` was not invoked |
| `pause_resume_test.go` | `ConnectSandbox` | dynamic success → body `Domain` matches; empty host → 500 **and** `ResumeSandbox` / sandbox timeout writes were not invoked |
| `list_test.go` | `ListSandboxes` | dynamic success → every returned entry's `Domain` matches the resolved value |
| `services_test.go` | `BrowserUse` | native path → URL is `wss://<port>-<sid>.<domain>`; customized path (`/kruise/api/browser/...`) → URL is `wss://<domain>/kruise/<sid>/<port>`; empty host → 500 **and** no upstream request was sent to the sandbox |

Each test uses `httptest.NewRequest` with an explicit `req.Host` and an
`r.URL.Path` consistent with the shape under test. The "no state mutation
on 500" assertions are the central regression guard for P2.

### Adapter Package

Unchanged. The existing adapter tests cover `ParseRequest`, which is all
the Controller depends on.

## Compatibility

- Deployments that explicitly set `--e2b-domain=<value>` keep the previous
  behavior bit-for-bit.
- The flag default flips from `localhost` to `""`, and the standard
  manifests no longer inject a hard-coded value. Fresh
  `make deploy-sandbox-manager` deployments default to dynamic resolution.
- Operators currently relying on the patched `--e2b-domain=localhost`
  default (`use-e2b.md` §4 port-forward scenario) keep working by
  explicitly setting `--e2b-domain=localhost` in their own overlay; the
  documentation update spells this out.
- Customized-shape `BrowserUse` was previously returning a native-style URL
  even in customized deployments — a latent bug. After this change the
  returned URL matches the actually reachable address. Captured in the
  changelog under behavioral fixes.
- No CRD, annotation, label, or runtime state is added or read.

## Implementation Order

1. Add `GetCustomizedSandboxAddress` to `pkg/utils/sandbox-manager/e2b.go`.
2. Change `convertToE2BSandbox` signature; thread `domain` through every
   handler call site (still using `sc.domain` as the value at this step);
   add `isCustomizedRequest` and split `BrowserUse` URL builder per shape.
   Tests continue to pass.
3. Move adapter construction from `Init()` to `NewController` so
   `sc.requestAdapter` is always non-nil after construction.
4. Implement `resolveSandboxDomain` and `splitHostPort`; switch handlers
   from `sc.domain` to `resolveSandboxDomain(r)`, in every case resolving
   before any mutating call or upstream request.
5. Flip the `--e2b-domain` default to `""` in `main.go`.
6. Update `config/sandbox-manager/deployment.yaml` (drop the args entry)
   and `configuration_patch.yaml` (drop the domain patch, renumber the
   admin-key patch path).
7. Update `docs/best-practices/use-e2b.md` for the new default and the
   cases where `--e2b-domain` is still useful.
8. Add `TestResolveSandboxDomain` and `TestIsCustomizedRequest` in
   `pkg/servers/e2b/sandbox_test.go`.
9. Add integration test rows in `services_test.go`, `create_test.go`,
   `pause_resume_test.go`, and `list_test.go` per the table above.
