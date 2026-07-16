## Context

Route tables currently serve three roles: data-plane forwarding, a lookup-presence shortcut, and an ownership index. Those roles conflict once lifecycle states become precise. A recycling or terminal Sandbox CR still exists but intentionally has no active route, while a paused or transitional Sandbox may be stored but cannot forward.

This change shares its routing, lookup, and infra seams with the approved [short Sandbox ID design](../../../docs/specs/2026-07-10-short-sandbox-id-design.md). That design is mandatory, not an alternative implementation. It establishes these invariants before lifecycle route activation:

- client Sandbox IDs are opaque and are never split into namespace/name;
- `pkg/sandboxroute` owns the neutral `Route`, injected `Projector`, ObjectKey/UID/resourceVersion-fenced `Store`, conditional delete modes, collision quarantine, and targeted `Repairer`;
- manager and Gateway keep separate physical Stores backed by that same implementation;
- manager route feeding is installed by sandbox-manager composition, while `sandboxcr.Infra` owns no Projector, feeder, Store mutation, or repair worker;
- Gateway reconciliation is a thin CR-aware adapter;
- targeted repair performs direct ObjectKey Gets only and never a full Sandbox List;
- `infra.Sandbox` exposes neither `GetSandboxID()` nor `GetRoute()`.

The lifecycle work therefore cannot place canonical derivation in legacy `proxyutils.GetRouteFromSandbox`, retain `resourceVersion >=` registry semantics, use unconditional peer deletes, or continue the sandboxcr-owned five-minute `reconcileRoutes` loop. All of those paths are replaced by the short-ID foundation before this change starts.

Short-ID also changes what is possible on a pure claimed-ID cache miss. Once the client ID is opaque, a miss has no ObjectKey for `APIReader.Get`. Parsing a legacy ID or scanning every Sandbox would violate the short-ID contract and its scale assumptions. APIReader refresh remains valid only after a cache hit supplies an ObjectKey. Clean zero-result lookup, propagation retry, ambiguity, and backend failure must therefore stay distinct.

Part 1 provides the canonical derivation and Controller failure-stage evidence. This change is the first production consumer: it supplies canonical state to `sandboxroute.ProjectionInput.State`, and both proxy and Gateway data planes forward only a stored `running` route. The healthy golden path remains equivalent, but intermediate and terminal route behavior changes in production. The legacy general state wrapper remains unchanged until Part 3.

## Goals / Non-Goals

**Goals:**

- Make Sandbox existence and ownership independent from route presence.
- Preserve short-ID's opaque zero/one/multiple claimed-ID lookup contract and non-NotFound backend errors.
- Expose normalized lifecycle, owner, and capabilities through backend-neutral infra accessors so manager/E2B lifecycle policy does not interpret CRD phase, conditions, or annotation constants.
- Activate canonical state through the short-ID Projector without changing its ID-resolution or Route-shape responsibilities.
- Apply one lifecycle disposition table in the manager feeder and Gateway CR adapter, and reuse each component's exact inclusion predicate in targeted repair.
- Preserve short-ID ObjectKey/UID/resourceVersion fencing and conditional peer deletion while retaining legacy `dead` wire compatibility.
- Keep Gateway changes limited to lifecycle derivation and inclusion policy wiring.
- Make both the Part 1 exhaustive suite and the short-ID routing foundation mandatory activation gates.

**Non-Goals:**

- Switching SandboxSet, cache accounting, waiters, or public E2B lifecycle projection.
- Adding the public HTTP `reason` field or final lifecycle-specific 404 taxonomy.
- Changing short-ID generation, assignment, cache resolver, Route shape, Store state machine, collision policy, fence lifetime, or targeted-repair algorithm.
- Restoring production projection under `pkg/utils/proxyutils` or route ownership under `sandboxcr.Infra`.
- Parsing an opaque ID, issuing a full Sandbox List to resolve a lookup miss, or adding a second ID-to-ObjectKey index.
- Removing tuple `GetState()` before all Part 3 consumers migrate; it remains a temporary compatibility method only.
- Reintroducing `GetSandboxID()` or `GetRoute()`, which the short-ID prerequisite has already removed.

## Decisions

### 1. Make short-ID routing a hard prerequisite, not a parallel alternative

The required partial order is:

```text
1-define-sandbox-lifecycle-state-model -----------+
                                                   +--> 2-prepare-sandbox-lifecycle-infrastructure --> 3-adopt-sandbox-lifecycle-state-model
short-sandbox-id routing/cache/infra foundation +
```

