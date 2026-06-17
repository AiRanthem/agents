# API Key Sandbox Quota — Design Spec

- Date: 2026-06-17
- Branch: `feature/e2b-api-quota-260617`
- Scope: `pkg/servers/e2b/` (create, api_key, models, keys, routes), `pkg/servers/e2b/quota/` (new), `pkg/sandbox-manager/` (api, infra wiring), `pkg/cache/`, `pkg/proxy/` (peer transport reuse), `cmd/sandbox-manager/`, `api/v1alpha1/` (owner label constant), `config/`/Helm chart (RBAC for `coordination.k8s.io/leases`)
- Ownership model: per-shard Kubernetes `Lease` leader election (`k8s.io/client-go/tools/leaderelection`, already vendored) — not a hand-rolled hash ring.

## 1. Background

sandbox-manager is a stateless, multi-replica backend exposing E2B/MCP APIs to manage sandboxes. Each request authenticates via `X-API-KEY`, resolved to a `*models.CreatedTeamAPIKey` (with `ID uuid.UUID` and `Team`). That `ID` is the sandbox **owner**: every create path stamps it onto the Sandbox CR as `agentsv1alpha1.AnnotationOwner` (claim and create-on-no-stock via `utils.LockSandbox`, clone via direct set), and it surfaces as `route.Owner`.

We need to cap how many sandboxes a single API key may hold, enforced **without overselling** (beyond a tiny, self-healing residual under a rare failure intersection — see §8) even under highly concurrent creates across replicas, and **without materially slowing down create**. Peak create throughput is ~2500/sec (150k/min) aggregate. The worst case for a single limited key is "small limit + high churn" (a key that constantly creates and deletes against a tiny limit), which rules out any per-operation external IO on the hot path.

Phase 1 exposes only a per-key **sandbox count** limit, but the internal model must extend to future dimensions (CPU, memory) and scopes (per-team, per-template, api-key+template).

### Key facts established from the codebase

- `pkg/cache` already maintains a `user` field index (`IndexUser`) over `AnnotationOwner` on Sandbox/Checkpoint, plus `ListSandboxes({User})` and `CountActiveSandboxes({User})`, and exposes `GetAPIReader()` — a `client.Reader` that bypasses the lagging local informer for a consistent apiserver read.
- `CountActiveSandboxes` **excludes** `Dead` (`cache.go:306`). Its only production caller is the SandboxClaim controller's `countClaimedSandboxes` (`common_control.go:408`), which relies on Dead being excluded so a dead sandbox triggers a replacement. **It must not be modified.**
- `AnnotationOwner` is an **annotation** (`api/v1alpha1`, `InternalPrefix + "owner"`). Annotations are not server-side selectable, so a consistent per-owner read cannot filter on it. We add a mirrored **owner label** to enable `apiReader.List(MatchingLabels{...})` server-side filtering (§5).
- `k8s.io/client-go/tools/leaderelection` (with `resourcelock/leaselock.go`, backed by `coordination.k8s.io/Lease`) is **already vendored** and is the battle-tested ownership primitive used across the controller ecosystem. We use it for shard ownership instead of a hand-rolled ring.
- Peer-to-peer transport already exists: `pkg/proxy` runs an HTTP server on `SystemPort` (routes registered via `web.RegisterRoute`) and ships a peer HTTP client (`requestPeerClient`). We reuse it to forward `Acquire`/`Release` to the current shard leader; the leader's address comes from the Lease `holderIdentity`, not from a memberlist ring.
- Create paths: `CreateSandbox` → `createSandboxWithClaim` / `createSandboxWithClone`, both passing `User: user.ID.String()` and accepting a `Modifier func(infra.Sandbox)` that runs before the CR is written.
- Key storage: `keys.KeyStorage` with Secret backend (`e2b-key-store` Secret, informer-synced in-memory indexes, `retryUpdateSecret` CAS writes) and MySQL backend (GORM `teams`/`team_api_keys`, HMAC-only, TTL caches, `DisableAutoMigrate`).

## 2. Goals & Non-Goals

### Goals

