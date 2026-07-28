## ADDED Requirements

<!--
Traceability to the design artifact:
- Authoritative Sandbox ID resolution: Sections 4 and 6; Acceptance Criteria 2-3.
- Complete UID short-ID encoding: Section 5; Acceptance Criterion 1.
- Flag-controlled final assignment: Sections 6, 8, and 9; Acceptance Criteria 1-2.
- One-way CR identity transition: Sections 4.3 and 9.4; Acceptance Criteria 5-6 and 16.
- Reserved metadata protection: Sections 4.1, 9.4, and 13.1; Acceptance Criterion 4.
- Final assignment failure semantics: Sections 8.1-8.3 and 17; Acceptance Criterion 1.
- Opaque unique cache lookup: Section 10; Acceptance Criteria 5 and 7.
- Shared atomic route projection: Sections 11.1-11.4; Acceptance Criteria 5, 7-8.
- Version-fenced peer compatibility and deletion: Sections 11.3-11.7 and 17; Acceptance Criteria 8-9 and 11.
- Informer-driven route deletion fencing: Sections 11.3 and 11.8; Acceptance Criterion 10.
- Authorized E2B resource diagnostics: Section 13; Acceptance Criterion 14.
- Point-in-time Checkpoint and opaque pagination identity: Section 12; Acceptance Criterion 13.
- Staged activation and rollback boundary: Section 14; Acceptance Criterion 15.
- Bounded identity observability: Section 15.
-->
### Requirement: Authoritative Sandbox ID resolution
The system SHALL return a Sandbox's non-empty `agents.kruise.io/sandbox-id` label unchanged and SHALL otherwise resolve the legacy `<namespace>--<name>` ID, independent of whether new short-ID assignment is enabled.

#### Scenario: Existing non-empty label is authoritative
- **WHEN** a Sandbox has a non-empty `agents.kruise.io/sandbox-id` label
- **THEN** every component returns that label unchanged without validating its alphabet, length, UID relationship, or origin

#### Scenario: Missing or empty label uses the legacy ID
- **WHEN** the label is absent or empty
- **THEN** the Sandbox resolves to `<namespace>--<name>`

### Requirement: Complete UID short-ID encoding
The system SHALL generate a short Sandbox ID suffix by encoding all 16 UUID bytes of the Kubernetes UID with unpadded lowercase RFC 4648 Base32, producing 26 characters from `[a-z2-7]` without truncation.

#### Scenario: Valid UID is encoded deterministically
- **WHEN** short assignment processes the same valid 16-byte Kubernetes UID more than once
- **THEN** it produces the same 26-character lowercase unpadded Base32 value each time

#### Scenario: Invalid UID fails generation
- **WHEN** short assignment receives a UID that cannot be decoded as 16 UUID bytes
- **THEN** generation fails instead of persisting a fallback or truncated ID

### Requirement: Configurable short-ID prefix
The system SHALL expose `--short-sandbox-id-prefix=""`, prepend its value verbatim to every newly generated 26-character suffix without adding a separator, reject startup unless a non-empty prefix starts with `[a-z0-9]` and otherwise contains only `[a-z0-9-]`, and SHALL NOT impose a prefix length limit.

#### Scenario: Empty prefix preserves the original format
- **WHEN** short assignment runs with the default empty prefix
- **THEN** the persisted ID is exactly the 26-character encoded UID suffix

#### Scenario: Configured prefix is prepended
- **WHEN** short assignment runs with prefix `prod-`
- **THEN** the persisted ID is `prod-` followed immediately by the 26-character encoded UID suffix

#### Scenario: Malformed prefix prevents startup
- **WHEN** the configured prefix contains invalid characters or starts with a hyphen
- **THEN** sandbox-manager startup fails before Infra is constructed, even if short assignment is disabled

#### Scenario: Prefix length is unrestricted
- **WHEN** a syntactically valid prefix exceeds any previous implementation length threshold
- **THEN** sandbox-manager does not reject it solely because of its length and passes it unchanged to assignment