Part 1 and the short-ID foundation may be implemented independently. Part 2 starts only after both are present and verified. If they ship in one release train, the short-ID Store/Projector/Repairer, manager feeder ownership, opaque cache resolver, and infra interface changes land first; lifecycle activation is a later stacked change. There is no supported branch in which Part 2 modifies the old registry or `GetRouteFromSandbox` and short-ID replaces it afterward.

The ownership split is:

| Seam | Owning design | Lifecycle integration |
|---|---|---|
| ID resolution and Route identity | short-ID | unchanged |
| `ProjectionInput` and `Projector` | short-ID | Part 2 supplies canonical `State`; Projector stays CRD-agnostic |
| physical route mutation and freshness | short-ID `Store` | Part 2 selects upsert versus authoritative delete through component policy |
| peer full/ID-only compatibility and conditional delete | short-ID | Part 2 uses `dead` only as an outgoing state compatibility value |
| feeder/repair ownership | short-ID | manager composition and Gateway adapter keep ownership; Part 2 changes their inclusion policy only |
| lifecycle normalization and diagnostic reason | lifecycle Part 1 | sandboxcr and CR-aware Gateway adapter supply observations |
| public projection and HTTP errors | lifecycle Part 3 | not activated here |

### 2. Keep claimed-ID lookup opaque and route-independent

Lookup uses the short-ID-injected claimed-Sandbox cache index and requests enough matches to distinguish zero, one, and multiple results:

1. One claimed match supplies the Sandbox and its ObjectKey.
2. A clean zero result enters a configured, bounded cache-propagation confirmation window. Repeated clean zero results when that window completes normally return typed claimed-Sandbox absence. An active opaque Route observation makes the miss non-clean and may delay or fail absence confirmation, but it cannot supply ownership or a Sandbox result.
3. Multiple matches return the short-ID ambiguity/collision error and fail closed; the caller never selects the first object.
4. Cache errors, ambiguity, request cancellation, deadline expiry before normal absence completion, and transport failures remain non-NotFound failures.
5. After a one-result cache hit, an unsatisfied resourceVersion expectation or a newer full-route observation may trigger the existing `APIReader.Get` by ObjectKey. APIReader NotFound or a fresh object without `agents.kruise.io/sandbox-claimed=true` then confirms absence; other reader errors remain backend failures.

Route presence and route state are never lookup filters. The opaque Route reader remains only a staleness signal: after a cache hit, a newer full Route may trigger ObjectKey refresh; during a zero-result window, active Route presence prevents the miss from being called clean absence. A Route never authorizes, returns, or identifies the Sandbox through infra. A pure zero-result miss does not call `APIReader.Get`, because it has no ObjectKey; it also does not parse the ID, query by reconstructed name, or issue a full List. This explicitly supersedes the earlier lifecycle draft's pure-miss APIReader claim in order to preserve the approved short-ID invariant.

Part 2 carries these typed outcomes far enough for E2B to keep clean absence as the existing generic 404, preserve the existing ownership status, and map non-NotFound failures to 5xx. Part 3 adds the optional reason field and lifecycle-specific 404 taxonomy.

### 3. Evolve short-ID's neutral input extraction without moving projection into infra

`infra.Sandbox` gains a named lifecycle observation containing typed internal state and a non-empty diagnostic reason, plus CR-backed owner, recycle-eligibility, and reserved-failure/visibility capabilities. Sandboxcr implements them from the CR and canonical derivation. The vocabulary remains owned by `pkg/utils/lifecycle`; infra may expose type/constant aliases for that normalized vocabulary so manager/E2B import only the infra contract. Those aliases contain no derivation or Kubernetes policy and MUST NOT become a second independently maintained state set.

This deliberately evolves two temporary short-ID extraction seams:

- manager route projection takes `ProjectionInput.State` from the normalized lifecycle observation instead of tuple `GetState()`;
- manager authorization and `ProjectionInput.Owner` take the normalized owner accessor instead of interpreting `AnnotationOwner` in sandbox-manager.

The remaining neutral short-ID inputs stay intact: embedded `metav1.Object` supplies ObjectKey/UID/resourceVersion, `GetPodIP()` supplies the address, and the injected Projector resolves the opaque ID. Infra does not import `pkg/sandboxroute`, return a `Route`, select an ID, register a route event handler, mutate a Store, or run a Repairer.

Tuple `GetState()`, raw `Phase()`, and split recycle methods remain temporarily for untouched Part 3 consumers. `GetState()` is no longer used by the manager route feeder after this change. `GetSandboxID()` and `GetRoute()` are already absent because of short-ID and MUST NOT be reintroduced.