- Enforce a per-API-key maximum on the number of sandboxes it holds, strongly consistent across replicas (no oversell, except a bounded self-healing residual under the rare crash × extreme-informer-lag intersection of §8).
- Internal model distinguishes static **QuotaSpec** (limits) from dynamic **usage** (committed) and **reservation** (in-flight). Phase 1 exposes only `sandbox.count`; dimension/scope are extension points.
- Hot path performs **at most one** in-memory acquire for limited keys and **zero** extra work for unlimited/default keys. No full sandbox list, no per-op external IO, no high-frequency rewrite of `e2b-key-store`.
- Static QuotaSpec is stored with API-key metadata; dynamic usage/reservation is **never** written back to the key store.
- During replica/leadership change (scale up/down, crash + replacement, rolling upgrade), the system **prefers under-sell (temporary retryable rejection) over over-sell**.
- Backward compatible: old keys without a quota field default to **unlimited**.

### Non-Goals

- Implementing CPU / memory / disk dimensions or per-team / per-template enforcement. Only model extension points are added.
- Reclaiming or evicting existing sandboxes when a quota is lowered. Lowering a limit only blocks new creates.
- Strict no-oversell **during the brief leadership-handoff window** without any availability cost. We accept a short fail-closed settle (≈ lease duration) plus a tiny, self-healing residual under the rare crash × extreme-informer-lag intersection, instead of a per-operation consensus log (see §11). **Note:** we *do* use Kubernetes Lease **leader election** — a battle-tested, already-vendored primitive — for coarse shard ownership. What we avoid is a per-operation CP consensus/fencing subsystem (Raft-style replicated log).
- Billing / usage reporting. This is hard-limit enforcement only.
- Cross-cluster / multi-region quota.

## 3. Quota Data Model

Three layers, all addressed by `(apiKeyID, dimension, scope)`. Phase 1 only populates `dimension = sandbox.count`, `scope = {}`.

```go
// Static — stored with key metadata.
type QuotaDimension string
const DimSandboxCount QuotaDimension = "sandbox.count" // future: cpu.millicores, memory.mb, ...

// Scope narrows where a limit applies. Phase 1: empty == per-api-key.
type QuotaScope struct {
    Template string `json:"template,omitempty"` // future extension point
}

type QuotaLimit struct {
    Dimension QuotaDimension `json:"dimension"`
    Scope     QuotaScope     `json:"scope,omitempty"`
    Limit     *int64         `json:"limit,omitempty"` // nil == unlimited
}

type QuotaSpec struct {
    Limits []QuotaLimit `json:"limits,omitempty"` // empty/absent == fully unlimited
}
```

External JSON on the key request/response is **nested** (not a flat `maxSandboxes`), e.g. `"quota": { "sandbox": { "count": 50 } }`; absent / `null` == unlimited. The handler normalizes it to `QuotaSpec.Limits`. The exact external shape is an implementation detail provided it stays nested and extensible.

Dynamic state is **in-memory only** (see §6), held by the current shard leader:

```go
type quotaCell struct {
    spec     QuotaSpec
    counters map[scopeDimKey]*counter
    warm     bool // true after base is seeded (consistent read) and the settle window has elapsed
}
type counter struct {
    base         int64                   // committed = count of owner CRs from cluster (incl Dead).
                                         // Maintained warm by an informer-driven per-owner counter;
                                         // seeded exactly via an owner-label consistent read on takeover.
    reservations map[string]*reservation // opID -> in-flight, not yet reflected in base
}
type reservation struct {
    opID      string
    sandboxID string    // bound after the CR is created
    expiresAt time.Time // TTL backstop. MUST exceed worst-case informer lag (minutes) so the
                        // implicit (informer-driven) commit never drops a still-valid reservation.
}
// used = base + sum(open reservation amounts); amount is 1 for sandbox.count, generalizes for cpu.
```

## 4. Static Config Storage

Both backends store **only** the static `QuotaSpec`, alongside the key. These are low-frequency writes (create key / admin PATCH).

### 4.1 Secret backend

- Add `Quota *QuotaSpec json:"quota,omitempty"` to `models.CreatedTeamAPIKey`; it serializes into the per-key JSON inside `e2b-key-store`.
- Old payloads decode to `nil` == unlimited (back-compat).
- Writes reuse the existing `retryUpdateSecret` CAS path. **No usage/reservation is ever written to the Secret.**

