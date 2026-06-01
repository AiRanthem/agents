# CreateSandbox Unlimited Server-Side Timeout Design

## Context

The E2B `CreateSandbox` API (`pkg/servers/e2b/create.go`) applies two server-side
timeouts on the synchronous claim/clone path:

- `ClaimTimeout` (claim path) / `CloneTimeout` (clone path): bounds the whole
  pick + lock + retry loop in `Infra.ClaimSandbox` / `Infra.CloneSandbox`.
- `WaitReadyTimeout`: bounds the post-lock readiness wait in
  `waitForSandboxReady`.

Today these default to finite values when the client does not configure them:

- `DefaultClaimTimeout = time.Minute`, `DefaultCloneTimeout = time.Minute`
  (`pkg/sandbox-manager/infra/sandboxcr/config.go`).
- `DefaultWaitReadyTimeout = 60 * time.Second`
  (`pkg/sandbox-manager/consts/consts.go`).

These defaults are applied inside `ValidateAndInitClaimOptions` /
`ValidateAndInitCloneOptions` whenever the option value is `<= 0`.

Having two server-imposed defaults that interact with the client's own request
deadline has a high explanation cost. We want the default behavior to be "no
server-imposed deadline": the operation runs until it succeeds or the client
cancels the request, while still allowing explicit per-request configuration
through the existing extension metadata.

## Goals

- Default `ClaimTimeout`, `CloneTimeout`, and `WaitReadyTimeout` on the
  `CreateSandbox` path to "effectively unlimited", so the operation is bounded
  only by the client request context (cancellation).
- Keep explicit configuration working through the existing extension metadata
  keys (`e2b.agents.kruise.io/claim-timeout-seconds`,
  `e2b.agents.kruise.io/wait-ready-timeout-seconds`).
- Make the change as small as possible.

## Non-Goals

- Do not change the `SandboxClaim` controller path. The controller builds its
  options and calls `sandboxcr.TryClaimSandbox` directly; its CRD-level
  `ClaimTimeout` / `WaitReadyTimeout` fields and status-based timeout
  (`isClaimTimeout`) keep their current semantics. The controller has no client
  to cancel a hanging reconcile, so it must keep finite defaults.
- Do not change `NewSandboxRequest.Timeout` (the sandbox lifecycle
  auto-shutdown / auto-pause timeout). It is unrelated to these server-side
  timeouts.
- Do not remove the `DefaultClaimTimeout` / `DefaultCloneTimeout` /
  `DefaultWaitReadyTimeout` constants; the controller path still relies on them
  via `ValidateAndInit*Options` when the option is unset (`0`).
- Do not add a global server-side cap. If the HTTP server has its own
  write/idle timeout, that layer still applies and is orthogonal to this change.

## Design

### Approach: represent "unlimited" as a far-future duration

`0` already means "unset → use default" inside `ValidateAndInit*Options`, so
"unlimited" needs a distinct representation. Instead of introducing a negative
sentinel (which would require branching in `context.WithTimeout`, `retrySteps`,
and `pkg/cache/utils/wait.go`), we represent "unlimited" as a single far-future
positive duration.

This is the minimal change because every downstream consumer already handles a
large positive duration correctly:

- `ValidateAndInitClaimOptions` / `ValidateAndInitCloneOptions`: `if x <= 0`
  does not fire for a large positive value, so the value is preserved unchanged.
- `Infra.ClaimSandbox` / `Infra.CloneSandbox`: `context.WithTimeout(ctx, huge)`
  produces a far-future deadline (child of the client `ctx`, so client cancel
  still propagates), and `retrySteps(huge)` returns a large `int` step count
  (no overflow on 64-bit; the retry loop terminates on client cancel via a
  non-retriable error, not on step exhaustion).
- `pkg/cache/utils/wait.go`: `timeout <= 0` (the "skip waiting" branch) does not
  fire; the wait runs with a far-future `context.WithTimeout` deadline plus the
  existing 10s polling ticker, so it ends when the sandbox becomes ready or the
  client cancels.

This also matches the existing repository convention of representing
"indefinitely" as a far-future point in time (pause sets the sandbox shutdown
time ~1000 years out).

The trade-off is that the value is not a literal "no deadline" — it is ~100
years. For any real request this is indistinguishable from unlimited: a client
cancel or a server restart occurs long before. Given the explicit priority on a
minimal change, this is acceptable.