#### Scenario: Existing label ignores prefix changes
- **WHEN** a Sandbox already has a non-empty authoritative label
- **THEN** the label is returned unchanged and is not regenerated with the current prefix

### Requirement: Flag-controlled final assignment
The system SHALL use `--enable-short-sandbox-id=false` as an assignment-only gate and, when enabled, persist an unlabeled claim or clone's generated short ID at the final successful stage before returning its client-visible identity.

#### Scenario: Assignment is disabled
- **WHEN** claim or clone succeeds for an unlabeled Sandbox while short assignment is disabled
- **THEN** no short-ID label is added and the operation returns the legacy ID

#### Scenario: Assignment is enabled
- **WHEN** claim or clone succeeds for an unlabeled Sandbox while short assignment is enabled
- **THEN** the generated short ID is persisted before the success response returns that ID

#### Scenario: Clone uses its own identity
- **WHEN** a Sandbox is cloned while short assignment is enabled
- **THEN** the clone's own UID generates its short ID and no sandbox-ID label is inherited from the source or template

### Requirement: One-way CR identity transition
The system SHALL treat Sandbox ID as the identity of the Sandbox CR, preserve a non-empty label through recycle and later operations, and expose no simultaneous active legacy and short aliases.

#### Scenario: Recycled unlabeled Sandbox transitions later
- **WHEN** an unlabeled Sandbox returns to a pool and is later claimed with short assignment enabled
- **THEN** it may transition from its legacy ID to one persisted short ID

#### Scenario: Labeled Sandbox is recycled or assignment is disabled
- **WHEN** a labeled Sandbox is recycled, claimed again, or observed after the feature flag is disabled
- **THEN** it retains the same short ID and does not regain a legacy alias

#### Scenario: Ownership changes across claims
- **WHEN** a Sandbox CR is reused by another claim or tenant session
- **THEN** authorization and external consumers do not infer the current owner or session from the Sandbox ID alone

### Requirement: Reserved metadata protection
The system MUST reject or strip user-controlled and callback-controlled attempts to add, change, or delete the reserved Sandbox-ID label, while preserving a core-assigned label during metadata cleanup and recycle.

#### Scenario: Public input supplies the reserved label
- **WHEN** E2B extensions or SandboxClaim labels supply `agents.kruise.io/sandbox-id`
- **THEN** the request is rejected before infra, cache, or routing state is invoked

#### Scenario: Pool or template carries the reserved label
- **WHEN** SandboxSet or SandboxTemplate metadata is materialized into a Sandbox
- **THEN** the reserved internal label is not inherited

#### Scenario: Caller callback mutates the reserved label
- **WHEN** a pre-lock Modifier or final PostModifier adds, changes, or deletes the reserved key
- **THEN** the operation fails before that modified object is persisted, even when short assignment is disabled

#### Scenario: Recycle metadata lists the reserved label
- **WHEN** current, historical, or manually crafted cleanup metadata lists the reserved key
- **THEN** recycle preserves the existing short-ID label

### Requirement: Final assignment failure semantics
The system MUST fail the overall claim or clone and use its existing cleanup path when final identity refresh, callback, conflict retry, context handling, or persistence fails, and MUST NOT emit a success response before final identity is persisted.

#### Scenario: Final callback or update fails
- **WHEN** the final metadata stage returns an error after readiness work has completed
- **THEN** the operation fails through existing cleanup and does not return a partially successful Sandbox result

#### Scenario: Final callback makes no change
- **WHEN** the final callback reports `changed=false`
- **THEN** the returned Sandbox is refreshed from that attempt's informer Get only when it is not older than the current wrapper view, and no Update is issued

### Requirement: Opaque unique cache lookup
The claimed-Sandbox cache SHALL index exactly one resolved ID per Sandbox, treat client-provided IDs as opaque, and request at most one result under the supported global-ID uniqueness contract.

#### Scenario: Label update reaches the cache
- **WHEN** an informer observes a Sandbox transition from unlabeled to a non-empty short-ID label
- **THEN** the cache moves the entry from the legacy key to the short key without retaining both aliases

