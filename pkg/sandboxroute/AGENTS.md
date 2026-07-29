# Sandbox Route

This package defines the shared, protocol-neutral projection and route-state
semantics used by manager and gateway processes.

## Local Invariants

- Use explicit Kubernetes object identity as the authoritative route key.
  Sandbox IDs are opaque active lookup values and must not be reverse-parsed.
- Order replacement and deletion by Kubernetes resource version. Identity
  replacement exposes one active ID, and deletion prevents an older observation
  from restoring the route.
- Retain deletion watermarks for the process lifetime so arbitrarily delayed
  observations remain rejected. TTL, eviction, or any weaker guarantee requires
  an explicit design change.
- Reject malformed or untrusted observations without changing current state.
  Supported producers observe the same Kubernetes cluster.
- Keep projection and mutation semantics identical across every producer and
  process. Preserve non-terminating lifecycle states and leave traffic
  admission to serving components.
- Treat route credentials as sensitive. Never expose them through logs,
  diagnostics, or other observable output.