### Constant

Add one package-level constant in `pkg/servers/e2b/create.go`:

```go
// noServerTimeout is used when the server should not impose its own deadline on
// claim/clone/wait-ready. The operation is then bounded only by the client
// request context (cancellation). It is a far-future duration rather than a
// true infinity so that existing timeout handling (context deadlines, retry
// step counts, wait-ready polling) keeps working unchanged. ~100 years is
// indistinguishable from unlimited for any real request.
const noServerTimeout = 100 * 365 * 24 * time.Hour
```

`100 * 365 * 24 * time.Hour` ≈ 3.15e18 ns, well within `time.Duration`'s int64
range (max ≈ 292 years).

### create.go changes

The extension parser (`parseAndRemoveIntExtension`) already returns `0` when the
key is absent or its value is `<= 0`. So `TimeoutSeconds > 0` /
`WaitReadySeconds > 0` cleanly means "explicitly configured to a positive
value".

Claim path (`createSandboxWithClaim`):

- `ClaimTimeout`: currently set unconditionally to
  `time.Duration(request.Extensions.TimeoutSeconds) * time.Second`. Change to:
  if `TimeoutSeconds > 0`, use the finite value; otherwise use `noServerTimeout`.
- `WaitReadyTimeout`: currently set only when `WaitReadySeconds > 0`. Add an
  `else` branch that sets `noServerTimeout`.

Clone path (`createSandboxWithClone`):

- `CloneTimeout`: same treatment as `ClaimTimeout`.
- `WaitReadyTimeout`: same treatment as the claim path.

No other files change. `ValidateAndInit*Options`, `Infra.ClaimSandbox` /
`CloneSandbox`, `retrySteps`, and `pkg/cache/utils/wait.go` are untouched.

### Behavior notes

- Explicit `claim-timeout-seconds` / `wait-ready-timeout-seconds` positive values
  still produce finite timeouts exactly as before.
- An explicitly configured non-positive value (e.g. `0`) is parsed to `0` by the
  extension parser and therefore treated the same as "absent" → unlimited. This
  is an acceptable edge case.

### Resource implications (no worker-pool exhaustion)

With unlimited `WaitReadyTimeout`, the readiness wait does not hold a claim
worker. In `TryClaimSandbox` the worker slot (`claimLockChannel`, capacity
`DefaultClaimWorkers = 500`) is released early — `freeWorkerOnce()` runs
immediately after the sandbox is locked (`claim.go`) and **before**
`waitForSandboxReady`. The worker pool is only occupied during the bounded
pick + lock phase.

Other consequences of the unlimited default:

- A newly created sandbox that never becomes ready will block the request until
  the client cancels, with no automatic retry onto a fresh sandbox (the finite
  `WaitReadyTimeout` previously turned a stuck wait into a `retriableError`).
  This is the explicitly chosen behavior.
- On client cancel, the locked sandbox is still cleaned up: `TryClaimSandbox`'s
  deferred `clearFailedSandbox(ctx, claimed, err, ...)` applies the configured
  `ReserveFailedSandboxFor` policy when the context error surfaces.
- The clone path uses `createLimiter` (a create-QPS rate limiter), not the
  worker pool; its readiness wait holds no limiting resource either.
- The only resource that scales with the number of concurrently hanging
  requests is the usual per-request goroutine, one wait-hook entry, and the
  locked-but-not-ready Sandbox CR — inherent to any client-cancel-bounded long
  request and bounded by client behavior and HTTP server limits.

## Tests

Use table-driven tests in the `e2b` package (alongside the existing create /
services tests).

Add or update tests for:

- Claim option construction: no `claim-timeout-seconds` extension →
  `opts.ClaimTimeout == noServerTimeout`; positive extension → the finite value.
- Claim option construction: no `wait-ready-timeout-seconds` extension →
  `opts.WaitReadyTimeout == noServerTimeout`; positive extension → the finite
  value.
- Clone option construction: same two assertions for `opts.CloneTimeout` and
  `opts.WaitReadyTimeout`.
- Existing create/services tests that relied on the previous finite defaults
  continue to pass (they set explicit short timeouts via metadata where needed,
  so they should be unaffected; verify and adjust only if a test implicitly
  depended on a 60s/1m server default).