#### Scenario: Claimed Sandbox is looked up
- **WHEN** a client supplies an opaque Sandbox ID
- **THEN** cache lookup requests at most one indexed result and does not parse the ID for fallback lookup

### Requirement: Shared atomic route projection
Manager and gateway SHALL use the same ObjectKey-, resourceVersion-, and SandboxID-aware routing
semantics while maintaining separate physical stores, and an accepted ID transition SHALL replace
the old route with the new route atomically. Every accepted Route producer, including peer refresh,
SHALL be a trusted projection of ObjectMeta from the same Kubernetes cluster. Every supported
non-empty label SHALL be generated from that Sandbox's complete UID; direct reserved-label writes,
copied labels, forged Routes, and cross-cluster delivery are undefined behavior. The Store SHALL
rely on Kubernetes resourceVersion ordering across objects in that cluster, store each complete
Route only in its ObjectKey record, and maintain only an active SandboxID-to-ObjectKey index. UID
remains on the wire for compatibility and validation but SHALL NOT participate in Store ordering.

#### Scenario: Legacy route transitions to short
- **WHEN** a full Route with a strictly newer resourceVersion changes the same UID from its legacy ID to its persisted short ID
- **THEN** one Store transaction removes the legacy ID and activates the short ID so a single snapshot never contains both

#### Scenario: Route is logged
- **WHEN** any shared Route is formatted for logs
- **THEN** its access token is rendered as `***`

#### Scenario: Runtime access token takes priority
- **WHEN** a projected Sandbox carries both the runtime access-token annotation and the legacy envd access-token annotation
- **THEN** every component's projected Route carries the runtime token

#### Scenario: Legacy envd token fallback
- **WHEN** a projected Sandbox carries only the legacy envd access-token annotation
- **THEN** every component's projected Route falls back to the envd token

#### Scenario: Traffic auth requires the exact enable value
- **WHEN** a projected Sandbox's JWT-auth annotation is absent or any value other than exactly `true`
- **THEN** the projected Route does not require traffic auth

#### Scenario: Active route is looked up
- **WHEN** a caller gets an active Sandbox ID
- **THEN** the Store resolves SandboxID to ObjectKey and reads the authoritative Route record under the same read lock

#### Scenario: ObjectKey is reused
- **WHEN** a Sandbox is deleted and a new Sandbox is created with the same namespace and name
- **THEN** the recreated object's greater resourceVersion crosses the deletion fence and stale events from the previous object remain fenced

#### Scenario: Equal resourceVersion is replayed
- **WHEN** any Route for the current ObjectKey repeats the current record or fence resourceVersion
- **THEN** the Store ignores it as stale without requeueing or changing current state

### Requirement: Operation-specific Route validation and version-fenced deletion
The routing Store MUST require an explicit ObjectKey for every mutation, MUST apply full-Route
validation to Upsert and ObjectKey/RV validation to Delete, MUST use ObjectKey/RV-fenced deletion,
and MUST prevent stale updates and deletes from replacing or removing current ownership. It MUST
NOT reverse-parse a Route ID to recover ObjectKey.

#### Scenario: An old peer sends an ID-only Route
- **WHEN** JSON decoding succeeds and a peer Route has both namespace and name absent with a non-empty ID, for any state or resourceVersion
- **THEN** the endpoint logs at debug level and returns `204 No Content` before state/resourceVersion checks, Store mutation, or route-count update

#### Scenario: Store receives an ID-only or partial-key Route
- **WHEN** Upsert or Delete is called without both explicit ObjectKey fields
- **THEN** the Store returns invalid and creates no record, active index, or deletion fence

#### Scenario: Peer sends a partial or malformed upsert
- **WHEN** exactly one ObjectKey field is present, the ID is empty, a full Route lacks UID or resourceVersion, or resourceVersion is not a well-formed positive integer
- **THEN** the peer endpoint returns `400 Bad Request` without Store mutation

