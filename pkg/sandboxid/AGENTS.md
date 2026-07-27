# Sandbox ID

Neutral leaf for encode / resolve / assign. Prefix and ID correctness are
owned by callers above this package, not here.

- Do not import API or Manager layers, or encode their policy (gates, length,
  replicas, CLI names, protocol rules).
- `AssignShort` trusts the caller's prefix; do not backfill missing policy.
