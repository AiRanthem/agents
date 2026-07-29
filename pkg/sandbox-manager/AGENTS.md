# Sandbox Manager

This directory implements the Manager layer defined by the repository guide.

## Sandbox Identity

- Manager owns the one-way assignment of a missing Sandbox ID, and assignment
  configuration affects only future assignments.
- Keep rollout, format, and assignment policy here. Shared identity primitives
  and Infra remain policy-neutral.

## Route Orchestration

- Manager composes neutral backend observations into the shared route model; it
  must not maintain a Manager-specific projection or route state machine.
- Preserve the backend observation scope during route ingestion. Apply
  lifecycle and authorization policy only when admitting a request.

## Quota Orchestration

- Manager owns quota orchestration over neutral Infra capabilities. Wire it only
  after those capabilities are available, and do not move its policy into API
  or concrete Infra implementations.
- Release quota only after an accepted sandbox deletion. API-key cleanup is a
  separate Manager operation and must not roll back an already accepted key
  deletion on backend failure.
- Anti-drift mutations are primary-only. Losing primary status must stop the
  active repair cycle.
- Preserve typed quota-exceeded errors and fail-open handling for quota backend
  transport failures. HTTP status mapping remains in the API layer.
