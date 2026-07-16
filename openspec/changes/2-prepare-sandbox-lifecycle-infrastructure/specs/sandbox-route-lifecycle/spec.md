## ADDED Requirements

### Requirement: Lifecycle route activation extends the approved short-ID foundation
Canonical lifecycle routing SHALL activate only after the Part 1 lifecycle/Controller suites pass and the approved short-ID routing foundation is present. Production route construction SHALL use the injected `pkg/sandboxroute` Projector and full `ProjectionInput`; manager and Gateway mutations SHALL use the shared ObjectKey/UID/resourceVersion-fenced Store and targeted Repairer. Production code MUST NOT restore `GetRouteFromSandbox`, sandboxcr-owned route feeders, periodic full reconciliation, independent registry algorithms, unconditional peer deletes, ID parsing, or full Sandbox List repair.

#### Scenario: Part 1 verification is incomplete
- **WHEN** any declared-phase, precedence, persistent-condition, mutation-stage, or Ready re-synchronization test is failing
- **THEN** canonical lifecycle route projection is not enabled

#### Scenario: Short-ID foundation is absent
- **WHEN** the implementation base still routes through `GetRouteFromSandbox`, an independent registry, sandboxcr-owned periodic reconciliation, or unconditional peer delete
- **THEN** Part 2 implementation stops until the approved short-ID foundation is integrated

#### Scenario: Canonical state enters the neutral Projector
- **WHEN** a manager or Gateway adapter observes a Sandbox CR
- **THEN** the adapter supplies canonical state through `ProjectionInput.State`, while the Projector remains unaware of CRD phase, conditions, lifecycle precedence, and ID format

#### Scenario: Infra does not regain route ownership
- **WHEN** manager route feeding and repair are composed
- **THEN** sandbox-manager composition owns the feeder and Repairer, and `sandboxcr.Infra` owns no Projector, Route construction, Store mutation, route handler registration, or repair worker

### Requirement: Local CR route disposition follows lifecycle state
CR-backed component adapters SHALL retain `creating`, `available`, `pausing`, `paused`, `resuming`, and `upgrading` as full Routes without forwarding; SHALL retain and forward only `running`; and SHALL treat `recycling`, `terminating`, `succeeded`, `failed`, and legacy `dead` as authoritative route absence. Every mutation SHALL use the authority-specific short-ID Store API.

#### Scenario: Healthy golden path remains forwarding
- **WHEN** a claimed Sandbox is in phase Running, Ready is true, and Pod IP is non-empty without a higher-priority lifecycle fact
- **THEN** projection supplies `running`, `UpsertFull` retains the Route, and both proxy and Gateway data planes remain eligible to forward

#### Scenario: Transitional local route is retained but rejected
- **WHEN** the manager feeder or Gateway CR adapter observes `creating`, `available`, `pausing`, `paused`, `resuming`, or `upgrading`
- **THEN** it offers a full Route through `UpsertFull` while the data plane refuses forwarding because the state is not `running`

#### Scenario: Terminal local route is authoritatively absent
- **WHEN** local observation derives `recycling`, `terminating`, `succeeded`, or `failed`
- **THEN** the adapter calls `DeleteAuthoritativeByObjectKey` and the Route cannot forward

#### Scenario: Missing or deleting CR removes the ObjectKey
- **WHEN** the local adapter observes NotFound, `DeletionTimestamp`, or configured visibility exclusion
- **THEN** it applies authoritative ObjectKey absence with only the separately injected legacy fallback and never deletes by a client-provided ID

#### Scenario: Empty IP preserves lifecycle disposition
- **WHEN** a recycling or terminal Sandbox has an empty Pod IP
- **THEN** `ProjectionInput.State` remains the precise deletion state instead of being rewritten to `creating`

#### Scenario: Newer retained observation restores a recycled object
- **WHEN** the same ObjectKey later produces a retained observation whose resource version satisfies the existing short-ID deletion-fence rules
- **THEN** the Store may restore the full Route without bypassing UID/RV fencing

