# OpenKruise Agents Guide

This file contains repository-wide rules.

## Instruction Scope

- Root rules apply repository-wide; keep durable cross-file or silently critical
  constraints in the deepest applicable `AGENTS.md`, leave details and public
  contracts to their owning code, tests, specifications, or proposals, and
  review changes root-to-leaf before removing guidance.

## Control Plane Layering

### API Layer — sandbox-manager

- The API layer is `pkg/servers/**`, including E2B-compatible protocols.
- It owns routing, transport protocols, request and response models,
  protocol-level validation, authentication and authorization, error and status
  mapping, and compatibility behavior.
- Logic that directly expresses an API protocol contract must remain here. Do
  not push protocol models, HTTP semantics, or compatibility rules into Manager
  or Infra.

### Manager Layer — sandbox-manager

- The Manager layer is `pkg/sandbox-manager/**`, excluding its `infra/**`
  subtree.
- It owns protocol-independent and implementation-independent business rules
  and use-case orchestration, including lifecycle orchestration, quota
  coordination, and admission and release policy.
- It may access underlying capabilities only through neutral Infra interfaces.
  It must not depend on `pkg/servers` or directly implement Kubernetes CRD
  reads and writes.

### Infra Layer — sandbox-manager

- The Infra layer is `pkg/sandbox-manager/infra/**`; concrete Kubernetes
  implementations belong in subpackages such as `infra/sandboxcr`.
- On the sandbox-manager path, concrete Kubernetes clients, caches, CRD queries,
  and CRD mutations must be contained by this layer.
- It exposes protocol-neutral capabilities and data upward. It must not depend
  on API models, HTTP status codes, authentication semantics, or Manager
  business policy.

### Agent Sandbox Controller

- `cmd/agent-sandbox-controller` and `pkg/controller/**` form an independent
  Kubernetes operator.
- The controller's complete dependency closure must not include
  `pkg/servers/**` or `pkg/sandbox-manager/**`. Code shared with
  sandbox-manager must move to a genuinely neutral package; a shared or utility
  package must not hide an indirect reverse dependency.
- Controllers may reconcile CRDs directly, but must not reuse sandbox-manager
  API behavior, business orchestration, or Infra implementations.

### Dependency Rules

- New sandbox-manager dependencies follow `API -> Manager -> Infra`. Do not
  add API-to-Infra shortcuts or lower-to-upper reverse dependencies.
- `pkg/features` is controller-only. Code under `pkg/sandbox-manager/**` and
  `pkg/servers/**` must not import it or consume its gates through a shared
  wrapper.
- For optional sandbox-manager behavior, prefer interface or option parameters
  that control a single call. Avoid package-global or process-global feature
  switches. Add a global switch only when per-call control cannot safely express
  the requirement, and document why global scope is necessary.
- `cmd/*` entrypoints assemble dependencies and start components only; business
  logic belongs in the appropriate layer.
- These rules are normative for new work. Existing cross-layer imports are
  legacy debt, not architectural precedent: do not add to or widen them. If a
  task requires a wider violation, propose a layering refactor first.
- Shared packages must stay policy-neutral and must not import domain-specific
  packages merely to make reuse convenient.

## Sandbox Identity

- A persisted system-owned Sandbox ID is immutable. Operations on the same
  Sandbox preserve it; operations creating a new Sandbox do not inherit it;
  callers and templates cannot set it. Only Manager assignment policy may
  initialize a missing ID.

## Development

- Follow standard Go idioms. Run `gofmt -w` on changed Go files.
- New Go files must use the Apache 2.0 header from
  `hack/boilerplate.go.txt`. Keep code comments in English.
- Prefer table-driven unit tests. Extend a suitable existing table; use a
  standalone test only when no table fits.
- Do not introduce test stubs, fakes, or mocks unless necessary. Prefer
  exercising real implementations or existing test infrastructure first.
- Do not create abstract interfaces or new types unless necessary. Introduce
  an abstraction only when a concrete, current need requires it.
- Test only when needed, using the narrowest changed package or selected test
  (`-run`, `-count=1`). Do not run unrelated tests or repeat stable tests. For
  probabilistic failures, races, or other concurrency risks, rerun the relevant
  test enough times to trust it (`-count=N`, `-race`). `make test` runs the full
  `pkg/...` suite; use `make vet` and `make lint` only when warranted. Never run
  E2E tests for ordinary validation.
- Check cancellation in retrying or long-running work and preserve meaningful
  error context.
- Do not add Prometheus metrics (new collectors, counters, gauges, histograms,
  or instrumentation) unless the user explicitly requests them.

## Generated Files And Design Changes

- Do not edit generated files under `client/`, `proto/`, or `config/crd/`
  directly.
- After changing `api/v1alpha1/`, run `make generate manifests`. Use
  `make generate` or `make manifests` for their respective generated
  outputs.
- New APIs and architectural changes require a proposal in `docs/proposals/`.
- Prefer responsibility-specific package names. Do not create new catch-all
  `utils`, `common`, `helpers`, `util`, or `base` packages.

## Errors And Logging

- Never ignore errors. Classify wrapped errors with `errors.Is` and
  `errors.As`; use Kubernetes API error helpers for Kubernetes errors and
  `client.IgnoreNotFound` only where absence is acceptable.
- Sandbox-manager domain errors belong in
  `pkg/sandbox-manager/errors/`; transport status mapping belongs in the API
  layer.
- Use structured key-value logging. Controllers use
  `logf.FromContext(ctx)`; sandbox-manager code uses
  `klog.FromContext(ctx)`. Do not use `fmt.Println` for runtime logging.

## Repository Hygiene

- Do not remove useful comments unless they are obsolete.
- A new submodule `AGENTS.md` must have a sibling `CLAUDE.md` whose sole
  content is `@./AGENTS.md`.
- Commits must include sign-off, for example `git commit -s`.
