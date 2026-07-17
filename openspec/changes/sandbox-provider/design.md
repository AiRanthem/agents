## Context

`pkg/sandbox-manager/infra/sandboxcr` currently contains both the Manager CR adapter and mechanics
used directly by controller. `TryClaimSandbox` accepts option and result types owned by Manager
infra, imports Manager defaults and logging, calls a Controller SandboxSet constructor, and imports
an E2B model for a CR annotation key. Controller therefore has a forbidden reverse dependency on
Manager merely to execute a Sandbox CR claim.

Gateway has a different problem: it watches Sandbox CRs directly and converts them into routes
outside the Manager adapter. The state-model change needs Manager and Gateway to use exactly the
same CR observation and route mapping without making Gateway import Manager infra.

The repository architecture requires API to call Manager, Manager to call its infra port, concrete
Kubernetes behavior to stay below that port, and controller to have no Manager or server dependency
in its production closure. A shared package must be policy-neutral and responsibility-specific.

## Goals / Non-Goals

**Goals:**

- Give shared Sandbox capabilities and Sandbox CR mechanics one neutral owner.
- Remove controller's claim/runtime dependency on sandbox-manager packages.
- Provide a safe read-only CR observation path for Gateway and a shared claim algorithm over narrow
  component-owned CR backend adapters.
- Move claim options according to responsibility and make policy defaults explicit.
- Preserve normal behavior while establishing dependency and route-deletion safety prerequisites
  for the state-model change.
- Permit future non-CR Sandbox providers without putting CR types in the Manager business contract.

**Non-Goals:**

- Changing lifecycle state values, route actions, normal E2B/claim policy, retry counts, quota
  decisions, timeout defaults, or Route wire fields in this change.
- Moving Manager-only clone, checkpoint, volume, lifecycle orchestration, API errors, or builders
  into the shared provider.
- Making controller consume the manager-oriented eight-state observation.
- Replacing the existing cache, route registry, peer transport, or runtime implementations.
- Adding a CRD field or changing generated clients or manifests.

## Decisions

### 1. Responsibility-specific package split

`pkg/sandboxprovider` is the implementation-neutral contract. It owns the Sandbox capabilities
that cross component boundaries, the manager-oriented state observation type used by provider
implementations, common claim request and result types, explicit defaults, admission callbacks,
resource and update descriptions, and claim metrics.

`pkg/sandboxprovider/sandboxcr` is a policy-neutral Sandbox CR algorithm package. It owns raw CR
interpretation, read-only observation, pool predicates, SandboxSet materialization, CR-specific
claim inputs, the narrow claim backend contract, candidate/claim orchestration, and pure CR
mutation helpers. It does not own concrete Kubernetes clients, caches, informer reads, API-reader
fallbacks, or persisted writes.

The shared packages must not import `pkg/controller`, `pkg/sandbox-manager`, `pkg/servers`,
controller-runtime clients, or the concrete cache package. Neutral data and pure helper dependencies
such as API types, runtime configuration, timeout values, expectations, and the existing route model
are allowed. External reads, writes, waits, runtime calls, identity processing, and cleanup
persistence are backend capabilities implemented by the component adapter.

### 2. Manager infra remains the port and adapter

`pkg/sandbox-manager/infra` continues to define the complete Manager infrastructure port. It refers
to provider-owned Sandbox, option, result, and observation types rather than defining duplicates.

`pkg/sandbox-manager/infra/sandboxcr` remains the Manager CR implementation and assembly location
required by the repository architecture. It owns concrete Kubernetes clients, informer cache and
API-reader access, CR queries and persisted mutations, plus the Manager-only builder, clone,
checkpoint, volume, quota-source, lifecycle mutation, and error translation. It implements the
shared sandboxcr backend contract and delegates only reusable observation and claim orchestration.

The Manager core never receives `agentsv1alpha1.Sandbox`, client, cache, or CR-specific option
extensions. The adapter translates between the neutral Manager port and the CR provider.

### 3. Shared observation is read-only; mutation remains in component adapters

The CR provider exposes a read-only Sandbox view backed only by the observed Sandbox CR. It provides
metadata access plus `GetState` and `GetRoute`; it has no cache, client, or mutation methods.

Manager's mutable CR Sandbox remains in `pkg/sandbox-manager/infra/sandboxcr`, embeds or delegates to
that view, and owns the dependencies required by pause, resume, delete, timeout, runtime,
checkpoint, and CSI operations. Gateway constructs only the read-only view, avoiding a partially
initialized mutable object or nil cache dependency.

CR-to-state derivation remains unexported. `GetState` is the only state observation method, and
`GetRoute` obtains state through that method rather than exposing a second state API. In this
foundation change, GetRoute owns the current legacy projection and the conservative route-safety
filter described below. `sandbox-manager-state-model` later replaces that projection and filter
with the approved observation-to-Action contract.