### 4.2 MySQL backend

- Add a nullable `quota JSON` column to `team_api_keys` (`NULL` == unlimited). `AutoMigrate` adds the column; gated by `DisableAutoMigrate`, with a documented manual DDL alternative.
- Old rows (`NULL`) == unlimited (back-compat).
- **No usage/counter/reservation tables are required** (see §5). An optional snapshot table for warm-up/audit may be added later; it is not required for correctness and is out of Phase-1 scope.

## 5. Usage Source: the Cluster Itself

Because the chosen counting rule is "a sandbox occupies a slot until it is truly deleted," committed usage is **exactly** the number of non-deleted Sandbox CRs carrying `AnnotationOwner = keyID`. This has two consequences:

1. **Committed usage is auto-persisted by the CRs themselves.** Every create produces a CR with the owner annotation; that IS the durable record. No separate usage store is needed, and **delete needs no quota-release operation** — the count drops naturally when the CR is garbage-collected and observed by the informer.
2. **The base count is reconstructible by any replica** from the cluster, which is what makes the in-memory authority resilient to leadership churn (§8). Reconstruction uses two complementary paths:
   - **Warm steady-state:** an informer-driven **per-owner counter** maintained on every replica (one `int` per distinct owner; incremented/decremented as owner CRs appear/disappear). `base(K)` is an O(1) read; there is nothing to "rebuild" at takeover because the counter is already warm. Cost is one map op per CR event — negligible, and bounded by event rate, not sandbox count.
   - **Exact crash seed:** a **consistent read** `GetAPIReader().List(MatchingLabels{ownerLabel: K})` that bypasses the lagging informer (§8). Used when a new leader must seed `base` precisely without waiting out informer lag.

### 5.1 Owner label (enables consistent per-owner reads)

`AnnotationOwner` is an annotation and cannot be server-side filtered. We add a mirrored **owner label** `agents.kruise.io/owner = <keyID>` to every Sandbox CR, stamped on the **same path** that stamps the annotation (`utils.LockSandbox` for claim/create, direct set for clone) — no new webhook, no extra write. A UUID keyID is a valid label value (≤63 chars, alphanumeric + `-`). The label is what lets `apiReader.List(MatchingLabels{...})` return only key `K`'s CRs in a consistent (lag-free) read, so a new leader can seed `base` exactly instead of stalling on informer convergence.

### 5.2 Counting primitive

`CountActiveSandboxes` excludes `Dead` and must not change (§1). Add a small additive method that counts **all** existing owner CRs including Dead:

```go
// CountSandboxesByOwner counts every existing Sandbox CR owned by User,
// regardless of state (including Dead-but-not-yet-GC), matching the
// "occupies a slot until truly deleted" quota rule. It can read from the
// warm informer index (steady state) or from GetAPIReader with the owner
// label selector (consistent crash seed).
func (c *Cache) CountSandboxesByOwner(ctx, opts ListSandboxesOptions) (int32, error)
```

(~5 lines over the informer path, mirroring `CountActiveSandboxes` without the Dead filter; the consistent variant uses the owner-label selector against `GetAPIReader()`.)

### 5.3 The correctness boundary (why base alone is insufficient at admission time)

The informer is per-replica and eventually consistent, with minute-level lag possible in large clusters under stress. There is a gap between admitting a create and the new CR becoming visible. Counting purely from the cluster **at the instant of admission** oversells: two concurrent creates both read `N` and both admit. Therefore admission uses

```
used(K) = clusterBase(K) + pendingReservations(K)
```

where the reservation overlay bridges "admitted but CR not yet in base," and a **single writer per key** (the shard leader, §6) keeps that overlay consistent. The overlay is the only volatile, non-reconstructible state — and it is small and short-lived. Crucially, with a stable leader, informer lag biases **only toward under-sell** (§6.4), never oversell.

## 6. In-Memory Authoritative Counting & Single-Writer Control

All quota enforcement lives in a new `QuotaManager` (package `pkg/servers/e2b/quota`), holding one `quotaCell` per key on the key's **shard leader**. The external store is demoted to "static spec source." There is **no per-op external IO**.