The manager lifecycle dependency is:

```text
E2B -> SandboxManager policy -> infra.Sandbox normalized contract -> sandboxcr -> api/v1alpha1 + pkg/utils/lifecycle
```

Manager composition may pass generic Kubernetes object metadata into the neutral Projector, but Sandbox-manager and E2B do not interpret Sandbox phase, conditions, claim/cleanup metadata, ownership annotation constants, or Controller reason strings. Controller and lifecycle packages do not import manager, infra, server, or route packages.

### 4. Supply canonical state through `ProjectionInput`

The short-ID Projector remains a mechanical projection boundary. It receives an explicit `ProjectionInput` and copies the supplied `State`; it does not derive lifecycle, inspect a Sandbox CR, read a clock, or rewrite an empty IP to `creating`.

The manager feeder obtains the normalized state/reason through the sandboxcr-backed infra adapter. The Gateway CR adapter is already CR-aware and invokes the same canonical explicit-time derivation with its injected observation time. Both then build the existing neutral `ProjectionInput` and call the same Projector implementation.

An empty Pod IP never changes the lifecycle state. It merely prevents forwarding because only `running` can be produced when Ready and Pod IP satisfy the canonical serving gate. Preserving the derived value is essential for deleting an empty-IP recycling or terminal route rather than accidentally retaining it as `creating`.

Production code does not call `proxyutils.GetRouteFromSandbox`. Any temporary compatibility facade retained by short-ID tests still requires an injected Projector and is not a lifecycle decision point.

### 5. Apply lifecycle disposition in component adapters and repair callbacks

The shared disposition is:

| State | Local full Route present | Forwarded |
|---|---:|---:|
| `creating`, `available`, `pausing`, `paused`, `resuming`, `upgrading` | yes | no |
| `running` | yes | yes |
| `recycling`, `terminating`, `succeeded`, `failed`, legacy `dead` | no | no |

For a present retained observation, the adapter projects a full Route and offers it through `UpsertFull`; the Store alone decides ordering, replacement, collision, no-op, and repair requests. For NotFound, `DeletionTimestamp`, visibility exclusion, or a deletion-disposition lifecycle state, the adapter uses `DeleteAuthoritativeByObjectKey` and the separately injected legacy fallback exactly as defined by short-ID. It never deletes by client ID or calls an unconditional Store mutation.

Manager and Gateway each define one inclusion/deletion predicate covering configured namespace/selector visibility, deletion timestamp, and lifecycle disposition. Each component reuses the identical predicate in its informer event adapter and direct-APIReader targeted-repair callback. A direct repair therefore cannot re-add a terminal route that the normal feeder considers absent.

A later strictly newer retained observation for a recycled same-UID object may cross the short-ID deletion fence and restore its full Route according to the existing Store state machine. Lifecycle policy does not bypass or weaken that fence.

The manager uses its short-ID cache custom handler; it does not restore sandboxcr-owned `reconcileSandbox` or the periodic five-minute `reconcileRoutes`. Normal initial population and missed-event recovery remain informer List/Watch responsibilities. Ambiguous Store mutations enqueue the existing targeted ObjectKey Repairer; no lifecycle path performs a periodic or request-triggered full Sandbox List.

### 6. Keep `dead` as a copy-only peer deletion signal over conditional Store APIs

Local CR observations retain precise lifecycle state. When manager explicit delete/recycle succeeds, or its cache feeder removes an existing full Route because the observed state became `recycling`, `terminating`, `succeeded`, or `failed`, the sender may project that full current observation, copy it, and change only the copy's state to legacy `dead` before peer synchronization.

The full payload preserves namespace, name, ID, UID, resourceVersion, owner, IP, and access token. A short-ID-aware receiver validates the shape and applies `DeleteFullConditionally`; an old JSON decoder ignores additive namespace/name fields and recognizes `dead` through its legacy path. Old ID-only payloads received during the short-ID compatibility window continue through `DeleteIDOnlyConditionally`.

The source observation and any diagnostic remain precise. Retained states are never translated. Informer handling sends a deletion notification only when it actually removes a local active Route; an already-absent stable terminal CR does not create a periodic broadcast. Targeted repair remains local and does not turn into a full-store or peer-rebroadcast loop.

### 7. Keep the Gateway lifecycle delta small without reverting short-ID safety

