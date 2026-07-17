## ADDED Requirements

### Requirement: Public Sandbox state remains running or paused
E2B Sandbox responses SHALL expose only public `running` or `paused`. Internal `running` SHALL project to `running`; `pausing`, `paused`, and `resuming` SHALL project to `paused`; `claimable`, `unready`, `terminating`, and `completed` SHALL be unrepresentable. Only Manager SHALL consume provider `SandboxStateObservation`; E2B SHALL consume a protocol-independent lifecycle outcome through the Manager interface and MUST NOT import provider/infra or inspect CR phase and conditions.

#### Scenario: Running projects to running
- **WHEN** Manager returns the protocol-independent outcome corresponding to internal `running`
- **THEN** its public state is `running`

#### Scenario: Paused family projects to paused
- **WHEN** Manager returns an outcome corresponding to internal `pausing`, `paused`, or `resuming`
- **THEN** its public state is `paused`

#### Scenario: API does not bypass Manager
- **WHEN** E2B performs lookup, projection, or a lifecycle operation
- **THEN** it calls the Manager interface and does not call provider GetState or Manager infra

#### Scenario: List omits unrepresentable state
- **WHEN** List Sandboxes encounters `claimable`, `unready`, `terminating`, or `completed`
- **THEN** it omits that Sandbox rather than leaking the internal state

#### Scenario: Paused filter includes transition family
- **WHEN** List Sandboxes filters for public `paused`
- **THEN** it includes internal `pausing`, `paused`, and `resuming`

#### Scenario: Successful body is refreshed running
- **WHEN** Create, Clone, or Connect returns a successful Sandbox body
- **THEN** a refreshed observation is `running` and the public state is `running`

#### Scenario: Legacy paused fallback becomes unavailable
- **WHEN** a claimed Upgrading, Recycling, empty-phase, or unsupported-phase Sandbox would previously have been returned as public `paused`
- **THEN** List omits it and direct representation returns the applicable HTTP 404 reasoned unavailable response instead of HTTP 200

### Requirement: Manager lifecycle lookup does not pre-filter state
The Manager lookup used by E2B SHALL establish existence and ownership without an expected-state parameter, state whitelist, or reserved-failed label short-circuit. Manager lifecycle policy and the API projection SHALL run only after lookup and authorization. Confirmed absence SHALL remain distinct from backend, timeout, cancellation, and authorization failures.

#### Scenario: Found unready Sandbox reaches policy
- **WHEN** an owned Sandbox exists and its observation is `unready`
- **THEN** lookup returns it to lifecycle policy instead of converting a whitelist miss into absence

#### Scenario: Reserved failed Sandbox reaches policy
- **WHEN** an owned Sandbox exists with the reserved-failed label
- **THEN** shared lookup returns it so GetState derives `completed` unless a higher removal fact
  applies, and the requested operation applies its own policy

#### Scenario: Backend failure is not absence
- **WHEN** the cache or API lookup fails without confirmed NotFound
- **THEN** E2B returns the mapped non-404 server error and does not label it `SandboxNotFound`

#### Scenario: Ownership failure remains protected
- **WHEN** the Sandbox exists but belongs to another user
- **THEN** the existing authorization response is preserved without exposing lifecycle or resource details

### Requirement: Lifecycle unavailability has four stable reasons
`web.ApiError` SHALL add `Reason string` serialized as `reason,omitempty`. Direct Sandbox representation of confirmed absence or an unrepresentable lifecycle observation SHALL return HTTP 404 and SHALL use only `SandboxNotFound`, `SandboxTemporarilyUnavailable`, `SandboxCompleted`, or `SandboxTerminating`. Operation-specific conflicts and rejections retain their separately specified status. Existing error fields and unrelated errors SHALL remain compatible.

#### Scenario: Confirmed absence
- **WHEN** claimed-Sandbox lookup confirms no Sandbox exists
- **THEN** the response is HTTP 404 with reason `SandboxNotFound`

#### Scenario: Live but unavailable
- **WHEN** an operation cannot represent `claimable` or `unready`
- **THEN** direct representation is HTTP 404 with reason `SandboxTemporarilyUnavailable`

#### Scenario: Completed Sandbox
- **WHEN** an operation cannot represent `completed`
- **THEN** direct representation is HTTP 404 with reason `SandboxCompleted` regardless of successful or failed raw completion

#### Scenario: Removal in progress
- **WHEN** an operation cannot represent `terminating`
- **THEN** direct representation is HTTP 404 with reason `SandboxTerminating` regardless of deletion or recycling mechanism