#### Scenario: Peer sends a minimal explicit-key deletion
- **WHEN** a deletion Route carries namespace, name, and a valid resourceVersion but omits ID and UID
- **THEN** Delete accepts it and ignores fields unrelated to ObjectKey/RV

#### Scenario: Peer sends a malformed deletion
- **WHEN** a deletion Route has a partial ObjectKey or empty ID/object shape, or an explicit-key deletion has a missing or malformed resourceVersion
- **THEN** the peer endpoint returns `400 Bad Request` without Store mutation

#### Scenario: Stale peer event arrives
- **WHEN** a well-formed full event is older than or equal to current ObjectKey state
- **THEN** it is an idempotent no-op and the peer endpoint returns `204 No Content`

#### Scenario: Authoritative deletion arrives
- **WHEN** a deletion Route carries an ObjectKey and a resourceVersion equal to or newer than current state
- **THEN** one Store transaction removes the current stored ID and record and installs that resourceVersion as the deletion fence

#### Scenario: Stale deletion arrives
- **WHEN** a deletion Route carries a resourceVersion older than the current record or fence
- **THEN** the Store ignores it without removing or reviving a route

#### Scenario: Authoritative delete has no prior state
- **WHEN** a Kubernetes deletion event carries a non-empty resourceVersion for an ObjectKey absent from the Store
- **THEN** the Store creates a deletion fence so a delayed peer upsert cannot resurrect the route

#### Scenario: Empty-resourceVersion tombstone removes a record
- **WHEN** a DeletedFinalStateUnknown deletion has a valid ObjectKey and the Store has a current record
- **THEN** deletion uses the record's resourceVersion as the fence and never stores an empty value

### Requirement: Informer-driven route deletion fencing
Manager and gateway SHALL subscribe directly to Sandbox informer Add, Update, and Delete events and
SHALL apply namespace and selector as informer observation filters, and SHALL construct complete
Upsert or Delete mutations before discarding each visible event object. Route maintenance SHALL NOT
query an APIReader or run a route Repairer.

#### Scenario: Sandbox is outside the observation scope
- **WHEN** a Sandbox does not match the configured informer namespace or selector
- **THEN** it does not reach the informer route handler, and that feeder does not Upsert it or create an initial deletion fence

#### Scenario: Visible Sandbox is not Running
- **WHEN** an informer-visible Sandbox has no deletionTimestamp and is not Running
- **THEN** the adapter projects and Upserts its Route, while the request path continues to reject traffic to it

#### Scenario: Sandbox stops matching the selector
- **WHEN** a previously observed Sandbox update moves outside the informer selector
- **THEN** the filtering informer emits a normal DELETE carrying that update resourceVersion and the Store removes the tracked Route

#### Scenario: Sandbox matches the selector again
- **WHEN** a later Sandbox update re-enters the informer observation scope
- **THEN** its newer resourceVersion crosses the deletion fence and the Store Upserts the Route

#### Scenario: Deletion timestamp is observed
- **WHEN** Add or Update observes a Sandbox with a non-empty deletionTimestamp
- **THEN** the adapter emits Delete with that object's current resourceVersion

#### Scenario: Final delete object is available
- **WHEN** a normal DELETE contains the Sandbox object
- **THEN** the adapter preserves its ObjectKey and resourceVersion in Delete

#### Scenario: DeletedFinalStateUnknown is received
- **WHEN** DeletedFinalStateUnknown contains a valid tombstone ObjectKey, with or without an embedded Sandbox object
- **THEN** the adapter ignores any embedded object resourceVersion and emits an empty-resourceVersion Delete as a best-effort fallback

#### Scenario: Initial informer synchronization is in progress
- **WHEN** initial LIST Add events arrive before gateway readiness
- **THEN** Registry mutations succeed while production reads remain gated until the handler registration reports synchronized

#### Scenario: Multiple Sandbox handlers are registered
- **WHEN** quota and route subscriptions coexist
- **THEN** cache health requires every active registration to be synchronized and removing one registration removes it from health aggregation

#### Scenario: A deletion fence remains unused
- **WHEN** no newer Route for its ObjectKey arrives
- **THEN** the fence remains in memory without periodic cleanup or API-server verification

