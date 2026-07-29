# Sandbox Manager Infrastructure

This directory defines the protocol-neutral Infra contracts used by the Manager
layer.

## Local Invariants

- Shared contracts expose only implementation-neutral capabilities genuinely
  needed by Manager.
- Inputs and results must not expose backend objects, clients, or caches, or
  encode API, authentication, or Manager policy.
- Concrete backend behavior, resilience, and repair policy belong in
  implementation subpackages.
- Extend a shared interface only for a current cross-implementation need. Keep
  observability data implementation-neutral and safe to serialize.
