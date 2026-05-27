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

## Goals

- Return a `domain` derived from the current HTTP request when no static
  `--e2b-domain` is configured.
- Preserve `--e2b-domain` as a static override that bypasses dynamic
  resolution. Existing single-domain deployments must keep working without
  config changes other than the default value flip.
- Cover the two existing deployment shapes:
  - **Native**: API on `api.X`, sandbox on `{port}-{id}.X`. Returned domain is
    `X` (the `api.` prefix is stripped).
  - **Customized**: API on `X/kruise/api/...`, sandbox on `X/kruise/...`.
    Returned domain is `X` as is (no prefix stripping).
- Keep `pkg/proxy` and `pkg/servers/e2b/adapters` unchanged. Domain resolution
  is a Controller-layer concern; the adapter only provides `ParseRequest` as a
  parsing utility.

## Non-Goals

- Do not trust `X-Forwarded-Host`. Reverse-proxy support requires an explicit
  trust / allowlist config and is left for a follow-up PR.
- Do not persist `domain` anywhere on the Sandbox CR, annotations, labels, or
  runtime state. The value is derived per request and only appears in the API
  response body.
- Do not change the `proxy.RequestAdapter` interface or the
  `adapters.E2BAdapter` public surface.

## Resolution Rules

When a handler is about to return a `models.Sandbox` (or wires a sandbox URL
into a response, as `BrowserUse` does), the Controller derives the domain as
follows:

1. If `sc.domain` (set from `--e2b-domain`) is non-empty, return it as is.
2. Otherwise, build `{":path": r.URL.Path, "host": r.Host}` and call
   `sc.requestAdapter.ParseRequest` to obtain a `ParsedRequest`.
3. If `parsed.Authority` is empty, return HTTP 500
   (`cannot resolve sandbox domain: empty host`).
4. If `parsed.Path` starts with `adapters.CustomPrefix` (`/kruise`), the
   customized adapter is in use. Return `parsed.Authority` unchanged.
5. Otherwise (native adapter shape), split `host[:port]` on the last colon,
   strip a leading `api.` segment from `host`, and rejoin with `port`.

Only a literal `api.` segment is stripped. `apiserver.example.com` is left
untouched because the segment boundary is `api.` followed by another label,
not the substring `api`.

### Native Examples

| Input `r.Host` | Output |
|---|---|
| `api.example.com` | `example.com` |
| `api.example.com:8443` | `example.com:8443` |
| `example.com` | `example.com` |
| `localhost:7788` | `localhost:7788` |
| `apiserver.example.com` | `apiserver.example.com` |
| `""` | HTTP 500 |

### Customized Examples

| Input `r.Host` | `r.URL.Path` | Output |
|---|---|---|
| `gateway.example.com` | `/kruise/api/sandboxes` | `gateway.example.com` |
| `api.gateway.example.com` | `/kruise/api/sandboxes` | `api.gateway.example.com` |
| `""` | `/kruise/api/sandboxes` | HTTP 500 |

## Code Changes

### `pkg/servers/e2b/core.go`

- `Controller` gains `requestAdapter proxy.RequestAdapter`.
- `Init()` stores the adapter built by `adapters.DefaultAdapterFactory(sc.port)`
  into `sc.requestAdapter` before passing the same value to
  `WithRequestAdapter`. The field type stays at the `proxy.RequestAdapter`
  interface because only `ParseRequest` is consumed.

### `pkg/servers/e2b/sandbox.go`

- Add `resolveSandboxDomain(r *http.Request) (string, *web.ApiError)`
  implementing the rules above.
- Add a local helper `splitHostPort(authority string) (host, port string)` that
  splits on the last `:` and returns `(authority, "")` when no colon is
  present. `net.SplitHostPort` is rejected because it errors on inputs like
  `example.com` (no port) and on IPv6 brackets, which add complexity we do not
  need for `r.Host` values.
- Change `convertToE2BSandbox` to
  `func (sc *Controller) convertToE2BSandbox(sbx infra.Sandbox, accessToken, domain string) *models.Sandbox`.
  The body uses the `domain` parameter instead of `sc.domain`. No other change.

### Handler Call Sites

