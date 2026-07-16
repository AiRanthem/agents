## ADDED Requirements

### Requirement: Public Sandbox state remains a two-value projection
E2B responses SHALL expose only public `running` or `paused`. Internal `running` SHALL map to public `running`; internal `pausing`, `paused`, and `resuming` SHALL map to public `paused`; every other internal state SHALL be unrepresentable. Projection SHALL consume the normalized infra lifecycle observation and MUST NOT inspect Sandbox CR phase or conditions. Sandbox identity SHALL remain manager-resolved and opaque; E2B MUST NOT call an infra ID/Route accessor or parse the client ID.

#### Scenario: Running projects to running
- **WHEN** an E2B response represents an internal `running` Sandbox
- **THEN** its public state is `running`

#### Scenario: Paused family projects to paused
- **WHEN** an E2B response represents internal `pausing`, `paused`, or `resuming`
- **THEN** its public state is `paused`

#### Scenario: List omits unrepresentable states
- **WHEN** List Sandboxes encounters `creating`, `available`, `upgrading`, `recycling`, `terminating`, `succeeded`, or `failed`
- **THEN** it omits those objects rather than exposing an internal state

#### Scenario: Paused filter includes the paused family
- **WHEN** List Sandboxes uses the public `state=paused` filter
- **THEN** it includes internal `pausing`, `paused`, and `resuming` objects

#### Scenario: Successful body waits for running
- **WHEN** Create, Clone, Resume, or Connect returns a successful Sandbox body
- **THEN** refreshed internal state is `running` and public state is `running`

#### Scenario: Reserved failed CR is never projected as running
- **WHEN** a claimed CR is retained with the reserved-failed marker after a failed claim
- **THEN** it is unrepresentable regardless of its otherwise-derived lifecycle state

### Requirement: Lookup does not pre-filter lifecycle through expected-state whitelists
E2B `getSandboxOfUser` and `SandboxManager.GetSandbox` SHALL NOT accept or apply `expectedStates`, `claimedSandboxStates`, or `liveSandboxStates` whitelists. Lookup SHALL establish confirmed existence, claim identity, and ownership before normalized lifecycle projection or operation gating classifies availability.

#### Scenario: Found transitional CR reaches lifecycle classification
- **WHEN** a claimed owned CR exists in `creating`, `pausing`, `resuming`, or `upgrading`
- **THEN** lookup returns the Sandbox observation to the projection/operation policy instead of converting a whitelist miss directly to NotFound

#### Scenario: Confirmed absence remains distinct
- **WHEN** opaque claimed-ID lookup produces a clean indexed absence or cache-hit APIReader confirmation
- **THEN** the absence classification reaches the HTTP mapper without being conflated with an unrepresentable found state

#### Scenario: Opaque-ID ambiguity is not absence
- **WHEN** the short-ID claimed index finds multiple Sandbox objects for one client ID
- **THEN** the fail-closed ambiguity classification reaches a non-404 mapper without selecting an object or parsing the ID

### Requirement: Every Sandbox lifecycle 404 has a stable reason
Every HTTP 404 caused by claimed-Sandbox lookup or an internal state that is unrepresentable for the requested Sandbox operation SHALL include a non-empty JSON `reason` on the runtime `web.ApiError`. The only allowed values are `SandboxNotFound`, `SandboxTemporarilyUnavailable`, `SandboxSucceeded`, `SandboxFailed`, `SandboxTerminating`, and `SandboxRecycling`. Existing `web.ApiError` fields `code`, `headers`, `message`, and `request_id` SHALL retain their current behavior; the separate two-field `models.Error` SHALL NOT replace the runtime handler error body.

#### Scenario: Confirmed absence is the only NotFound reason
- **WHEN** CR lookup confirms that the claimed Sandbox is absent or the named CR is not claimed
- **THEN** the API returns 404 with `reason=SandboxNotFound`

#### Scenario: Temporary lifecycle unavailability is explicit
- **WHEN** a direct operation cannot represent internal `creating`, `available`, or `upgrading`
- **THEN** the API returns 404 with `reason=SandboxTemporarilyUnavailable`

#### Scenario: Successful completion is explicit
- **WHEN** a direct operation cannot represent internal `succeeded`
- **THEN** the API returns 404 with `reason=SandboxSucceeded`

#### Scenario: Failed completion is explicit
- **WHEN** a direct operation cannot represent internal `failed`
- **THEN** the API returns 404 with `reason=SandboxFailed`

#### Scenario: Reserved claim failure is found, not absent
- **WHEN** a claimed CR exists with the reserved-failed marker
- **THEN** a direct operation that requires representation returns 404 with `reason=SandboxFailed`, not `SandboxNotFound`

#### Scenario: Termination is explicit
- **WHEN** a direct operation cannot represent internal `terminating`
- **THEN** the API returns 404 with `reason=SandboxTerminating`