Gateway already uses the shared short-ID Store, Projector, conditional peer mutations, and targeted Repairer. Part 2 changes only its CR adapter's canonical state extraction and inclusion predicate, plus focused wiring tests. It does not implement another registry, RV comparator, tombstone/fence, collision mechanism, or repair queue.

The local Gateway adapter stores retained transitional Routes and deletes deletion-disposition Routes through the shared Store. The data-plane filter remains unchanged and forwards only `running`.

Gateway's peer HTTP policy also remains running-only: full or ID-only `running` payloads use the appropriate upsert, while non-running payloads use the appropriate conditional delete. Consequently, a peer transitional Route may be absent even when the local CR adapter would retain it. This is accepted because it cannot forward traffic, API existence/ownership no longer depends on Gateway routes, and a later local `running` observation restores the full Route. The important short-ID safety properties—identity validation, UID/RV fencing, collision quarantine, and targeted repair—remain intact.

### 8. Treat Part 2 as a production data-plane activation

Both proxy and Gateway forwarding compare the stored state with `running`. Part 2 therefore changes production behavior as soon as adapter projection uses canonical state. Activation requires:

- every Part 1 declared-phase, precedence, persistent-condition, in-place failure-stage, and Ready re-synchronization test to pass;
- the short-ID Store/Projector/Repairer and manager/Gateway feeder ownership to be present;
- no old `GetRouteFromSandbox`, sandboxcr route feeder, periodic reconcile, independent registry algorithm, or unconditional peer delete remaining on the production path;
- route tests proving the healthy golden path, every retained-but-rejected state, every deletion state, empty-IP behavior, and conditional peer deletion.

## Risks / Trade-offs

- **[Risk] A canonical derivation bug changes data-plane availability.** -> Gate activation on the full Part 1 suite and route-level golden tests for healthy running, every transition, empty IP, and every deletion state.
- **[Risk] Lifecycle Part 2 is applied to a checkout that still has the legacy route algorithms.** -> Make short-ID an explicit hard prerequisite and fail the source inventory if shared Store/Projector/Repairer, manager feeder ownership, or conditional peer mutations are absent.
- **[Risk] A pure opaque-ID cache miss cannot be verified by direct Get.** -> Use a bounded, test-injectable propagation confirmation window; classify only clean repeated zero results through its normal completion as absence, preserve earlier caller cancellation/backend/ambiguity as non-404, and forbid ID parsing or a full List workaround.
- **[Risk] Removing route-based ownership weakens tenant isolation.** -> Authenticate first, fetch the claimed CR, expose its owner through infra, and enforce that owner before lifecycle details are returned.
- **[Risk] Gateway peer policy discards transitional Routes.** -> Accept the non-forwarding loss; local CR observation restores `running`, and lookup no longer depends on the registry.
- **[Risk] Lifecycle policy accidentally bypasses short-ID ordering or deletion fences.** -> Require every adapter mutation to use the authority-specific Store APIs and reuse the same inclusion predicate in targeted repair.
- **[Risk] An old peer needs the legacy deletion state.** -> Translate only an outgoing copy to `dead` while preserving the full ObjectKey/UID/RV payload for new conditional receivers.
- **[Trade-off] This change cannot be deployed independently of short-ID routing even when short assignment remains disabled.** -> The shared route machinery, not short assignment itself, is the prerequisite; assignment may remain disabled according to the short-ID rollout plan.

## Migration Plan

1. Implement and verify Part 1. In parallel or earlier, implement the approved short-ID routing/cache/infra foundation.
2. Roll out the short-ID-capable manager and Gateway binaries according to their disabled-assignment, old-peer drain, compatibility-expiry, collision, and repair-queue gates. Part 2 MUST NOT target a mixed legacy route implementation.
3. Add normalized lifecycle/owner/capability accessors, migrate manager ownership and route-state extraction to them, and preserve opaque lookup outcomes.
4. Activate lifecycle disposition in the manager feeder and Gateway CR adapter, using the shared Projector/Store/Repairer and copy-only `dead` peer deletion.
5. Verify data-plane behavior and Store mutation results, then deploy Part 2 before `3-adopt-sandbox-lifecycle-state-model`.

Rolling back Part 2 restores legacy state extraction and lifecycle disposition while leaving the short-ID foundation in place. It does not roll back a cluster across short-ID's persisted-label boundary. No lifecycle CRD data migration is required.

## Open Questions

None. The short-ID prerequisite, opaque-miss limitation, normalized input evolution, Projector integration, component disposition, conditional peer deletion, targeted-repair reuse, and minimal Gateway delta are fixed.