| File | Handler / Helper | Change |
|---|---|---|
| `create.go` | `CreateSandbox` | Resolve once at the top; pass `domain` into `createSandboxWithClaim` / `createSandboxWithClone`. |
| `create.go` | `createSandboxWithClaim` | Accept new `domain string` parameter; forward to `convertToE2BSandbox`. |
| `create.go` | `createSandboxWithClone` | Accept new `domain string` parameter; forward to `convertToE2BSandbox`. |
| `services.go` | `DescribeSandbox` | Resolve domain, pass to `convertToE2BSandbox`. |
| `services.go` | `BrowserUse` | Resolve domain, pass to `managerutils.GetSandboxAddress` (replaces `sc.domain` at line 141). |
| `list.go` | `ListSandboxes` | Resolve once before the conversion loop; reuse the same `domain` for every entry. |
| `pause_resume.go` | `ConnectSandbox` | Resolve domain, pass to `convertToE2BSandbox`. |

### `cmd/sandbox-manager/main.go`

Change the flag default and update the help string:

```go
pflag.StringVar(&domain, "e2b-domain", "",
    "Static E2B domain. When empty, the domain is resolved per-request "+
        "from the HTTP Host header.")
```

### `pkg/proxy` and `pkg/servers/e2b/adapters`

No changes.

## Error Handling

- Empty `r.Host` (no fallback static domain) → HTTP 500 with the message
  `cannot resolve sandbox domain: empty host`. This is the strict failure
  contract requested for the new mode.
- `X-Forwarded-Host` is not consulted. Reverse proxies that need to propagate
  the inbound host must rewrite the upstream `Host` header.

## Testing

### Unit Tests — `pkg/servers/e2b/sandbox_test.go`

Add a new table-driven test `TestResolveSandboxDomain` to the existing file.
The Controller's `requestAdapter` is set to a real `adapters.NewE2BAdapter(0)`
so the test covers the full path through `ParseRequest`. Cases mirror the
resolution rules tables above, plus an integration with the static override:

| name | sc.domain | r.Host | r.URL.Path | expect |
|---|---|---|---|---|
| static configured wins | `example.com` | `api.foo.com` | `/sandboxes` | `example.com` |
| native strip api with port | `""` | `api.example.com:8443` | `/sandboxes` | `example.com:8443` |
| native strip api no port | `""` | `api.example.com` | `/sandboxes` | `example.com` |
| native no api prefix | `""` | `example.com` | `/sandboxes` | `example.com` |
| native localhost with port | `""` | `localhost:7788` | `/sandboxes` | `localhost:7788` |
| native apiserver not stripped | `""` | `apiserver.example.com` | `/sandboxes` | `apiserver.example.com` |
| customized host as-is | `""` | `gateway.example.com` | `/kruise/api/sandboxes` | `gateway.example.com` |
| customized api host not stripped | `""` | `api.gateway.example.com` | `/kruise/api/sandboxes` | `api.gateway.example.com` |
| empty host returns 500 | `""` | `""` | `/sandboxes` | error `empty host` |

`expectError` is a string per the project convention; the empty-host case
asserts `assert.Contains(err.Error(), "empty host")`.

### Integration Test — `pkg/servers/e2b/services_test.go`

Extend `DescribeSandbox` tests with three rows covering response body
`domain`:

| name | sc.domain | request Host | expect |
|---|---|---|---|
| static configured | `example.com` | `api.foo.com` | body `Domain` = `example.com`, status 200 |
| dynamic native success | `""` | `api.foo.com` | body `Domain` = `foo.com`, status 200 |
| dynamic empty host | `""` | `""` | status 500 |

Existing `DescribeSandbox` test fixtures (mocked manager, fake user) are
reused.

### Adapter Package

Unchanged. The existing adapter tests cover `ParseRequest` already, which is
all we depend on.

## Compatibility

- Deployments that explicitly set `--e2b-domain=<value>` keep the previous
  behavior bit-for-bit.
- The flag default flips from `localhost` to `""`. The only effect on
  deployments that previously relied on the default is that the response
  `Domain` becomes the actual request host (with `api.` stripped on native
  paths) instead of the unusable literal `localhost`. Clients that hardcoded
  `localhost` were already non-functional unless they ran on the same machine
  as the sandbox-manager, so this is not a behavioral regression worth
  guarding.
- No CRD, annotation, label, or runtime state is added or read.

## Implementation Order

1. Change `convertToE2BSandbox` signature and update all 6 handler call sites
   to pass `sc.domain` through. Tests still pass; this is a pure mechanical
   refactor.
2. Add `Controller.requestAdapter` field and store the adapter in `Init()`.
3. Implement `resolveSandboxDomain` + `splitHostPort` and switch each handler
   from `sc.domain` to `resolveSandboxDomain(r)`.
4. Flip the `--e2b-domain` default to `""` in `main.go`.
5. Add `pkg/servers/e2b/sandbox_test.go` unit tests for `resolveSandboxDomain`.
6. Extend `pkg/servers/e2b/services_test.go` with the three `DescribeSandbox`
   integration rows.