### 6.1 Shard ownership via per-shard Lease leader election

The "who is the single writer for key K" question is delegated to a battle-tested primitive rather than hand-rolled membership logic.

- **Key → shard (trivial, static):** `shard(K) = fnv32(keyID) mod N`. `N` is a fixed config (default **1**). Plain modulo is correct and sufficient because shard ids `{0..N-1}` are **fixed identities** — leadership moving between replicas never remaps a key to a different shard, so there is **zero key reshuffle on failover**. (Consistent hashing solves dynamic-node-set reshuffling, which we do not have here.)
- **Shard → leader (battle-tested):** each shard `i` has a `coordination.k8s.io/Lease` named `quota-shard-<i>`. Every replica runs `client-go` leader election for **all** N leases (all replicas are candidates for all shards — required so any shard can fail over). `holderIdentity` is set to the replica's routable peer address (`IP:SystemPort`). Each replica watches the N Leases (cached locally), so "who leads shard `i`" is an O(1) local lookup, no per-op apiserver read.
- **Routing:** a limited-key acquire computes `shard(K)`, looks up the leader; if leader == self, handle locally; otherwise forward one `Acquire` RPC to `holderIdentity` over the existing `SystemPort` peer HTTP. Unlimited keys never consult leases or forward.
- **N as a knob:** `N=1` (default) = a single leader owns all cells; simplest, one Lease. `N>1` spreads ownership to reduce forwarding concentration and failure blast-radius. Leadership spread across replicas is **best-effort** (independent elections may put several shards on one replica) — this affects only forwarding load and blast-radius, **never correctness**. `N` is a deploy-time constant; changing it is a **reshard** (mismatched N across replicas can double-own a key) and must be done via a full restart, not a rolling change.

### 6.2 Acquire / Commit / Release

```go
type QuotaManager interface {
    // Acquire returns a Reservation or ErrQuotaExceeded. Routes to the shard
    // leader (local or forwarded). Fail-closed while the cell is unwarm (see 6.4).
    Acquire(ctx context.Context, req AcquireRequest) (Reservation, error)
    // Release returns an in-flight reservation (create failed / cancelled). Idempotent.
    Release(ctx context.Context, req ReleaseRequest) error
    // Reconcile expires stale reservations and realigns base from the cluster.
    Reconcile(ctx context.Context, scope ReconcileScope) error
    // Describe reports current usage/limit for read APIs.
    Describe(ctx context.Context, apiKeyID string) (QuotaStatus, error)
}
```

`AcquireRequest` carries `apiKeyID, namespace, dims+amounts, QuotaSpec` (the spec is already loaded at auth time, so the leader need not re-read the store on the hot path).

**Commit is implicit.** When the leader's informer observes a CR carrying the reservation's `opID` annotation (owner = K), the same event both increments `base` (via the per-owner counter) and retires the matching reservation — atomically, so there is no undercount gap. **Release is mostly implicit too**: deletion of any owner CR (by any replica) lowers `base` via the informer. An explicit `Release` RPC is needed only when a create **fails and never produced a CR**; the reservation TTL is the backstop if that RPC is lost. Because the implicit commit waits for the informer, the **TTL must exceed worst-case informer lag** (minutes), so a slow informer never drops a still-valid reservation early (which would undercount → oversell).

### 6.3 Create hot path (limited key)

1. `CheckApiKey` already put `user` (with `QuotaSpec`) in context.
2. Unlimited key → no-op (`Acquire` returns a sentinel reservation; `Release` is a no-op). No shard/lease lookup; zero cost. This is the majority of the 2500/sec.
3. Limited key → `shard = fnv32(K) mod N`; `leader = leaseHolder(shard)`; local in-memory acquire, or one forwarded `Acquire` RPC. On the leader: if `used+1 <= limit`, record a pending reservation `opID`; else reject with `429`.
4. The `opID` is stamped onto the CR via the existing `Modifier` closure (`basicSandboxCreateModifier`), e.g. annotation `agents.kruise.io/quota-op-id`, alongside the owner label. **No infra interface change.**
5. Call `ClaimSandbox` / `CloneSandbox`. On failure, issue `Release(opID)` using `context.WithoutCancel(ctx)` so client cancellation/timeout cannot skip it. On success, do nothing — the CR-with-opID will close the reservation via the informer.