### Requirement: Event adapters and targeted repair share one inclusion predicate
Manager and Gateway SHALL each define one namespace, selector, deletion, and lifecycle inclusion predicate and SHALL reuse it for both normal informer observations and targeted direct-reader repair. Repair SHALL perform ObjectKey Gets requested by the Store and MUST NOT List all Sandboxes.

#### Scenario: Repair cannot re-add a terminal Route
- **WHEN** targeted repair directly reads a Sandbox that the normal adapter classifies as recycling, terminal, deleting, or excluded
- **THEN** it returns authoritative absence and cannot project or upsert that Sandbox

#### Scenario: Present retained repair observation is projected
- **WHEN** targeted repair directly reads a present, visible, non-deleting Sandbox in a retained lifecycle state
- **THEN** it builds the same full projection as the event adapter and applies it through generation-matched authoritative repair

#### Scenario: Repair read fails
- **WHEN** an APIReader Get or projection fails
- **THEN** the Store remains unchanged and the existing rate-limited targeted repair behavior retries without blocking the event adapter

#### Scenario: No periodic full reconcile is introduced
- **WHEN** informer delivery is healthy or a Store mutation is ambiguous
- **THEN** normal List/Watch recovery or targeted ObjectKey repair is used, and no sandboxcr-owned periodic route List or full APIReader List runs

### Requirement: Peer deletion is legacy-state compatible and identity fenced
Manager peer senders SHALL translate a precise `recycling`, `terminating`, `succeeded`, or `failed` observation to `dead` only on a copy used for deletion synchronization. Full short-ID Route identity fields MUST be preserved. Short-ID-aware receivers SHALL use full or ID-only conditional delete according to payload shape; retained states MUST NOT be translated.

#### Scenario: Precise full deletion is translated
- **WHEN** an explicit operation or manager feeder accepts removal of a current full Route for a deletion-disposition observation
- **THEN** peers receive a copied full Route with the same namespace, name, ID, UID, resourceVersion, owner, IP, and token and with state `dead`

#### Scenario: Translation does not mutate the source
- **WHEN** a Route is translated for peer synchronization
- **THEN** the source lifecycle observation, Route value, and diagnostic reason remain precise

#### Scenario: Retained state is not translated
- **WHEN** a retained `creating`, `available`, `pausing`, `paused`, `resuming`, or `upgrading` Route is synchronized
- **THEN** the sender does not rewrite it to `dead`

#### Scenario: New receiver applies full conditional delete
- **WHEN** a short-ID-aware receiver gets a full `dead` Route
- **THEN** it validates ObjectKey, ID, UID, and resourceVersion and calls the full conditional-delete Store operation

#### Scenario: Old ID-only payload stays compatible
- **WHEN** a short-ID-aware receiver gets an old payload with both namespace and name absent
- **THEN** it uses only the ID-only compatibility delete state machine and cannot delete an ObjectKey-backed full Route

#### Scenario: Stable absent terminal CR is not rebroadcast periodically
- **WHEN** a terminal or recycling CR remains present after its local Route is already absent
- **THEN** no periodic deletion broadcast or full-store reconciliation is started

### Requirement: Gateway keeps a minimal lifecycle adapter delta
Gateway SHALL reuse the approved short-ID Store, Projector, conditional peer handler, and targeted Repairer. Its local CR adapter SHALL retain transitional Routes and delete deletion-disposition Routes; its data-plane and peer state policies SHALL remain running-only.

#### Scenario: Gateway controller and filter have separate responsibilities
- **WHEN** the Gateway local CR adapter observes a retained non-running state
- **THEN** the adapter stores it through the shared Store and the unchanged data-plane filter rejects it

#### Scenario: Peer transitional Route may be absent
- **WHEN** the Gateway peer handler receives a non-running transitional Route
- **THEN** it applies the appropriate conditional delete and does not forward traffic

#### Scenario: Later local Running observation restores forwarding
- **WHEN** the Gateway local CR adapter later observes the Sandbox as `running`
- **THEN** it offers the full Route through the shared Projector and Store, subject to the existing UID/RV fences

#### Scenario: Lifecycle does not fork Store semantics
- **WHEN** Gateway lifecycle integration is implemented
- **THEN** it adds no independent RV comparator, tombstone/fence, collision map, unconditional delete, or repair queue
