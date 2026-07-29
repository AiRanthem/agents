# Sandbox ID

This package defines shared, policy-neutral Sandbox identity primitives.

- A non-empty persisted identity is authoritative and unchanged; use the legacy
  identity only when no persisted value exists. IDs are opaque and are not
  reverse-parsed or revalidated during reads.
- Keep generation deterministic and collision-resistant from the complete
  Kubernetes object identity.
- Enforce only syntax intrinsic to the encoding. Assignment rollout, timing,
  contextual length, replica configuration, and protocol policy remain in
  upper layers; do not depend on those layers.