Acquire covers both claim and clone.

### 6.4 Correctness: single writer + informer-lag safety

The no-oversell guarantee rests on three pillars:

- **Single writer per shard.** `client-go` leader election guarantees at most one Lease holder per shard at a time, so every key in a shard has exactly one in-memory writer. This replaces hand-rolled ring construction and membership-convergence detection.
- **Steady-state informer-lag safety (the key property).** With a stable leader, informer lag can **only** bias toward under-sell:
  - `Acquire` is an **immediate, local** `pending += 1` — no informer involved, so a brand-new create is counted the instant it is admitted.
  - A create stays counted as `pending` from admission until its CR is observed by the informer (matched by `opID`), at which point it converts to `base` with no net change. So **create-path lag never under-counts → never oversells.**
  - Delete-path lag merely delays `base -= 1`, leaving `used` transiently high → **under-sell (safe).**
- **Leadership-change safety.** Two mechanisms, depending on cause:
  - **Exact base seed:** the new leader seeds `base(K)` via a **consistent read** (owner-label selector through `GetAPIReader()`), which is lag-free — so it does **not** have to wait out informer convergence to be correct.
  - **Bounded settle (only on lease-expiry takeover):** when it took over via lease **expiry** (a possible partition), the new leader waits a short **settle window ≈ lease duration** before serving the shard, ensuring any partitioned old leader has self-demoted (`client-go` stops acting on renew-deadline failure) → no two-writer oversell. The cell is `warm=false` and **fail-closed** during settle. On a detected **clean release** the settle is skipped (§8).
  - **Failover gap** (leader gone, lease not yet expired): forward fails / no leader → reject (under-sell).

This trades a brief, per-shard availability dip on leadership change for "never oversell," matching the chosen preference. The only residual oversell is the rare crash × extreme-lag intersection of §8, and it self-heals.

### 6.5 Reconcile (self-healing)

A periodic + informer-event-driven loop on the leader: maintain `base` via the per-owner counter, retire reservations whose CR became visible, expire reservations past TTL, and periodically re-seed `base` with a consistent read as an anti-drift check. Drift only converges toward cluster truth.

## 7. Performance

- **Unlimited / default keys:** one in-memory check; no shard/lease lookup; zero external IO. Majority of the 2500/sec.
- **Limited keys:** hot path is `fnv32 mod N` + an O(1) cached lease-holder lookup + one cell mutation, either local or a single intra-cluster HTTP `Acquire`. Never a per-op DB/apiserver write.
- **Base reads are O(1)** off the warm per-owner counter; no full scan, no per-op list.
- A limited key's per-key op rate (the only contention point) is bounded by that tenant's own create+delete churn, not the global 2500/sec.
- **Crash seed cost** is a handful of consistent `List(MatchingLabels{owner})` reads (only the limited keys mapped to the recovering shard), and only at the rare takeover event — off the hot path. Server-side label filtering keeps the wire payload to just that key's CRs.
- Optional optimization: when `used` is far below `limit`, the leader may serve from slack without strict serialization; strict single-writer only matters near the limit.

## 8. Failure Recovery & Replica Lifecycle

Invariant: **bias to over-count during uncertainty; never under-count (beyond the bounded self-healing residual below).** Over-count → temporary conservative rejection (self-heals); under-count → oversell (forbidden).

What is lost on a crash is **only** the volatile `pendingReservations` (in memory). `base` is always reconstructible from the cluster (warm counter / consistent read). In-flight creates at crash time are either (a) already-committed CRs — counted in `base`; or (b) never-committed — the create failed client-side, no CR, no oversell.

| Scenario | base seed | overlay | settle | oversell? |
|---|---|---|---|---|
| Scale up (replica added) | n/a | n/a | n/a | No — a new replica does not steal an actively-held lease; no leadership change |
| Scale down / rolling (clean lease release) | consistent read (or restored snapshot) | restored from snapshot, else empty | skipped (clean release ⇒ no partition risk) | No (no residual if snapshot restored; else tiny self-healing) |
| Crash (lease expiry) | consistent read via owner label (lag-free) | empty; lost reservations were in-flight creates with no committed CR | ≈ lease duration | No, except tiny self-healing residual |