### 4. Controller uses pool predicates, not manager state

Pool creating and available/claimable classification is not the Manager eight-state model. The CR
provider owns explicit-time pure predicates for those pool facts because they are used by
SandboxSet, cache, claim selection, and later manager claimable derivation.

Controller and cache call those predicates directly. They do not call `GetState` or `GetRoute`.
The provider does not import Controller. The existing pure SandboxSet materialization helper moves
to the provider and Controller calls it from its reconcile path.

This direction keeps controller self-contained while allowing both controller and Manager's CR
adapter to reuse the same low-level CR mechanics.

### 5. Options are split by responsibility

Common claim data lives in `sandboxprovider`: namespace, owner, template, lock identity, candidate
limits, timeouts, create-on-no-stock, speculation, failed-Sandbox retention, admission callbacks,
resource and in-place update intent, runtime and CSI intent, generic mutation hooks, results, lock
classification, and metrics.

CR-specific claim options live in `sandboxprovider/sandboxcr`: originating SandboxClaim,
RuntimeConfig CR values, CR metadata tracking, a narrow backend capability, pick cache, worker
semaphore, create limiter, and other execution controls. Concrete client and cache objects are never
part of these options; they remain encapsulated by the backend implementation in Manager infra or
Controller.

Manager API defaults, controller defaults, quota decisions, authorization, protocol fields, and
public error mapping remain with their callers. The common contract includes an explicit defaults
value, but no provider function imports Manager constants or silently chooses Manager policy.
Validation runs after defaults are resolved and before `TryClaimSandbox` starts side effects.

Existing Manager config aliases for runtime and CSI move to the responsibility-specific shared
runtime/provider types. In-place update options move to the provider contract. Temporary aliases
may be used only within one atomic migration and are removed before completion.

### 6. TryClaimSandbox remains one orchestration over component-owned backends

Controller and the Manager CR adapter both call the shared `TryClaimSandbox`. Manager infra and the
SandboxClaim Controller each implement the CR backend contract using their own legal client/cache
boundary. The shared algorithm preserves candidate ordering, current-revision preference,
speculative creation, create-on-no-stock, resource-version expectations, local pick lock, optimistic
lock sequencing, create limiting, admission acquire/release pairing, readiness waits, runtime
initialization, identity token processing, CSI mounts, metadata recording, failed-Sandbox
reservation/deletion, metrics, context cancellation, and error retry classification.

The backend contract exposes only the CR operations required by one claim attempt: pool listing and
SandboxSet/template lookup, create/update/refresh/delete, readiness wait, runtime and CSI execution,
identity processing, and failed-Sandbox persistence. It returns CR data or protocol-neutral errors;
it does not expose concrete clients, caches, Manager errors, API models, quota decisions, or
Controller reconciliation types.

The operation returns provider/CR errors. Manager maps those errors to its domain error codes, and
Controller keeps its reconciliation behavior. The provider never imports Manager error types or
E2B response models.

The CSI mount annotation key, pure CR mutations, and SandboxSet construction required by both
callers move to a neutral CR-owned location. Persisted I/O remains in each backend adapter. Logs use
standard context-aware Kubernetes logging without Manager log helpers.

### 7. Shared dependencies must remain neutral

The cache package replaces `SandboxManagerOptions` parameters with cache-owned options and uses
neutral logging so Controller's existing cache dependency does not pull Manager into its closure.
Manager startup translates its configuration into cache options. The shared provider does not
import the concrete cache package.

Controller runtime/CSI code imports the existing shared runtime configuration directly. Constants
used only by SandboxSet remain local to Controller; values required by claim execution are supplied
through provider defaults. Unrelated legacy Gateway configuration debt is not expanded by this
change.

### 8. Legacy routing gains the compatibility safety baseline

The later state-model can change Route Action when local time crosses shutdown time without a CR
resource-version update. Before that change is enabled, every route receiver needs a non-forwarding
deletion tombstone and every old-format producer needs a conservative definition of legacy
`running`.

This prerequisite changes route stores so delete accepts Sandbox UID and resource version, removes
the active entry, and retains only the deletion decision metadata. An update for the same UID with
an equal or older resource version is rejected even though no active route exists. A strictly newer
resource version for the same UID or a different UID for a reused route ID can replace the tombstone.

In-memory tombstones are not treated as durable history. Each receiver maintains an authoritative
local Sandbox observation from its informer/cache and remains non-ready for peer route mutation and
data-plane forwarding until that cache has synchronized. At startup it derives the current route
decision for every observed Sandbox through GetRoute. A peer update is accepted only when its route
identity, UID, and resource version are consistent with the current local Sandbox observation and
its action does not weaken the locally derived same-version decision. A stronger same-version peer
decision may still apply. An update ahead of the local cache is deferred or rejected until the cache
catches up, and an update for an absent or superseded UID is rejected.

