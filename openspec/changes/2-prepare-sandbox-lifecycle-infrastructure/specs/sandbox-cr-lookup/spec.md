## ADDED Requirements

### Requirement: Claimed Sandbox lookup is opaque and independent from routes and lifecycle state
Claimed-Sandbox lookup SHALL use the short-ID-injected cache index, treat the client-provided Sandbox ID as opaque, and distinguish zero, one, and multiple matches. It SHALL return a unique claimed Sandbox CR without requiring a route and without filtering transitional, recycling, or terminal lifecycle states. It MUST NOT parse the ID, select an arbitrary duplicate, or use route presence as existence proof.

#### Scenario: Missing route does not prove absence
- **WHEN** a uniquely indexed claimed Sandbox CR exists but no active Route is stored
- **THEN** lookup returns the CR for ownership and later lifecycle evaluation

#### Scenario: Terminal CR remains observable
- **WHEN** a uniquely indexed claimed Sandbox CR exists in a recycling or terminal lifecycle state
- **THEN** lookup returns the CR even though lifecycle disposition deletes its Route

#### Scenario: One indexed match succeeds
- **WHEN** the opaque claimed-ID index returns exactly one claimed Sandbox in the requested namespace scope
- **THEN** lookup returns that Sandbox and its ObjectKey may be used for later staleness refresh

#### Scenario: Multiple indexed matches fail closed
- **WHEN** more than one claimed Sandbox matches the opaque ID
- **THEN** lookup returns the short-ID ambiguity error without selecting the first object, disclosing colliding ObjectKeys, or parsing the ID

#### Scenario: Unclaimed object is not a user Sandbox
- **WHEN** a cache-hit or APIReader-refreshed Sandbox lacks `agents.kruise.io/sandbox-claimed=true`
- **THEN** claimed-Sandbox lookup returns typed claimed-Sandbox absence

### Requirement: Pure miss preserves opaque-ID and propagation semantics
A zero-result cache lookup SHALL use a bounded, test-injectable propagation confirmation window and SHALL return typed absence only after normal window completion with clean repeated zero results. Active opaque Route presence SHALL make a miss non-clean but MUST NOT return, identify, or authorize a Sandbox. A pure miss MUST NOT invoke `APIReader.Get` without an ObjectKey, split the client ID on `--`, reconstruct namespace/name, or issue a full Sandbox List.

#### Scenario: Propagation retry finds the Sandbox
- **WHEN** the first index read returns zero during an allowed cache/label propagation window and a later retry returns one unique match
- **THEN** lookup returns the Sandbox without using a legacy alias or parsing the ID

#### Scenario: Clean zero result confirms indexed absence
- **WHEN** the bounded propagation confirmation window completes normally with clean repeated zero results and no ambiguity or backend error
- **THEN** lookup returns typed claimed-Sandbox absence

#### Scenario: Pure miss has no direct Get key
- **WHEN** the index returns zero for an opaque Sandbox ID
- **THEN** lookup does not call `APIReader.Get` or derive an ObjectKey from the ID

#### Scenario: Active Route prevents false clean absence
- **WHEN** the index returns zero while the opaque Route reader still has an active observation for the requested ID
- **THEN** lookup treats the observation only as cache-lag evidence, does not return the Route as a Sandbox, and does not complete clean claimed-Sandbox absence during that observation

#### Scenario: Context expires before absence completion
- **WHEN** cancellation or deadline expiry interrupts propagation retry before a clean absence result is reached
- **THEN** lookup returns the context/backend classification rather than claimed-Sandbox absence

### Requirement: Cache-hit staleness is refreshed by ObjectKey
After a unique cache hit supplies an ObjectKey, the existing APIReader fallback SHALL refresh an object whose resourceVersion expectation is unsatisfied or whose full Route observation proves the cache value older. APIReader NotFound or a fresh unclaimed object SHALL confirm absence; every other reader failure SHALL remain a backend failure.

#### Scenario: ResourceVersion expectation is unsatisfied
- **WHEN** a unique cached Sandbox is behind a known resourceVersion expectation
- **THEN** lookup performs `APIReader.Get` using the cached Sandbox ObjectKey and returns the fresh claimed object

#### Scenario: Full Route is newer than cache hit
- **WHEN** a unique cached Sandbox has an older resourceVersion than the opaque ID's full Route observation
- **THEN** lookup performs `APIReader.Get` by the cached ObjectKey rather than treating route presence or state as lookup policy

#### Scenario: APIReader confirms NotFound after cache hit
- **WHEN** cache-hit staleness refresh reports Kubernetes NotFound
- **THEN** lookup returns typed claimed-Sandbox absence