- **Graceful handoff (planned changes — every rolling deploy).** On SIGTERM the leader releases its leases cleanly (`ReleaseOnCancel`); the successor detects the **clean release** (vs an expiry) and **skips the settle** — there is no partitioned predecessor to wait out — so a rolling upgrade does not incur a per-shard fail-closed stall. Base is seeded by the lag-free consistent read. To also eliminate the tiny residual, the departing leader **may** snapshot its overlay into the shard Lease annotation for the successor to restore; if that write is skipped or fails, it falls back to the crash path's residual (still self-healing). Clean-release detection and the snapshot are implementation discretion (§14).
- **Crash recovery (no handoff).** The Lease expires; a surviving replica wins re-election. It seeds `base` with a **consistent read** (owner label, lag-free), starts with an **empty** overlay, waits a settle ≈ lease duration (so any partitioned predecessor has self-demoted), then serves. During the failover gap + settle, the shard's limited keys are **fail-closed** (creates return retryable `429`/`503`; clients retry) — under-sell, never oversell. Crucially, the consistent read means recovery does **not** stall for minute-scale informer lag.
- **Residual (rare crash × extreme lag).** A create whose CR commits in the instant *after* the new leader's consistent read, but whose reservation died with the old leader, is briefly counted in neither base nor overlay → at most a tiny over-admission, bounded by the number of in-flight creates at crash, and **self-healing** as the informer observes those CRs and `base` catches up. This is the only residual oversell, and it sits inside the accepted "prefer under-sell" envelope. A hard zero-oversell guarantee here would require the deferred consensus-log option (§11).

Defaults (tunable): **reservation TTL** must exceed worst-case informer lag — minute-scale (e.g. 5–10 min); the implicit commit retires reservations promptly when lag is normal, so a long TTL only backstops the "CR never appears" case and explicit `Release` frees failed creates immediately. **Settle window** ≈ lease duration (seconds; e.g. 15s), deterministic and library-timed. **Lease** parameters follow `client-go` defaults (lease/renew/retry ≈ 15s/10s/2s, tunable).

## 9. API Surface

- **Create** (`POST /sandboxes`): unchanged request shape; quota enforced internally. Quota exceeded → **HTTP 429** with the E2B-compatible error body.
- **Key create** (`POST /api-keys`): optional nested `quota`. Setting/raising quota is **admin-only** (admin-team key); non-admin callers may not set or raise quota. Admin keys **may** be explicitly limited (default unlimited).
- **Quota update** (new, admin-only): `PATCH /api-keys/{id}/quota` to set/change a key's `QuotaSpec`. Dynamic usage is never settable — only reconciled.
- **Describe** (optional, read): expose current usage/limit for a key (admin or owner-team), backed by `QuotaManager.Describe` (routes to the shard leader).
- **Key delete** (`DELETE /api-keys/{id}`): minimal-change behavior — the key's quota config is removed with the key; **existing sandboxes are kept** (no cascade delete) and run out their own lifecycle. Their CRs simply no longer back any live key.

Authorization reuses the existing `CheckCreateAPIKeyPermission` admin/team gating; the quota PATCH chains `CheckApiKey` + an admin check.

## 10. Compatibility

- Old keys without a `quota` field → unlimited. New JSON field is `omitempty`; old/new payloads interoperate.
- MySQL column add is gated by `DisableAutoMigrate` with a manual DDL fallback; no behavior change for existing rows.
- `CountActiveSandboxes` is untouched; SandboxClaim self-healing is preserved. Quota uses the additive `CountSandboxesByOwner`.
- Existing sandboxes created before this change lack the owner **label**; the consistent crash-seed read undercounts them until they churn out. Mitigation: a one-time backfill (label existing CRs from their annotation) on rollout, or rely on the warm informer counter (which reads the annotation index) until backfill completes. The hot-path annotation behavior is unchanged.
- New RBAC: sandbox-manager needs `get/list/watch/create/update` on `coordination.k8s.io/leases` in its namespace.
- No change to E2B sandbox lifecycle semantics (pause/resume/timeout/delete) beyond the create-time admission and the implicit release on CR deletion.

