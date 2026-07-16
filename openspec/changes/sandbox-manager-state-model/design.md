## Context

`pkg/utils.GetSandboxState` currently derives `creating`, `available`, `running`, `paused`, or `dead` for every component. That apparent consistency hides several different policies:

- SandboxSet needs to know whether a pool member is still creating or is available for claim.
- cache needs pool indexing, active-count, and operation-wait predicates.
- sandbox-manager needs an orchestration view that distinguishes pause/resume progress, temporary unavailability, removal, and completion.
- proxy and Gateway need a forwarding action, not a lifecycle vocabulary.
- E2B exposes only `running` and `paused` and needs stable errors for other observations.

The shared helper therefore both under-describes sandbox-manager state and over-couples components that should not share a state model. In particular, `dead` currently combines deletion, normal completion, failed completion, termination, and a claimed Running Sandbox whose Ready condition is false.

This change makes the internal model a sandbox-manager component contract. It is derived from the Sandbox CR but is not persisted and is not a Controller API. Other components keep only the purpose-specific predicates they require.

## Goals / Non-Goals

**Goals:**

- Cover every state distinction required by sandbox-manager without attempting to represent every Controller phase or condition outcome.
- Return one deterministic state and a non-empty diagnostic reason for every CR observation.
- Keep CR interpretation below the `infra.Sandbox` boundary.
- Preserve existing SandboxSet, pool-index, active-count, claim-selection, quota, and waiter behavior unless this proposal explicitly changes it.
- Remove lifecycle vocabulary from Route and make forwarding/removal policy explicit at the producer.
- Keep internal state out of public E2B response bodies.
- Support mixed-version manager and Gateway rollout while Route changes from `state` to `action`.

**Non-Goals:**

- Adding a lifecycle field to the Sandbox CRD.
- Making Controller, SandboxSet, cache, proxy, or Gateway consume the sandbox-manager state type.
- Adding new Controller phases or in-place update reasons, or changing mutation/retry behavior.
- Distinguishing successful and failed completion in the internal state or public unavailable reason.
- Distinguishing deletion from recycling in the internal state or public unavailable reason.
- Tightening SandboxSet availability with Pod IP, lock, claimed-label, or new health requirements.
- Changing quota liveness, route identity, peer membership, route freshness comparison, or reconciliation topology.

## Decisions

### 1. One sandbox-manager-owned vocabulary

`pkg/sandbox-manager/infra` defines:

```go
type SandboxState string

const (
	SandboxStateClaimable   SandboxState = "claimable"
	SandboxStateRunning     SandboxState = "running"
	SandboxStatePausing     SandboxState = "pausing"
	SandboxStatePaused      SandboxState = "paused"
	SandboxStateResuming    SandboxState = "resuming"
	SandboxStateUnready     SandboxState = "unready"
	SandboxStateTerminating SandboxState = "terminating"
	SandboxStateCompleted   SandboxState = "completed"
)

type SandboxStateObservation struct {
	State  SandboxState
	Reason string
}
```

`infra.Sandbox.GetState()` returns `SandboxStateObservation`. The only production implementation, `sandboxcr.Sandbox`, delegates to an unexported pure function:

```go
func getSandboxState(sbx *v1alpha1.Sandbox, now time.Time) infra.SandboxStateObservation
```

The method supplies the current time; tests call the pure function with an explicit time. No exported CR-to-state function is added. Sandbox-manager and its E2B server path consume the observation through `infra.Sandbox`; Controller, SandboxSet, cache, proxy, and Gateway cannot import or compare these constants.

`Reason` is always non-empty and is intended for logs and protected diagnostics. It is not a stable public enum and must not be returned as the public Sandbox `state`.

### 2. First-match derivation covers manager needs

The first matching rule wins:

| Priority | State | Decisive facts |
|---:|---|---|
| 1 | `terminating` | deletion timestamp; shutdown time is before the observation time; reserved-failed label; accepted cleanup (`cleanup=true` and `cleanup-enabled=true`); or phase `Recycling`/`Terminating` |
| 2 | `completed` | phase `Succeeded` or `Failed` |
| 3 | `resuming` | phase `Resuming`; completed Paused condition with `spec.paused=false`; or exact post-resume initialization gate |
| 4 | `pausing` | `Running` with `spec.paused=true`; or phase `Paused` before the Paused condition is true |
| 5 | `paused` | phase `Paused`, `spec.paused=true`, and Paused condition true |
| 6 | `unready` | phase `Upgrading`, or a currently supported active/unsafe in-place update observation |
| 7 | `claimable` | `sandboxset.IsSandboxAvailable(sbx, now)` |
| 8 | `running` | phase `Running`, not paused, Ready true, Pod IP non-empty, and no higher rule matched |
| 9 | `unready` | every other live observation, including Pending, Ready false/absent, empty Pod IP, empty phase, and unsupported future phase |