#### Scenario: Route is absent
- **WHEN** a unique cache hit has no Route observation and no unsatisfied expectation
- **THEN** lookup returns the cached CR without requiring a route or calling APIReader solely because the route is missing

### Requirement: Backend and ambiguity failures are not rewritten as absence
Cache, ambiguity, APIReader, timeout, cancellation, and transport failures other than a clean indexed zero result, cache-hit APIReader NotFound, or a refreshed unclaimed object MUST remain typed non-NotFound failures through infra and Sandbox-manager. They MUST NOT be converted into claimed-Sandbox absence or HTTP 404.

#### Scenario: APIReader is unavailable
- **WHEN** cache-hit fallback fails for a reason other than NotFound
- **THEN** the original backend classification is preserved for the caller

#### Scenario: Cache lookup fails
- **WHEN** the claimed-ID index reports an operational error rather than a clean zero result
- **THEN** lookup preserves that failure and does not label it absence

#### Scenario: E2B receives a backend or ambiguity failure
- **WHEN** manager-path lookup returns a non-NotFound backend or collision classification
- **THEN** the E2B boundary returns the mapped non-404 error without a false Sandbox NotFound classification

### Requirement: Ownership is enforced from the normalized Sandbox CR contract
Authentication middleware SHALL authenticate and attach the user without using route presence or route owner. The sandboxcr adapter SHALL expose the fetched CR owner through a backend-neutral infra accessor, and Sandbox-manager SHALL compare that accessor with the authenticated user before exposing lifecycle or Sandbox data. Sandbox-manager MUST NOT interpret `AnnotationOwner` or reconstruct owner from `ProjectionInput` or Route.

#### Scenario: Owned CR is accepted without route
- **WHEN** the claimed CR owner accessor matches the authenticated user and its Route is absent
- **THEN** ownership succeeds and lifecycle evaluation continues

#### Scenario: CR owner mismatch is rejected
- **WHEN** the normalized CR owner does not match the authenticated user
- **THEN** the existing authorization failure is returned before lifecycle details or short-ID resource diagnostics are exposed

#### Scenario: Route owner cannot override CR owner
- **WHEN** a stale Route contains an owner different from the fetched CR's normalized owner
- **THEN** ownership is decided exclusively from the infra owner accessor

### Requirement: Infra exposes normalized CR facts without owning route projection
The infra Sandbox contract SHALL expose a named lifecycle observation with internal state and non-empty diagnostic reason, plus CR-backed owner, recycle eligibility, and reserved-failure visibility capabilities. Its state type/constants SHALL be aliases of the canonical `pkg/utils/lifecycle` vocabulary rather than an independently maintained vocabulary. E2B and Sandbox-manager lifecycle decisions MUST NOT inspect Sandbox phase, conditions, claim/cleanup metadata, ownership annotation constants, or Controller reason constants directly. Infra MUST NOT expose Sandbox ID or Route selection, import `pkg/sandboxroute`, register a route feeder, mutate a Store, or start targeted repair.

#### Scenario: Sandboxcr adapts a CR observation
- **WHEN** sandboxcr wraps a Sandbox CR
- **THEN** it derives the canonical lifecycle observation and exposes normalized owner and capabilities through infra accessors

#### Scenario: Infra does not fork lifecycle vocabulary
- **WHEN** manager or E2B compares a normalized lifecycle state through the infra contract
- **THEN** the type and constants alias the canonical lifecycle package while CRD derivation remains in sandboxcr

#### Scenario: Manager builds short-ID projection input
- **WHEN** manager composition needs to project an infra Sandbox
- **THEN** it combines generic object metadata and `GetPodIP()` with normalized lifecycle and owner facts, then calls the injected short-ID Projector without calling `GetRoute()` or selecting an ID in infra

#### Scenario: Upper layer evaluates lifecycle
- **WHEN** Sandbox-manager or E2B needs lifecycle state, diagnostic reason, owner, or recycle eligibility
- **THEN** it consumes the infra contract without reconstructing those facts from Kubernetes fields

#### Scenario: Short-ID methods stay absent
- **WHEN** the lifecycle accessors are added
- **THEN** `infra.Sandbox.GetSandboxID()` and `infra.Sandbox.GetRoute()` remain absent, while tuple `GetState()` may remain temporarily only for Part 3 migration

#### Scenario: Controller dependency does not reverse
- **WHEN** lifecycle and infra boundaries are implemented
- **THEN** Controller and `pkg/utils/lifecycle` packages do not import sandbox-manager, infra, web, E2B, or route packages