## 11. Alternatives Considered

| Option | Mechanism | Hot-path external IO | Small-limit high churn | No oversell | Verdict |
|---|---|---|---|---|---|
| **Per-shard Lease leader election + in-memory cell + owner-label consistent seed (chosen)** | `client-go` leader election per shard; `fnv mod N` key→shard; consistent read seeds base | none | OK | Yes (under-sell on handoff; tiny self-healing residual under crash×extreme-lag) | Recommended; battle-tested ownership, minimal hand-rolled logic, fits "internal only + prefer under-sell" |
| Hand-rolled consistent-hash ring over memberlist | ring over `peers.GetAllMembers()` + fail-closed-on-uncertainty | none | OK | Yes (under-sell) | Rejected — single-writer rests on hand-rolled AP membership convergence; correctness of the handoff window is self-built and risky |
| Replicated consensus log (Raft/dragonboat) | reservations in a replicated state machine | none (off hot path) | OK | Yes, even crash×lag (true fencing) | **Deferred** — heavy new dependency + replicated-log/snapshot ops; only needed to remove the §8 residual, which is within the accepted envelope |
| Local lease pool | each replica leases blocks | only at block boundaries | Fails (degrades to per-op) | Yes | Rejected for worst case |
| Synchronous DB counter | row-lock conditional UPDATE per op | every op | single hot row serializes | Yes | Rejected at this throughput; MySQL-only |
| K8s ConfigMap/Secret CAS | resourceVersion per op | every op | apiserver cannot sustain | Yes | Rejected (infeasible at scale) |
| Informer-only counting | derive from cache | none | — | No (cross-replica lag) | Rejected as enforcement; used only for base maintenance/seed |
| Gateway consistent-hash affinity | envoy hash on `X-API-KEY` | none | OK | Yes | Out of scope — front-end cannot be changed |

We use Kubernetes Lease **leader election** for coarse, per-shard ownership — a proven, already-vendored primitive — rather than hand-building membership convergence. We stop short of a per-operation **consensus log** (Raft) because the product preference is "prefer under-sell over oversell," and the only thing the consensus log buys over the chosen design is eliminating the small self-healing §8 residual. It remains a clean future hardening if strict zero-oversell under crash × extreme-lag is ever required.

## 12. Risks

- **`N` reshard hazard:** because `shard = hash mod N`, changing `N` while replicas run mixed values can double-own a key → oversell. Mitigation: `N` is a deploy-time constant; changes require a full restart (brief global fail-closed), not a rolling change. Documented as an operational constraint.
- **Best-effort leadership spread (N>1):** independent per-shard elections may concentrate several shards on one replica, widening failover blast-radius and forwarding load. Correctness is unaffected; if balance matters, that is a future enhancement (a coordinator assigning shards). `N=1` avoids the question entirely.
- **Reservation TTL vs informer lag:** TTL shorter than worst-case informer lag could drop a still-valid reservation before its CR is visible → oversell. Mitigated by a minute-scale TTL plus prompt explicit `Release` on failure; documented tuning constraint.
- **Crash-seed apiserver load:** the consistent `List(MatchingLabels{owner})` per limited key reads from the apiserver (etcd-backed). Bounded by (limited keys in the recovering shard) × (rare takeover events), and server-side filtered. Acceptable; not on the hot path.
- **Two leaders during a partition:** a partitioned old leader could believe it still leads until its renew deadline. Mitigated by the settle ≈ lease duration before the new leader serves, so the old one has self-demoted. The deferred consensus option (§11) removes this entirely if needed.
- **Owner-label backfill:** sandboxes created before rollout lack the label and are missed by the consistent seed until backfilled/churned. Mitigated by a one-time backfill and by the annotation-index counter covering steady state (§10).
- **Hot single key concentrates on one leader replica:** in-memory cost is negligible; forwarding load for one hot limited key is bounded by its own churn.
- **Forwarding adds latency** for remote limited-key acquires (one intra-cluster hop). Unlimited keys (the majority) never forward.
- **Lingering Dead CRs hold quota** under the "count until deleted" rule (e.g., stuck finalizers). This is the conservative, no-oversell direction and was chosen deliberately.