Deletion/removal overrides completion because an object being removed is still in progress, not terminal from sandbox-manager's perspective. Only `completed` is terminal. `terminating` is a transition whose end is object absence.

The shutdown comparison preserves current behavior: the deadline is considered reached only when the observation time is after `spec.shutdownTime`.

Reserved-failed is `terminating` even when the raw phase or Ready condition would otherwise map elsewhere. It represents a failed claim artifact waiting for its retention/deletion policy, not a serviceable or completed user Sandbox.

### 3. Pause, resume, and update details are deliberately narrow

Pause and resume remain explicit because manager operations need to join or reject an in-flight transition:

- phase `Resuming` is always `resuming`;
- phase `Paused` with Paused condition true and `spec.paused=false` is `resuming`;
- phase `Running` with `SandboxResumed=True` is `resuming` only when `RuntimeInitialized` exists and is not true;
- phase `Running` with `spec.paused=true` is `pausing`;
- phase `Paused` before Paused condition true is `pausing`;
- phase `Paused` with `spec.paused=true` and Paused condition true is `paused`.

An absent `RuntimeInitialized` condition does not imply resume progress, preventing legacy healthy objects from remaining `resuming` indefinitely.

The post-resume initialization rule intentionally precedes `Running + spec.paused=true` and does not require `spec.paused=false`. Resume is not complete until runtime initialization and Ready convergence finish, so a Pause request in that window is an opposite-direction conflict and returns HTTP 409. This matches the current infra contract, where Resume waits for Ready and Pause rejects Running-but-not-ready. Once initialization finishes, a later pause observation derives `pausing` normally.

The former `upgrading` distinction is folded into `unready`. Phase `Upgrading` and the existing `InplaceUpdate` reasons `InplaceUpdating` or `Failed` are non-serving. `Succeeded` falls through to Ready and Pod-IP evaluation. This change does not add stage-specific update reasons or attempt to exhaustively encode Controller operation outcomes; Ready remains the final service signal after these known unsafe markers.

### 4. SandboxSet owns creating and available

`pkg/controller/sandboxset` exports pure helpers with an explicit observation time:

```go
func IsSandboxCreating(sbx *v1alpha1.Sandbox, now time.Time) bool
func IsSandboxAvailable(sbx *v1alpha1.Sandbox, now time.Time) bool
```

They reproduce the existing five-state helper's creating/available behavior:

- deletion, expired shutdown, `Succeeded`, `Failed`, and `Terminating` are neither creating nor available;
- Pending is creating;
- a SandboxSet-controlled, non-terminal object is available when Ready is true and creating otherwise;
- the available predicate does not require Pod IP, lock availability, or a new claimed-label rule.

SandboxSet grouping and event handling use these helpers plus local used/dead grouping. The pool cache index uses the same helpers. sandboxcr imports the SandboxSet package only from its infra implementation: claim selection uses both helpers, while manager `claimable` derivation uses only `IsSandboxAvailable` after higher-priority manager rules.

Claim selection retains its independent resource-version, candidate precheck, Pod-IP, lock, speculation duration, and revision-preference checks. Naming a manager state `claimable` does not replace those atomic claim safeguards.

### 5. Other non-manager consumers retain local policy

`pkg/utils.GetSandboxState` is removed rather than redirected to the new model. The five `api/v1alpha1.SandboxState*` strings are removed after all uses migrate. Generic low-level helpers such as Ready-condition lookup and SandboxSet controller ownership may remain shared; `pkg/utils/lifecycle` does not own or alias the sandbox-manager vocabulary, and its package guidance explicitly prohibits doing so.

Behavior-preserving migrations are local:

- `CountActiveSandboxes` keeps the current reserved-failed and legacy-dead exclusion policy; it does not become claimed-only in this change.
- pool indexing retains the current creating-or-available behavior.
- SandboxSet grouping, status, rolling update, and event enqueue behavior remain unchanged.
- waiters use their required CR facts and operation-specific fast failures without importing manager state.
- `IsLiveForQuota` remains an independent policy.

### 6. Recycle eligibility is an infra capability

The `infra.Sandbox` interface replaces `IsRecycleEnabled()` and `Phase()` with:

```go
IsRecyclable() bool
```

`sandboxcr.Sandbox.IsRecyclable()` preserves the current combined predicate: cleanup is enabled and the raw phase is `Running`. Sandbox-manager still performs the existing trigger-recycle, metric, and fallback-to-delete flow, but it no longer reads Controller phase or combines raw facts itself.

After cleanup is accepted, state observation reports `terminating` regardless of whether the Controller implements removal through recycling or direct deletion.

### 7. Route carries action, not lifecycle

The core Route replaces `State string` with:

```go
type RouteAction string

const (
	RouteActionAllow  RouteAction = "allow"
	RouteActionDeny   RouteAction = "deny"
	RouteActionDelete RouteAction = "delete"
)
```

Route metadata projection no longer derives lifecycle or action. Each producer explicitly assigns Action before local mutation or peer synchronization:

| Manager observation | Action |
|---|---|
| `running` | `Allow` |
| `claimable`, `pausing`, `paused`, `resuming`, `unready` | `Deny` |
| `terminating`, `completed` | `Delete` |

Gateway cannot consume manager state. Its local CR policy selects:

- `Delete` for deletion timestamp, expired shutdown, reserved-failed, accepted cleanup, or phase `Recycling`, `Terminating`, `Succeeded`, or `Failed`;
- `Allow` for a non-SandboxSet-controlled phase `Running` object that is not paused, has Ready true and a non-empty Pod IP, and has no active unsafe update marker;
- `Deny` for every other live observation.

`Allow` and `Deny` are retained route records; data planes forward only `Allow`. `Delete` invokes deletion and is never stored as an active Route. Missing or unknown Action is invalid after compatibility decoding and must not mutate a route or enable forwarding.

### 8. Mixed-version Route wire compatibility is isolated

Core Route logic never reads lifecycle `state`. A wire adapter temporarily emits both `action` and a legacy top-level `state` field:

| Action | Legacy field sent |
|---|---|
| `Allow` | `running` |
| `Deny` | `paused` |
| `Delete` | `dead` |

New receivers treat a present valid Action as authoritative. When Action is absent:

- sandbox-manager/proxy maps legacy `dead` to Delete, `running` to Allow, and every other value to Deny;
- Gateway maps legacy `running` to Allow and every other value to Delete, preserving its current refresh behavior.

Compatibility decoding happens before validation and store mutation. The legacy field is not copied into the core Route and is not consulted by data-plane filters. Existing resource-version comparison, registry/store ownership, peer selection, and reconciliation behavior are unchanged.

### 9. E2B remains a two-state public projection

Only the sandbox-manager/E2B path consumes `SandboxStateObservation`. Public projection is:

| Internal state | Public result |
|---|---|
| `running` | Sandbox state `running` |
| `pausing`, `paused`, `resuming` | Sandbox state `paused` |
| `claimable`, `unready` | unrepresentable, `SandboxTemporarilyUnavailable` |
| `terminating` | unrepresentable, `SandboxTerminating` |
| `completed` | unrepresentable, `SandboxCompleted` |
| confirmed absence | `SandboxNotFound` |

`web.ApiError` gains `Reason string` serialized as `reason,omitempty`. These four strings are the only stable lifecycle-unavailable reasons. Internal state and diagnostic reason may appear in protected logs/messages after ownership succeeds but never in the public Sandbox state field.

The public enum is stable, but observation behavior is not fully backward compatible. The current shared helper treats claimed Upgrading, Recycling, empty-phase, and unsupported-phase Sandboxes as `paused`, so Describe/List may expose them with HTTP 200. The new policy maps Upgrading/empty/unsupported observations to `unready` and Recycling to `terminating`; direct representation becomes the applicable reasoned HTTP 404 and List omits them. Migration tests must lock this intentional 200-to-404 change for SDK polling behavior.

Lifecycle filtering is removed from `SandboxManager.GetSandbox` and `getSandboxOfUser`; this includes the current reserved-failed label short-circuit in the shared E2B lookup. Lookup first establishes existence and ownership, then GetState and the requested E2B operation handle the observation. Describe therefore maps reserved-failed to `SandboxTerminating`, while Delete reaches and accepts the real removal path instead of treating the lookup error itself as deletion success. Confirmed absence remains distinct from backend, timeout, cancellation, and authorization failures.

Operation policy remains:

- Pause accepts `running`, `pausing`, and `paused`; Resume accepts `paused`, `resuming`, and `running`.
- Same-direction requests join existing waits; opposite pause/resume progress returns HTTP 409.
- Connect returns `running` directly, starts or joins Resume for `paused`/`resuming`, and rejects `pausing` with HTTP 400.
- Snapshot and timeout mutation require `running`.
- Create, Clone, Resume, and Connect return a Sandbox body only after a refreshed `running` observation.
- Delete accepts every state of an owned Sandbox and confirmed/concurrent absence, preserving authorization and non-NotFound backend failures.

### 10. Alternatives considered

- **Shared canonical lifecycle under `pkg/utils/lifecycle`: rejected.** It would continue coupling controller/cache policy to manager needs and encourage new consumers to treat one vocabulary as universal.
- **Eleven states mirroring Controller progress: rejected.** Separate creating/available, upgrading, recycling, succeeded, and failed states express Controller or pool detail that upper manager policy intentionally merges.
- **Three independently deployable changes: rejected.** The reduced design would require an unused model, temporary tuple/struct adapters, and partial route migration. One atomic change is smaller and prevents mixed state semantics inside a binary.
- **Tuple `GetState() (state, reason)`: rejected.** A named observation makes the boundary extensible and prevents callers from silently discarding the association between normalized state and its diagnostic.
- **Keep raw `Phase()` for recycle: rejected.** `IsRecyclable()` preserves behavior while keeping Controller phase interpretation inside sandboxcr.
- **Keep lifecycle state in Route: rejected.** Proxy and Gateway need an explicit forwarding/removal decision, not knowledge of manager lifecycle semantics.
- **Treat every non-running Route as Delete: rejected.** Deny preserves a live but unavailable record and distinguishes temporary unavailability from authoritative removal.
- **Hard Route wire cutover: rejected.** Dual-field encoding allows rolling upgrades while keeping the legacy field outside core logic.
- **Tighten SandboxSet available to require Pod IP or lock: rejected.** That would change pool/controller behavior; atomic claim checks remain the correct place for those safeguards.
- **Add stage-specific Controller update reasons: rejected.** The manager model needs only serviceable versus unready, and existing phase/Ready/update facts are sufficient for this change.

## Risks / Trade-offs

- **[Risk] `claimable` sounds stronger than the legacy available predicate.** -> Document that atomic claim still performs Pod-IP, expectation, lock, and candidate checks; do not tighten the shared pool helper implicitly.
- **[Risk] A new Controller phase is accidentally served.** -> Unknown and empty phases fall through to `unready`; Gateway's Allow predicate requires exact `Running` plus service facts.
- **[Risk] A half-migrated binary compares manager states outside the manager path.** -> Implement the interface switch, consumer migration, Route action, and legacy-helper removal in one change; add source/import inventory checks.
- **[Risk] Route deletion is persisted as an active entry.** -> Reject Delete in upsert paths and test that it only invokes deletion.
- **[Risk] Mixed-version peers disagree about non-running routes.** -> Keep component-specific legacy decode semantics and send both fields during rollout.
- **[Risk] Public clients receive new internal strings.** -> Centralize projection and assert response bodies contain only `running`/`paused`.
- **[Trade-off] Completion cause is lost in state.** -> Preserve phase and diagnostic reason inside sandboxcr logs; upper policy intentionally uses one `completed` outcome.
- **[Trade-off] Recycling is indistinguishable from deletion.** -> Preserve recycle metrics and fallback behavior as operation details while state and public errors use `terminating`.

## Migration Plan

1. Add the infra vocabulary, observation type, private explicit-time derivation, SandboxSet helpers, and focused tests without adding a shared canonical package.
2. Migrate SandboxSet, cache, claim selection, waiters, and recycle capability while preserving their current local behavior.
3. Add RouteAction, producer policies, compatibility wire adapters, storage/data-plane handling, and route tests.
4. Atomically switch `infra.Sandbox.GetState`, sandbox-manager, and E2B projection/operations; add stable error reasons.
5. Remove the legacy helper/constants and raw phase/recycle methods, run generated-artifact checks required by the API package edit, then complete focused tests, static checks, and final component builds.

No stored CRD migration is required. Stable running and paused observations remain compatible, while the documented legacy paused fallbacks change to unavailable responses and require rollout regression coverage. Route compatibility supports rolling component replacement; the legacy wire field can be removed in a separate compatibility cleanup after the supported mixed-version window ends.

## Open Questions

None. The vocabulary, precedence, component boundaries, Route action, compatibility mapping, public projection, and behavior-preservation constraints are fixed.