#### Scenario: Reserved failed Sandbox
- **WHEN** an owned Sandbox is retained with the reserved-failed label
- **THEN** it is observed as `completed` before removal starts and direct representation is HTTP 404
  with reason `SandboxCompleted`, not `SandboxNotFound`

#### Scenario: Unrelated error
- **WHEN** an error is not a Sandbox lifecycle unavailable response
- **THEN** reason may be omitted and existing code, headers, message, and request-id behavior remains unchanged

### Requirement: Pause and Resume are directionally idempotent
Pause SHALL accept `running`, `pausing`, and `paused`. Resume SHALL accept `paused`, `resuming`, and `running`. A same-direction request during progress SHALL join the existing wait without replacing first-writer parameters; an opposite-direction request during progress SHALL return HTTP 409. Resume SHALL preserve its existing empty HTTP 204 success response and SHALL complete that response only after a refreshed observation is `running`.

#### Scenario: Repeated Pause joins progress
- **WHEN** Pause is requested for `pausing`
- **THEN** it joins pause completion without a competing mutation

#### Scenario: Pause is already complete
- **WHEN** Pause is requested for `paused`
- **THEN** it succeeds without starting another pause

#### Scenario: Repeated Resume joins progress
- **WHEN** Resume is requested for `resuming`
- **THEN** it joins resume completion without a competing mutation

#### Scenario: Resume is already complete
- **WHEN** Resume is requested for `running`
- **THEN** it returns the existing empty HTTP 204 success without starting another resume

#### Scenario: Resume progress completes
- **WHEN** Resume starts or joins progress
- **THEN** it returns the existing empty HTTP 204 success only after refreshed `running`

#### Scenario: Opposite transition conflicts
- **WHEN** Pause sees `resuming` or Resume sees `pausing`
- **THEN** the response is HTTP 409

### Requirement: Connect handles the paused family explicitly
Connect SHALL return `running` without starting Resume, start or join Resume for `paused` or `resuming`, and reject `pausing` with HTTP 400. A successful response MUST contain public state `running` after refreshed observation.

#### Scenario: Connect running Sandbox
- **WHEN** Connect observes `running`
- **THEN** it applies existing timeout policy and returns public `running`

#### Scenario: Connect paused Sandbox
- **WHEN** Connect observes `paused`
- **THEN** it starts Resume and returns only after refreshed `running`

#### Scenario: Connect resuming Sandbox
- **WHEN** Connect observes `resuming`
- **THEN** it joins Resume and returns only after refreshed `running`

#### Scenario: Connect pausing Sandbox
- **WHEN** Connect observes `pausing`
- **THEN** it returns HTTP 400 without starting the opposite transition

### Requirement: Running-only operations require running
Snapshot creation and timeout mutation SHALL accept only internal `running`. Create and Clone response paths SHALL return a Sandbox body only after refreshed `running`; other observations SHALL use the approved lifecycle unavailable mapping or existing operation error.

#### Scenario: Snapshot sees unready
- **WHEN** Snapshot creation observes `unready`
- **THEN** it does not create a checkpoint and returns the approved unavailable result

#### Scenario: Timeout sees paused
- **WHEN** timeout mutation observes `paused`
- **THEN** it preserves the existing running-only rejection

### Requirement: Delete is idempotent for every state
Delete SHALL accept every internal state of an owned Sandbox and return HTTP 204 after direct deletion or recycle is accepted. Confirmed absence and concurrent NotFound SHALL also return 204. Authorization and non-NotFound backend failures MUST remain errors.

#### Scenario: Delete existing Sandbox
- **WHEN** Delete is requested for an owned Sandbox in any of the eight states
- **THEN** the applicable removal flow is accepted and the response is HTTP 204

#### Scenario: Delete reserved failed Sandbox
- **WHEN** Delete is requested for an owned reserved-failed Sandbox
- **THEN** shared lookup does not short-circuit, actual deletion is accepted, and the response is HTTP 204

#### Scenario: Delete confirmed absence
- **WHEN** lookup confirms the Sandbox is absent
- **THEN** Delete returns HTTP 204

#### Scenario: Delete races with another remover
- **WHEN** the Sandbox disappears after lookup and deletion receives NotFound
- **THEN** Delete returns HTTP 204

#### Scenario: Delete preserves failure boundaries
- **WHEN** ownership fails or a backend error other than NotFound occurs
- **THEN** Delete returns the existing mapped error rather than HTTP 204