## 13. Acceptance Criteria

- Concurrent creates for one limited key (single leader, and multi-replica with forwarding to the shard leader) never exceed `limit`; no oversell under small-limit high-churn load.
- Steady-state informer lag (simulated) on a stable leader never causes oversell — delete lag only ever under-sells; create-path counting is immediate.
- Leadership change triggering re-seed: the new leader is fail-closed during settle; after warm, `used` equals the consistent `CountSandboxesByOwner(owner)`.
- Crash recovery seeds `base` via the consistent owner-label read without stalling on informer convergence; the §8 residual is bounded and self-heals (test the in-flight-at-crash race converges to `<= limit`).
- Graceful handoff (SIGTERM / rolling) transfers the overlay and serves with no settle stall and no under-sell.
- `N` knob: `shard = fnv32 mod N` is stable across leadership change (no key remap); reshard with mismatched `N` is prevented by the restart constraint (documented; covered by a guard/test where feasible).
- Quota store unavailable (static spec load fails) or shard leader unreachable → limited key fail-closed; unlimited fast path unaffected and provably does zero external IO.
- Release is exercised on create failure, request cancel, reservation TTL expiry, and (implicitly) delete; reconcile corrects injected drift.
- Old keys without `quota` behave as unlimited; both Secret and MySQL backends store and load `QuotaSpec` correctly; MySQL migration respects `DisableAutoMigrate`.
- Owner label is stamped on every create path (claim/create/clone) and is a valid label value; consistent `List(MatchingLabels{owner})` returns the correct count.
- Quota exceeded returns HTTP 429 with the E2B-compatible error body.
- Admin-only quota set/raise enforced; non-admin cannot raise own quota; admin key may be explicitly limited.
- `CountActiveSandboxes` and SandboxClaim self-healing behavior are unchanged (regression test).
- Table-driven unit tests for QuotaManager (acquire/commit/release/reconcile, fail-closed paths, lag-safety) and for the create-path integration.

## 14. Resolved Decisions & Implementation Discretion

### Resolved (product)

- Counting rule: occupies a slot **until truly deleted** (includes Dead-not-GC); use `CountSandboxesByOwner`.
- Quota mutability: settable at key create **and** via an admin `PATCH` endpoint.
- Authorization: **admin-only** to set/raise quota; tenants cannot raise their own.
- Store unavailable: limited keys **fail-closed**.
- Crash → recovery window: **prefer under-sell**, never oversell beyond the bounded self-healing §8 residual.
- Ownership: **per-shard Kubernetes Lease leader election** (`client-go`), not a hand-rolled hash ring; **`N` default 1**, fixed at deploy time.
- Owner identity for consistent reads: add an **owner label** mirroring `AnnotationOwner`.
- Reservation TTL: **must exceed worst-case informer lag** (minute-scale); settle ≈ lease duration.
- Error code: **429**.
- Delete key with existing sandboxes: **keep** sandboxes, drop only the quota config (minimal change).
- Admin key may be **explicitly limited** (default unlimited).

### Left to the implementing agent

- Exact annotation key for `opID` and the owner label constant name; peer RPC route paths and payload encoding for `Acquire`/`Release`; `holderIdentity` address encoding.
- Clean-release-vs-expiry detection on takeover (to skip settle on graceful handoff), and whether to snapshot the overlay into the shard Lease annotation to also eliminate the planned-change residual (optional; falls back to the crash residual if absent).
- `leaderelection` parameter values, settle and TTL exact values, back-off/retry tuning for forwarded acquires; default `N` exposure (config/Helm flag).
- External nested JSON shape for `quota` (must stay nested/extensible).
- Whether `base` is maintained via a dedicated informer handler counter (`AddReconcileHandlers`) or read from the `user` index, and the exact mechanism to detect "informer warm" for the consistent-seed path.
- Owner-label backfill strategy on rollout (one-time job vs lazy).