A tombstone may be garbage-collected after the synchronized authoritative observation proves that
the UID is absent, a new UID owns the route ID, or a strictly newer active Allow/Deny record for the
same UID is installed. A newer Delete replaces the older tombstone rather than removing deletion
freshness. The acceptance gate or newer active record, not discarded process history, then rejects a
delayed old peer record. This bounds tombstones by currently observed deleted decisions plus
informer lag and makes restart safe without a persistent ledger.

Tombstones do not appear in active-route List or data-plane lookup. The shared legacy GetRoute path
continues to call GetState, but it emits legacy `running` only when phase is Running, the Sandbox is
not a pool member or paused, Ready is true, Pod IP is non-empty, and none of deletion, expired
shutdown, reserved failure, cleanup request, incomplete post-resume initialization, or unsafe
in-place update applies. Authoritative removal or completion uses legacy `dead`; every other
non-serving observation uses a non-running legacy value.

This filter is deliberately stricter than the old five-state projection because a baseline sender
must never describe a fact as running when the later model would produce Deny or Delete. It does not
add Action, expose another state method, or change the legacy wire shape; it is private compatibility
logic inside GetRoute and disappears when the state-model mapping replaces the legacy projection.
Manager, proxy, and Gateway producers and receivers must all run this baseline before the
state-model Action rollout.

### 9. Migration preserves behavior except for route safety hardening

The implementation first adds provider contracts and component-owned backend adapters, then
migrates the read-only observation, pool helpers, SandboxSet materialization, common claim types,
and `TryClaimSandbox`. Controller, Manager, Gateway, and cache switch in the same change before
duplicate definitions are removed.

No external response, Route wire field, CRD object, claim result, default value, retry decision, or
metric meaning changes. Same-or-older route resurrection after delete is rejected, and observations
that fail a known future Allow safety gate no longer emit legacy `running`. The state-model change
starts only after this prerequisite passes its equivalence, dependency, tombstone, and legacy-route
safety checks and is deployed to all route producers and receivers.

## Risks / Trade-offs

- **Provider becomes another generic dumping ground.** The parent accepts only cross-provider
  Sandbox contracts; Kubernetes mechanics stay in sandboxcr and business policy stays in callers.
- **Controller still depends on Manager transitively.** Source and package-closure checks cover the
  provider and cache, not only direct imports.
- **Options become CR-coupled.** CR pointers and the narrow backend capability remain in the child
  execution type, while concrete clients/cache never enter shared options or Manager business
  interfaces.
- **Shared orchestration escapes the Manager infra boundary.** Manager infra owns and implements
  every concrete Kubernetes operation; the shared algorithm can invoke only the narrow backend
  capabilities supplied by that boundary.
- **Claim behavior changes during movement.** Existing focused tests are migrated first and run as
  equivalence tests before any state-model semantic change.
- **Gateway receives mutation capability.** Its constructor returns only the read-only CR view and
  no backend.
- **Tombstone blocks a legitimate replacement.** UID scopes object identity, while a strictly newer
  resource version or a new UID replaces the tombstone.
- **Restart loses in-memory deletion history or tombstones accumulate forever.** Route readiness is
  gated on authoritative cache sync, peer updates are checked against that observation, and
  confirmed absence or supersession permits safe collection.
- **Two sources of truth survive.** Old Manager-owned shared helpers and option definitions are
  deleted after all consumers migrate; long-lived aliases are prohibited.

## Migration Plan

1. Add the provider contracts, read-only CR view, explicit defaults, CR execution options, narrow
   backend contract, and dependency guards without changing callers.
2. Neutralize cache/runtime dependencies and move SandboxSet materialization and pool predicates.
3. Move claim types, validation, metrics, and `TryClaimSandbox`; implement the backend in Manager
   infra and Controller, adapt callers, and preserve all focused tests.
4. Move shared state/route observation behind the read-only view; add deletion tombstones,
   authoritative cache validation, restart rebuilding, and safe collection to every route receiver;
   make legacy running satisfy the complete compatibility safety gate; adapt Manager and Gateway
   without adding Action or changing wire fields.
5. Remove duplicate Manager-owned shared types/helpers and verify no controller/provider production
   closure imports Manager or servers.
6. Complete focused package tests, stale-resurrection and legacy-route safety tests, static checks,
   component builds, and strict OpenSpec validation; deploy the producer/receiver baseline before
   beginning the dependent state-model implementation.

## Open Questions

None. Package names, option ownership, dependency direction, state consumers, and rollout order are
fixed.