#### Scenario: Recycling is explicit
- **WHEN** a direct operation cannot represent internal `recycling`
- **THEN** the API returns 404 with `reason=SandboxRecycling`

#### Scenario: Found-but-unavailable message retains context
- **WHEN** a CR was found but lifecycle state produces a 404
- **THEN** the reason is not `SandboxNotFound` and the message includes internal state and diagnostic reason

#### Scenario: Authorized unavailable error may include resource context
- **WHEN** claimed lookup and ownership authorization succeeded before a found lifecycle state produces a 404
- **THEN** the response may include short-ID's protected `sandboxResource=<namespace>/<name>` diagnostic context

#### Scenario: Absence and unauthorized errors do not disclose resource context
- **WHEN** lookup returns `SandboxNotFound`, opaque-ID ambiguity, or ownership authorization failure
- **THEN** the response does not include namespace/name or protected sandbox-resource context

#### Scenario: Backend failure is not a lifecycle 404
- **WHEN** cache, APIReader, timeout, cancellation, or transport lookup fails without confirmed absence
- **THEN** the API returns the mapped non-404 server error and does not label it `SandboxNotFound`

#### Scenario: Unrelated errors remain compatible
- **WHEN** an error is not a Sandbox lifecycle-related 404
- **THEN** `reason` may be omitted and existing `code` and `message` behavior remains unchanged

### Requirement: Pause and Resume are directionally idempotent
Pause SHALL accept `running`, `pausing`, and `paused`. Resume SHALL accept `paused`, `resuming`, and `running`. A same-direction request during progress SHALL join the existing wait without replacing first-writer parameters; an opposite-direction request during progress SHALL return HTTP 409, which is included in the upstream E2B OpenAPI response set for both endpoints.

#### Scenario: Repeated Pause joins pausing
- **WHEN** Pause is requested for a Sandbox already `pausing`
- **THEN** it performs no competing mutation, joins pause completion, and succeeds when paused

#### Scenario: Pause is already complete
- **WHEN** Pause is requested for a Sandbox already `paused`
- **THEN** it succeeds without starting another pause

#### Scenario: Repeated Resume joins resuming
- **WHEN** Resume is requested for a Sandbox already `resuming`
- **THEN** it performs no competing mutation, joins the running wait, and succeeds when running

#### Scenario: Resume is already complete
- **WHEN** Resume is requested for a Sandbox already `running`
- **THEN** it succeeds without starting another resume

#### Scenario: Pause conflicts with resume progress
- **WHEN** Pause is requested for a Sandbox `resuming`
- **THEN** the API returns HTTP 409

#### Scenario: Resume conflicts with pause progress
- **WHEN** Resume is requested for a Sandbox `pausing`
- **THEN** the API returns HTTP 409

### Requirement: Connect handles paused-family states explicitly
Connect SHALL return an already-running Sandbox without starting Resume, SHALL start or join Resume for `paused` or `resuming`, and SHALL reject `pausing` with HTTP 400, which is included in the upstream E2B OpenAPI response set for Connect while 409 is not. A successful response MUST contain public state `running`.

#### Scenario: Connect running Sandbox
- **WHEN** Connect is requested for internal `running`
- **THEN** it applies existing timeout policy and returns public `running` without starting Resume

#### Scenario: Connect paused Sandbox
- **WHEN** Connect is requested for internal `paused`
- **THEN** it starts Resume, waits for refreshed internal `running`, and returns public `running`

#### Scenario: Connect resuming Sandbox
- **WHEN** Connect is requested for internal `resuming`
- **THEN** it joins the Resume wait and returns only after refreshed internal `running`

#### Scenario: Connect pausing Sandbox
- **WHEN** Connect is requested for internal `pausing`
- **THEN** it returns HTTP 400 and does not start the opposite transition

### Requirement: Delete is idempotent without hiding authorization or backend failure
Delete SHALL accept every lifecycle state of an owned claimed Sandbox and return HTTP 204 after deletion or recycling is accepted. Confirmed absence and a concurrent NotFound during deletion SHALL also return 204. Ownership and non-NotFound backend failures MUST remain errors.

#### Scenario: Delete any existing lifecycle state
- **WHEN** Delete is requested for an owned claimed Sandbox in any derived state
- **THEN** deletion or cleanup is accepted as applicable and the API returns 204

#### Scenario: Delete confirmed missing Sandbox
- **WHEN** lookup confirms the claimed Sandbox is absent
- **THEN** Delete returns 204 rather than a 404

#### Scenario: Concurrent deletion completes first
- **WHEN** the Sandbox disappears after lookup and deletion receives NotFound
- **THEN** Delete returns 204

#### Scenario: Delete preserves ownership failure
- **WHEN** the CR exists but belongs to another user
- **THEN** Delete returns the existing authorization failure

#### Scenario: Delete preserves backend failure
- **WHEN** lookup or deletion fails for a reason other than confirmed NotFound
- **THEN** Delete returns the mapped error rather than 204