### Requirement: Authorized E2B resource diagnostics
E2B SHALL add protected namespace/name context to successful metadata and downstream errors only after Sandbox lookup and ownership authorization succeed, and MUST NOT disclose that context in not-found or unauthorized responses.

#### Scenario: Authorized successful response exposes metadata
- **WHEN** an authorized E2B response exposes Sandbox metadata
- **THEN** it adds `e2b.agents.kruise.io/sandbox-resource: <namespace>/<name>` after filtering ordinary metadata

#### Scenario: User attempts to spoof protected metadata
- **WHEN** a label extension supplies the Sandbox-ID key or the response-only resource key
- **THEN** E2B rejects the input before either key can be persisted or override generated response context

#### Scenario: Authorized downstream operation fails
- **WHEN** lookup and ownership authorization succeeded before a runtime, gateway, checkpoint, or lifecycle failure
- **THEN** the error retains its classification and appends `sandboxResource=<namespace>/<name>`

#### Scenario: Lookup or authorization fails
- **WHEN** the Sandbox is not found or ownership authorization fails
- **THEN** the response does not disclose namespace or name

### Requirement: Point-in-time Checkpoint and opaque pagination identity
Checkpoint creation SHALL persist the non-empty final Sandbox ID supplied by manager core at creation time, and pagination SHALL use the resolved ID as an opaque uniqueness component without parsing or historical rewriting.

#### Scenario: Sandbox transitions after a Checkpoint
- **WHEN** an unlabeled recycled Sandbox receives a short ID after an earlier Checkpoint was created
- **THEN** the earlier Checkpoint retains its legacy source ID and later Checkpoints use the short ID

#### Scenario: Empty Checkpoint identity is supplied
- **WHEN** infra receives an empty SandboxID for Checkpoint creation
- **THEN** it rejects persistence

#### Scenario: ID changes between list calls
- **WHEN** a Sandbox transitions between paginated list requests
- **THEN** pagination accepts the mutable opaque key behavior and does not retain a second identity

### Requirement: Staged activation and rollback boundary
Operators MUST roll out label-aware manager and gateway binaries with assignment disabled and MUST
drain old replicas/retries and satisfy informer cache health gates before enabling
new short-ID assignment. The system SHALL treat completion of this protocol as a trusted
correctness precondition: after activation no old binary or its delayed/retry peer traffic is
supported, and rollback to such a binary is prohibited.

#### Scenario: Initial binary rollout
- **WHEN** no Sandbox already carries a short-ID label and assignment remains disabled
- **THEN** manager and gateway may roll out in either order while new receivers ignore old ID-only peer messages and their own informer List/Watch eventually converges route state, accepting a brief missing route or stale state/IP before convergence

#### Scenario: Activation readiness is incomplete
- **WHEN** any old replica or retry traffic remains or an informer handler is not synchronized
- **THEN** operators do not enable short-ID assignment

#### Scenario: Assignment has occurred and the flag is disabled
- **WHEN** at least one short label has been persisted and operators turn the feature flag off
- **THEN** new assignments stop but existing labels remain authoritative and rolling back to label-unaware binaries remains unsafe

### Requirement: Bounded identity observability
The implementation SHALL NOT add dedicated Prometheus series for legacy resolution or assignment
success/failure. Shared short-ID Route Store processing and peer compatibility SHALL NOT add
dedicated Prometheus series. Assignment failures SHALL remain observable through existing
PostModifier and claim/clone error logs. Route diagnosis SHALL use structured logs with fixed reason
enums where applicable.

#### Scenario: Identity event has no dedicated metric
- **WHEN** legacy resolution or assignment produces an observable result
- **THEN** the implementation does not emit a dedicated Sandbox ID Prometheus series and retains
  route and retry details in structured logs

#### Scenario: Internal diagnostic is logged
- **WHEN** assignment fails or route mutation requires resource-specific diagnosis
- **THEN** assignment uses existing PostModifier and claim/clone error logs, while route diagnostics may include namespace and name
