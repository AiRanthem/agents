# API Key Sandbox Quota — Design Spec (Redis-backed)

- Date: 2026-06-17
- Branch: `feature/e2b-api-quota-260617`
- Supersedes: the previous per-shard Lease leader-election design (deleted). This revision replaces the self-built
  sharding/leader-election/forwarding/settle machinery with an **optional Redis** counting backend (the standard
  inventory-deduction pattern), keeping the same product contract and the same ground truth (the apiserver).
- Scope: `pkg/servers/e2b/` (create, api_key, models, keys, routes), `pkg/servers/e2b/quota/` (new), `pkg/sandbox-manager/`
  (api, infra wiring, a generic `IsPrimary()` leadership capability), `pkg/sandbox-manager/config` + `clients` (Redis
  config/client), `pkg/cache/` (additive owner counter), `cmd/sandbox-manager/`, `api/v1alpha1/` (owner label constant),
  `config/`/Helm chart (RBAC for `coordination.k8s.io/leases`, Redis config), `go.mod`/`vendor` (add a Redis client).

## 1. Background

sandbox-manager is a stateless, multi-replica backend exposing E2B/MCP APIs to manage sandboxes. Each request
authenticates via `X-API-KEY`, resolved to a `*models.CreatedTeamAPIKey` (with `ID uuid.UUID` and `Team`). That `ID` is
the sandbox **owner**: every create path stamps it onto the Sandbox CR as `agentsv1alpha1.AnnotationOwner` (claim and
create-on-no-stock via `utils.LockSandbox`, clone via direct set), and it surfaces as `route.Owner`.

We need to cap how many sandboxes a single API key may hold, enforced **without overselling** even under highly concurrent
creates across replicas, and **without materially slowing down create**. Peak create throughput is ~2500/sec (150k/min)
aggregate. The worst case for a single limited key is "small limit + high churn" (a key that constantly creates and
deletes against a tiny limit), which rules out any per-operation external IO on the **unlimited** hot path and demands a
cheap, contention-free check on the **limited** hot path.

Phase 1 exposes only a per-key **sandbox count** limit, but the internal model must extend to future dimensions (CPU,
memory) and scopes (per-team, per-template, api-key+template).

### Why this design exists (relative to the previous one)

The previous design's entire complexity surface — per-shard Lease leader election, `fnv mod N` sharding, the reshard
hazard, peer `Acquire`/`Release` forwarding over `SystemPort`, the per-handoff settle window, the warm/unwarm cell state
machine, in-memory cell rebuild on takeover, and the two-leaders-during-partition risk — existed **only** to synthesize
"exactly one writer per key" without a shared atomic store. A shared atomic store (Redis) provides that serialization
directly via a single Lua script (the classic flash-sale / inventory-deduction `if remaining > 0 then decrement`
pattern). Adopting Redis deletes all of that machinery. What remains is: a few small Lua scripts, an idempotent reconcile
loop, and the same owner-label / opID bookkeeping.

### Key facts established from the codebase

- `pkg/cache` already maintains a `user` field index (`IndexUser`) over `AnnotationOwner` on Sandbox/Checkpoint, plus
  `ListSandboxes({User})` and `CountActiveSandboxes({User})`, and exposes `GetAPIReader()` — a `client.Reader` that
  bypasses the lagging local informer for a consistent apiserver read.
- `CountActiveSandboxes` **excludes** `Dead` (`cache.go:306`). Its only production caller is the SandboxClaim
  controller's `countClaimedSandboxes` (`common_control.go:408`), which relies on Dead being excluded so a dead sandbox
  triggers a replacement. **It must not be modified.**
- `AnnotationOwner` is an **annotation** (`api/v1alpha1`, `InternalPrefix + "owner"`). Annotations are not
  server-side selectable, so a consistent per-owner read cannot filter on it. We add a mirrored **owner label** to enable
  `apiReader.List(MatchingLabels{...})` server-side filtering (§5.1).
- sandbox-manager **already runs informer-driven background work** (the Secret-backed `KeyStorage.Run()` installs an
  informer event handler plus a worker goroutine; `pkg/cache` runs informers). A quota reconcile loop is consistent with
  the component's existing shape — it is not a pure request/response server.
- `k8s.io/client-go/tools/leaderelection` (with `resourcelock/leaselock.go`, backed by `coordination.k8s.io/Lease`) is
  **already vendored**. We reuse it for a **single, generic "primary manager" Lease** (§8) — not for per-key ownership.
- Create paths: `CreateSandbox` → `createSandboxWithClaim` / `createSandboxWithClone`, both passing `User: user.ID.String()`
  and accepting a `Modifier func(infra.Sandbox)` (`basicSandboxCreateModifier`) that runs before the CR is written.
- Key storage: `keys.KeyStorage` with Secret backend (`e2b-key-store` Secret, informer-synced in-memory indexes,
  `retryUpdateSecret` CAS writes) and MySQL backend (GORM `teams`/`team_api_keys`, HMAC-only, TTL caches,
  `DisableAutoMigrate`).
- No Redis client is currently vendored. This design **adds** one (e.g. `github.com/redis/go-redis/v9`) behind a backend
  interface, used only when Redis is configured.

## 2. Goals & Non-Goals

### Goals

- Enforce a per-API-key maximum on the number of sandboxes it holds, strongly consistent across replicas with **strict
  no-oversell** under normal operation. Strict no-oversell **across Redis failover** is a **configurable** posture
  (§7 condition 4): a knob enables synchronous replication of reservation writes (default **off**). With the default
  (async replication), a failover that drops un-replicated reservations degrades to a bounded, self-healing residual
  (the same envelope as total-data-loss), never unbounded oversell; enabling the knob makes failover strict at a hot-path
  latency / availability cost.
- Make the counting backend **pluggable**. Redis is the strongly-consistent backend; without Redis, quota enforcement is
  disabled (all keys unlimited) and attempts to set a non-empty quota are rejected (§6.1).
- Internal model distinguishes static **QuotaSpec** (limits) from dynamic **usage** (committed) and **reservation**
  (in-flight). Phase 1 exposes only `sandbox.count`; dimension/scope are extension points.
- Unlimited / default keys perform **zero** external IO on the hot path (the majority of the 2500/sec). Limited keys
  perform **at most one** Redis round-trip per acquire.
- The apiserver remains the **ground truth**. Redis holds only a *cache of committed usage* plus a *short-lived in-flight
  overlay*; both are reconstructible from the cluster.
- During Redis unavailability, prefer **under-sell** (temporary retryable rejection of limited keys) over over-sell.
- Backward compatible: old keys without a quota field default to **unlimited**.

### Non-Goals

- Implementing CPU / memory / disk dimensions or per-team / per-template enforcement. Only model extension points are added.
- Reclaiming or evicting existing sandboxes when a quota is lowered. Lowering a limit only blocks new creates.
- High availability of the quota feature **without** Redis. Without Redis, quota is simply disabled.
- Billing / usage reporting. This is hard-limit enforcement only.
- Cross-cluster / multi-region quota.
- A per-operation consensus log (Raft) **or** apiserver-side fencing (a validating webhook). Strict no-oversell is
  achieved with Redis atomicity + a version-guarded reconcile under normal operation; the remaining rare, bounded,
  self-healing residuals (§7.1) are accepted rather than closed with a webhook/consensus. Total Redis data loss is handled
  by a global fail-closed cold-rebuild (§9).

## 3. Quota Data Model (static)

Three layers, all addressed by `(apiKeyID, dimension, scope)`. Phase 1 only populates `dimension = sandbox.count`,
`scope = {}`.

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

External JSON on the key request/response is **nested** (not a flat `maxSandboxes`), e.g. `"quota": { "sandbox": { "count": 50 } }`;
absent / `null` == unlimited. The handler normalizes it to `QuotaSpec.Limits`. The exact external shape is an
implementation detail provided it stays nested and extensible.

`QuotaSpec` is loaded at auth time (`CheckApiKey` puts `user` in context), so the hot path never re-reads the key store.

## 4. Static Config Storage

Both backends store **only** the static `QuotaSpec`, alongside the key. These are low-frequency writes (create key / admin
PATCH). **No dynamic usage/reservation is ever written to the key store.**

### 4.1 Secret backend

- Add `Quota *QuotaSpec json:"quota,omitempty"` to `models.CreatedTeamAPIKey`; it serializes into the per-key JSON inside
  `e2b-key-store`.
- Old payloads decode to `nil` == unlimited (back-compat).
- Writes reuse the existing `retryUpdateSecret` CAS path.

### 4.2 MySQL backend

- Add a nullable `quota JSON` column to `team_api_keys` (`NULL` == unlimited). `AutoMigrate` adds the column; gated by
  `DisableAutoMigrate`, with a documented manual DDL alternative.
- Old rows (`NULL`) == unlimited (back-compat).
- **No usage/counter/reservation tables are required.**

## 5. Usage Source: the Cluster Itself

The chosen counting rule is "a sandbox occupies a slot until it is truly deleted." Committed usage is therefore
**exactly** the number of non-deleted Sandbox CRs carrying `AnnotationOwner = keyID`, **including `Dead`-but-not-yet-GC**
(matching the previous design's deliberate, conservative no-oversell direction). Consequences:

1. **Committed usage is auto-persisted by the CRs themselves.** Every create produces a CR with the owner annotation;
   that IS the durable record. No separate usage store is needed.
2. **Committed is reconstructible by any replica** from the cluster (warm informer index, or a consistent read). This is
   what makes the Redis counter recoverable after data loss (§9).

### 5.1 Owner label (enables consistent per-owner reads)

`AnnotationOwner` is an annotation and cannot be server-side filtered. We add a mirrored **owner label**
`agents.kruise.io/owner = <keyID>` to every Sandbox CR, stamped on the **same path** that stamps the annotation
(`utils.LockSandbox` for claim/create, direct set for clone) — no new webhook, no extra write. A UUID keyID is a valid
label value (≤63 chars, alphanumeric + `-`). The label lets `apiReader.List(MatchingLabels{...})` return only key `K`'s
CRs in a consistent (lag-free) read, used for seed / cold-rebuild / anti-drift.

### 5.2 Counting primitive

`CountActiveSandboxes` excludes `Dead` and must not change (§1). Add a small additive method that counts **all** existing
owner CRs including Dead:

```go
// CountSandboxesByOwner counts every existing Sandbox CR owned by User,
// regardless of state (including Dead-but-not-yet-GC), matching the
// "occupies a slot until truly deleted" quota rule. It can read from the
// warm informer index (steady state) or from GetAPIReader with the owner
// label selector (consistent read).
func (c *Cache) CountSandboxesByOwner(ctx, opts ListSandboxesOptions) (int32, error)
```

The consistent variant also returns the snapshot's `ResourceVersion` and the set of per-CR `opID` annotations (§6),
needed by the reconcile apply.

## 6. Counting Model (Redis)

All quota enforcement lives in a new `QuotaManager` (package `pkg/servers/e2b/quota`) backed by a `QuotaBackend`
interface. Two backends: `redisBackend` (strongly consistent) and `noopBackend` (no Redis configured).

```go
type QuotaManager interface {
    // Acquire reserves one slot or returns ErrQuotaExceeded (429). Unlimited keys are a no-op (zero Redis IO).
    Acquire(ctx context.Context, req AcquireRequest) (Reservation, error)
    // Release returns an in-flight reservation. Idempotent. See 6.4 for when it may be called.
    Release(ctx context.Context, req ReleaseRequest) error
    // Reconcile re-aligns committed from the cluster and retires/frees reservations. Safe to run concurrently.
    Reconcile(ctx context.Context, scope ReconcileScope) error
    // Describe reports current usage/limit for read APIs.
    Describe(ctx context.Context, apiKeyID string) (QuotaStatus, error)
}
```

`AcquireRequest` carries `apiKeyID, namespace, dims+amounts, QuotaSpec` (already loaded at auth time).

### 6.1 Backend selection (pluggable, optional Redis)

- **Redis configured** → `redisBackend`: full enforcement as below.
- **Redis not configured** → `noopBackend`: `Acquire` returns a sentinel reservation (always allow), `Release` is a
  no-op, `Describe` reports "unlimited". Additionally, setting a **non-empty** `QuotaSpec` at key create / PATCH is
  **rejected** with a clear error (so a quota is never silently ignored). Existing keys with a non-empty quota are
  treated as unlimited (and the absence of enforcement is documented), since enforcement requires Redis.

### 6.2 Redis keys (per limited key K)

| Redis key | Type | Writer | Meaning |
|---|---|---|---|
| `q:committed:{K}` | int | version-guarded **apply** only (§6.5 sweep / §6.6 seed / §9 cold-rebuild) | committed CR count; a cached snapshot of apiserver truth |
| `q:cver:{K}` | int | version-guarded **apply** only | the etcd `ResourceVersion` watermark for that committed value (version guard) |
| `q:resv:{K}` | ZSET (member=opID, score=acquire-time unix, Redis clock) | hot path (ZADD/ZREM); apply (ZREM only) | in-flight reservations not yet folded into committed |
| `q:warm` | string | cold-rebuild (§9) | presence means Redis holds valid state; absence means total data loss / first boot |
| `q:warmAt` | int (unix) | cold-rebuild (§9) | global settle deadline during a cold rebuild |

Live usage: **`live(K) = committed + ZCARD(resv)`**.

**Writer separation is the foundation of correctness:** `committed`/`cver` are written *only* by the version-guarded
reconcile apply; `resv` membership is *added* only by the hot path and *removed* by the hot path (release) or by reconcile
(folding/freeing). This separation is what makes the inherently non-atomic "read apiserver → write Redis" reconcile safe
(§7). "Writer" above means the *mutation pattern*: `committed`/`cver` move only through the version-guarded apply,
regardless of whether that apply was triggered by the reconcile sweep (§6.5), a lazy seed (§6.6), or a cold-rebuild
(§9) — the guard makes all of them mutually safe.

**CR-visibility latency** is the maximum time from a successful `Acquire` to the created CR being observable in a
**consistent** apiserver read. It is the admit→CR-write window only — *not* the full create-to-ready wait (which can be
~unbounded under the unlimited server-side timeout), because the CR is written early and waiting-for-ready happens after.
`Tgrace` (§6.5/§6.7) and the cold-rebuild settle window (§9) are both sized to exceed it, so it is small (sub-second to a
few seconds), not minutes.

### 6.3 Acquire (hot path) — atomic Lua

```
-- KEYS[1]=q:committed:{K}  KEYS[2]=q:resv:{K}  KEYS[3]=q:warm
-- ARGV: opID, limit
if redis.call('EXISTS', KEYS[3]) == 0 then return 'COLD' end          -- cold rebuild in progress / data lost
if redis.call('EXISTS', KEYS[1]) == 0 then return 'NEED_SEED' end      -- key not seeded yet (see 6.6)
local now = tonumber(redis.call('TIME')[1])                           -- Redis server clock — single source of time, skew-free
local live = tonumber(redis.call('GET', KEYS[1])) + redis.call('ZCARD', KEYS[2])
if live + 1 <= limit then
    redis.call('ZADD', KEYS[2], now, opID)                           -- score = ACQUIRE TIME (Redis clock); the only age input for reconcile (6.5/6.7)
    return 'OK'
end
return 'REJECTED'
```

> **All reservation timing uses the Redis server clock, never a manager's clock.** The score is the acquire time from
> `redis.call('TIME')`, and the reconcile's age test (§6.5/§6.7) compares `redis.call('TIME') - score > Tgrace` on that
> same clock. This removes cross-manager skew: a skewed manager cannot stamp an already-"old" score that would let the
> consistent-read free retire a still-live in-flight token. There is a **single** age threshold, `Tgrace` (no separate
> "TTL"): a token is eligible for the absent+old free only when its age exceeds `Tgrace`. For that free to be safe,
> **`Tgrace` must exceed the worst-case time from acquire to the created CR becoming visible in a consistent read**
> (= the create-path CR-write *issue* deadline of §7 condition 4 **plus** the apiserver commit-visibility latency). See
> §6.5 / §7 / Risk in §14 for the residual when apiserver commit latency pathologically exceeds this.

> **No blind expiry on the hot path.** The acquire path never runs `ZREMRANGEBYSCORE`. The score is only an *age hint* for
> the state-aware reconcile (§6.5/§6.7). Expiring a token blindly here would let admission remove the sole cover of an
> *existing-but-not-yet-folded* CR whenever reconcile lags → `live < actual` → oversell. By never expiring on the hot
> path, **reconcile being slow or down can only cause under-sell** (tokens linger, `live` stays high), never oversell.

- **Unlimited keys**: `QuotaManager.Acquire` short-circuits before any Redis call (zero IO).
- `OK` → proceed with create; `REJECTED` → HTTP **429**; `NEED_SEED` → seed this key then retry (§6.6);
  `COLD` → fail-closed retryable error (503) — Redis lost state / is mid cold-rebuild (§9).
- Redis transport error (timeout / connection refused) → **fail-closed** for limited keys (retryable 503/429); unlimited
  keys are unaffected because they never call Redis.
- The returned `opID` is stamped onto the CR via the existing `basicSandboxCreateModifier`, alongside the owner label, in
  the **same** CR write (no extra round-trip, no infra interface change), e.g. annotation
  `agents.kruise.io/quota-op-id`.
- **`opID` MUST be globally unique and never reused** (e.g. a freshly generated UUIDv4 per `Acquire` that reaches the
  `ZADD`). Correctness depends on it: the ZSET member, the `ZREM` on release, the fold-retire, and the CR annotation all
  key off `opID`, so a collision or reuse could retire the wrong reservation (dropping a live CR's cover → oversell) or
  fail to retire a stale one. A `NEED_SEED` retry that never reached `ZADD` leaves no token, so generating a new `opID`
  on retry is safe.

### 6.4 Release rule (must avoid under-counting a created CR)

Release means `ZREM q:resv:{K} opID`. It is issued with `context.WithoutCancel(ctx)` so client cancellation cannot skip
it. **Release is only safe when the create provably did NOT create a CR.**

The classifier must be **conservative and concrete**, not a heuristic on error strings:

- **Provably no CR — release.** The failure occurred *strictly before* the claim/clone code issued the CR-create
  (`Create`/`Update`) call to the apiserver — e.g. template/checkpoint lookup failure, validation rejection, or a
  pre-write context error. The create path knows this positionally (it has not yet reached the write call), so it can set
  a definitive `crWriteAttempted=false` flag. Only then is `Release` issued.
- **Everything at or after the CR-create call — do NOT release** (default). This includes timeouts, transport errors, and
  any ambiguous outcome once the write call was issued, even if it appears to have failed (the apiserver may have
  committed the object before the response was lost). The reservation is left in place and resolved by:
  (a) reconcile folding it once the CR is observed present, or (b) reconcile's consistent-read **absent + old** free once
  the CR is confirmed never to have appeared (§6.5/§6.7). Erring this way biases to a transient over-count (under-sell);
  the opposite error (releasing a token whose CR exists, before it is folded) would cause `live < actual` → oversell
  (§7 condition 3).

### 6.5 Reconcile (correction) — single-snapshot, version-guarded apply

The reconcile reads the cluster, then applies to Redis. Because a distributed system cannot stop-the-world between the
read and the write, correctness relies on **(a)** writer separation (§6.2) and **(b)** a monotonic version guard.

```
snapshot S of owner K:  C = count, opIDsPresent = {opID on each CR in S}, ver = snapshot ResourceVersion
freeable = { opID in q:resv:{K} : opID NOT in opIDsPresent AND (redisTIME - score) > Tgrace }  -- age via Redis TIME; ONLY when S is a consistent read (§7)

-- apply (atomic Lua):
-- KEYS[1]=q:committed:{K} KEYS[2]=q:cver:{K} KEYS[3]=q:resv:{K}
-- ARGV: C, ver, mayCreate(1=consistent read, 0=informer/fast), [opIDs to retire (folded)], [opIDs to free]
if redis.call('EXISTS', KEYS[2]) == 0 and mayCreate == 0 then return 'SKIPPED_UNSEEDED' end  -- fast read MUST NOT create the first committed (6.5 / Risk 3)
if ver <= tonumber(redis.call('GET', KEYS[2]) or '-1') then return 'SKIPPED' end   -- stale snapshot → drop whole apply
redis.call('SET', KEYS[1], C)
redis.call('SET', KEYS[2], ver)
for _, op in ipairs(folded) do redis.call('ZREM', KEYS[3], op) end                 -- retire reservations now in committed
for _, op in ipairs(freeable) do redis.call('ZREM', KEYS[3], op) end               -- GC leaked reservations (consistent only)
return 'APPLIED'
```

`mayCreate` is **1 only for a consistent read** (lazy seed §6.6, slow reconcile, cold-rebuild) and **0 for the fast
informer-backed reconcile**. This closes the "stale first write" hole: the version guard prevents a stale snapshot from
*overwriting* a fresher `committed`, but it cannot stop an informer-stale cache from writing the *very first* `committed`
too low (no prior `cver` to compare) and thereby suppressing the consistent seed (`NEED_SEED` only fires while
`q:committed` is absent). So the **initial** `committed` for any key is always established by a lag-free consistent read;
fast reconcile may only *update* an already-seeded key.

Two cadences feed the same apply:

- **Fast reconcile (informer-backed, cheap, frequent):** owner-CR add/delete events (and a short periodic tick) decide
  *which* keys to reconcile — that change-detection may use the cheap owner-index. But the apply's `(C, opIDsPresent, ver)`
  MUST come from **one cached `List(MatchingLabels{owner=K})`** served from the informer cache (no apiserver round-trip),
  because a `List` carries a collection-level `ListMeta.ResourceVersion` (the cache's synced etcd revision) while a bare
  index counter does not. That cache RV is a valid, comparable watermark (§6.5 note). **If a comparable collection RV
  cannot be obtained for a read path, that path MUST NOT apply** — it defers to the slow (consistent) reconcile rather
  than writing `committed` without a sound `ver`. Fast reconcile applies with **`mayCreate=0`**: it may only *update* an
  already-seeded key, never establish the first `committed` (Risk 3). It **only folds** present opIDs (never frees absent
  ones — the informer may lag behind apiserver on creates, so "absent from the informer" does not imply "absent from
  apiserver"). Folding from a possibly-stale-but-RV-stamped cache list is safe: a lower cache RV is simply skipped by the
  guard, and an informer that still shows a just-deleted CR only over-counts (under-sell).
- **Slow reconcile (consistent read, anti-drift / GC, less frequent):** `GetAPIReader().List(MatchingLabels{owner=K})`
  is lag-free, so its `S` is authoritative; it applies with **`mayCreate=1`**. It re-seeds `committed` exactly **and**
  frees `q:resv` tokens whose opID is absent from `S` and whose age exceeds `Tgrace` (creates that failed or whose CR was
  already deleted before folding). **Safety of the free rests on `Tgrace` exceeding the acquire→consistent-visible bound**
  (§6.3): a token absent from a lag-free read could still belong to a create whose CR-create call was *issued* but whose
  apiserver commit is merely slow; freeing it before that commit becomes visible would drop a live CR's cover. `Tgrace` is
  sized above the issue deadline **plus** the apiserver commit-visibility latency; the residual when commit latency
  pathologically exceeds that is documented (§7, §14).

Both cadences are **idempotent and safe to run concurrently** (multiple replicas, or a leadership handoff window): the
version guard drops any apply built from a staler snapshot, in whole (both the `committed` write and the `ZREM`s are
skipped together), so a stale writer can never erase a fresher writer's folds.

> **`ver` MUST be the List's collection-level `ResourceVersion`** (the etcd global revision returned in
> `ListMeta.ResourceVersion`), **not** a per-object `resourceVersion` and not a wall-clock/logical counter. The etcd
> revision is a single monotonic sequence, so values from the cached client (fast reconcile) and from `GetAPIReader`
> (slow reconcile / seed / cold-rebuild) are mutually comparable, and a higher `ver` always means a strictly more recent
> view. The guard's correctness — and therefore the whole no-oversell argument under concurrent/handoff reconcilers —
> depends on this. `C` and `opIDsPresent` MUST be derived from the *same* List response that produced `ver` (one
> snapshot), so the count and the folded set are always mutually consistent. Equal `ver` is treated as stale (`<=`),
> which is safe because identical revisions imply identical state.

### 6.6 Seed (lazy, per new or re-limited key)

When `Acquire` returns `NEED_SEED` (`q:committed` absent while `q:warm` present, i.e. Redis is healthy and this key is
either new or had its quota state invalidated — see §6.8), the handling replica performs a **consistent read** for that
key and runs the **apply** with the read's `C`/`ver`, **`mayCreate=1`**, and empty fold/free lists, then retries
`Acquire`. This is version-guarded like any other apply, so it is safe even if the reconciler seeds the same key
concurrently. The single `Acquire` that observed `NEED_SEED` is briefly fail-closed (one consistent read) for that one
key only. Because `mayCreate=1` is reserved for consistent reads (§6.5), the *first* `committed` of a key is always
lag-free, never an informer-stale value.

### 6.8 Quota-mode transitions (limited ↔ unlimited)

While a key is **unlimited**, the hot path bypasses Redis entirely (§10), so `q:committed:{K}` is **not maintained** and
goes stale (creates and deletes during the unlimited interval do not touch it). If that stale value were later trusted
when the key is re-limited, `live` would be far below `actual` → oversell. Therefore:

- **Any quota `PATCH` for key K MUST invalidate K's dynamic Redis state** (`DEL q:committed:{K}`, `q:cver:{K}`; the
  `q:resv:{K}` overlay may be left — it is self-correcting) as part of the PATCH. The next limited `Acquire` then sees
  `q:committed` absent → `NEED_SEED` → a fresh **consistent** seed (§6.6). A re-limited key never trusts a `committed`
  value that predates an unlimited interval.
- This invalidation is also harmless (and recommended) for a pure limited→limited limit change: it forces one consistent
  reseed, which is cheap and removes any doubt.
- Propagation caveat (extends §11): a replica still holding a **cached** `QuotaSpec` that says "unlimited" will keep
  bypassing Redis (no enforcement, no `NEED_SEED`) until its `QuotaSpec` cache entry refreshes. So a newly-imposed limit
  is strictly enforced only after the key-store cache propagates (bounded by its TTL); invalidating the `QuotaSpec` cache
  on PATCH shrinks this window. This is a bounded *enforcement-onset* delay for newly-set limits, consistent with the
  non-goal of reclaiming existing sandboxes; it is documented, not a regression of an already-established limit.

### 6.7 Reservation retirement (handles small-limit high-churn — safely)

Every retirement path is **state-aware**: a token is removed only when its CR is known to be either *folded into committed*
or *truly gone from the cluster*. A token is **never** removed merely because the manager *initiated* a delete or because
a timer fired — the CR can outlive the delete request (`Dead`-but-not-yet-GC still occupies a slot, §5), so removing its
token early would drop the sole cover of a still-existing CR (`live < actual` → oversell). Paths, fastest first:

1. **Create provably produced no CR** → immediate `Release` (§6.4).
2. **CR truly deleted** → the informer **delete event** for an owner-labelled Sandbox CR carries the object (with its
   `opID` annotation); the handler `ZREM`s that `opID`. This fires when the CR is actually gone from the cluster (`actual`
   has already dropped), so it is safe, and it is prompt (no reconcile wait), which is what bounds zombie-token
   accumulation under client-driven create/delete churn. It is **not** triggered by `DELETE /sandboxes/{id}` initiation —
   only by observed deletion. Idempotent across replicas that each see the event. (A missed event — e.g. replica
   restart — is backstopped by path 3.)
3. **Reconcile fold** (CR present in snapshot → folded into committed, then `ZREM`) and **reconcile free** (CR absent +
   token age > `Tgrace`, **consistent read only**) (§6.5). Free covers failed creates that never produced a CR and any
   delete event that was missed.
4. **Acquire-time score** — not a blind expiry. The score (Redis `TIME` at acquire) is purely the age input to path 3's
   "older than `Tgrace`" test; there is no separate TTL and no hot-path expiry. If every reconcile/informer path is dead,
   tokens simply linger (under-sell + bounded memory growth), never oversell.

**Memory / availability note (addresses the churn-masking concern):** because freeing is state-aware, live-token count is
bounded by `create-rate × fold-latency` and stale-token count by `churn × observation-latency`, both small under a healthy
reconcile/informer. If reconcile lags, tokens accumulate → `live` inflates → **over-reject (under-sell)**, masking real
headroom and growing Redis memory — an *availability* regression, not an oversell. Monitor reconcile lag and `q:resv`
cardinality; alert when either exceeds a budget.

## 7. Correctness: `live >= actual` (no oversell)

Admission grants iff `live + 1 <= limit`. Since `actual` (the count of existing owner-K CRs, the quantity being capped)
satisfies `actual <= live` at every admission instant, granting implies `actual + 1 <= limit`, i.e. no oversell.

`live = committed + ZCARD(resv) >= actual` holds because **every existing CR is continuously covered by `committed` or a
reservation token**, with a seamless handoff:

| CR phase | covered by | in `actual`? | `live` vs `actual` |
|---|---|---|---|
| admitted, CR not yet written | token | no | over (safe) |
| CR written, not yet folded | token | yes | exact |
| reconcile fold (atomic: `SET committed=C` ∧ `ZREM opID`, same snapshot) | handoff instant | yes | no gap |
| folded | committed | yes | exact |
| CR deleted, before next reconcile | committed (stale-high) | no | over (safe) |

The invariant rests on four conditions the implementation must enforce. Each was a way the original draft could oversell;
they are now requirements, not discretion.

1. **Version-guarded single-snapshot apply, watermarked by the etcd revision.** Each apply derives `C` and the
   retired/freed opIDs from one List response and writes them atomically under the `q:cver` guard, where `ver` is that
   List's collection-level `ResourceVersion` (§6.5 note). A staler apply is skipped wholesale, so a fresh writer that
   folded CRs 9–10 (committed=10, tokens removed) can never be overwritten by a stale writer (committed=8) that did not
   observe them — which would otherwise leave 9–10 in neither committed nor resv. This is what makes the non-atomic,
   leaderless, possibly concurrent (and handoff-window) reconcile safe with no stop-the-world. **Freeing absent tokens is
   permitted only from a consistent read**, never from the lagging informer (informer-absent ≠ apiserver-absent → would
   drop a live CR's token → oversell).
2. **A token is never removed while its CR still exists (no blind expiry).** The token is the sole cover during "CR
   written, not yet folded." Tokens are removed only by state-aware paths (§6.7): fold (committed then covers),
   true-deletion event (CR gone), consistent-read absent+old free, or provable pre-CR release (CR never created). The hot
   path runs **no** `ZREMRANGEBYSCORE`, so a slow or dead reconcile causes only under-sell (tokens linger), never the
   oversell that blind expiry would have caused. The **absent+old free** carries one bounded assumption: "absent from a
   consistent read **and** age > `Tgrace`" is taken to mean "this create produced no CR." That is true only if `Tgrace`
   exceeds the acquire→consistent-visible bound (the CR-write *issue* deadline plus apiserver commit-visibility latency,
   §6.3). If apiserver commit latency *pathologically* exceeds that — a create whose write call was issued, then its
   object commits later than `Tgrace` after acquire — the free can retire a token whose CR is about to appear → a
   **bounded, self-healing steady-state residual** (the CR, once visible, is folded; `committed` catches up; the
   over-admission persists only until churn). This is the same class as the total-loss residual of condition 4 and is
   likewise closeable only by apiserver-side fencing (out of scope). With `Tgrace` sized well above normal commit latency
   (minutes), it requires extreme apiserver overload.
3. **Release only when the CR provably does not exist** (§6.4, conservative positional classifier), and **cold Redis →
   fail-closed** (§9). Releasing the token of a CR that actually got created before reconcile folds it would cause
   `live < actual`; admitting against a wiped Redis would too. Both are forbidden; errors bias to over-count.
4. **Reservation durability bounds the "lost token while its CR is created" window.** A reservation can be lost while its
   create still writes a CR in two cases, each handled:
   - **Redis failover.** With *asynchronous* replication, a primary can ack a `ZADD` that the promoted replica never
     received; `committed` survives but the token is gone, so the created CR is uncovered until reconcile folds it →
     a real (bounded, but persisting) oversell. This is governed by a **configurable knob, default off (async)**:
     - **Knob off (default):** failover degrades to the same bounded, self-healing residual as cold-loss (mopped by
       reconcile, but a persisting over-admission until churn). Chosen as the default for hot-path latency.
     - **Knob on (strict across failover):** the acquire follows `ZADD` with `WAIT <numreplicas> <timeout>`. On `WAIT`
       success → proceed; on `WAIT` timeout (the token is on the primary but not yet durable on a replica) → `ZREM` the
       just-added token and fail-closed (503), so an un-replicated reservation is never relied upon. **`WAIT` alone is not
       sufficient — `<numreplicas>` must cover every *electable* replica**, or the topology must guarantee that only a
       replica that acked the write can be promoted (e.g. `min-replicas-to-write` + a failover policy that elects only
       caught-up replicas). Otherwise a `WAIT 1` ack on replica R1 does not prevent promotion of R2 (which missed the
       token) → `live < actual`. A single un-replicated instance can never be strict (see Partial Redis rollback, §9).
       Cost: a replica-ack RTT on limited-key acquire, and acquire fails-closed while replicas lag or are down (an
       availability dip, still under-sell, never oversell).
   - **Total data loss + a create whose CR commits after the settle window.** Handled by the cold-rebuild settle (§9)
     **only if** the admit→CR-write window is bounded. The create path enforces a deadline of CR-visibility latency on
     **issuing** the `Create`/`Update` call: if the budget is exhausted it must **not issue** the call. This is the only
     part the client can enforce — **once the call is issued, the apiserver may commit the object regardless of a
     client-side timeout**, so "abort without writing" is *not* achievable post-issue. Therefore the residual is precisely:
     a create whose write call was issued just before total loss and whose object the apiserver commits *after* the
     `settle`/seed read. It is bounded by the in-flight creates at the loss instant and self-healing (reconcile folds them,
     no further oversell). Closing it to a hard zero would require **apiserver-side fencing** — e.g. a validating webhook
     that rejects a Sandbox create whose `opID`/reservation is expired or unknown — which is **out of Phase-1 scope**. So:
     strict no-oversell holds for normal operation; total-data-loss carries this one bounded, self-healing residual by
     design. `settle` and `Tgrace` must exceed the issue deadline.

Implicit precondition A: **every path that stamps `owner=K` onto a CR goes through `Acquire`** (so the CR gets a token
before it exists). Phase 1 stamps owner only on the E2B create paths (claim/clone), which all go through `Acquire`.

Implicit precondition B (**owner-label backfill is a hard prerequisite, not lazy**): the seed / cold-rebuild / anti-drift
consistent reads filter by the owner **label** (§5.1), so any owner CR lacking the label is invisible to them and would
be undercounted → oversell for keys that owned sandboxes before rollout. Enforcement for a key MUST NOT be enabled until
all of its existing owner CRs carry the label. Concretely: run the one-time backfill (label every existing Sandbox from
its `AnnotationOwner`) and confirm completion **before** turning quota enforcement on; until then a key with pre-existing
unlabelled CRs is treated as unlimited. (The informer index reads the annotation and so counts them, but the
strict-correctness paths use the label, hence the prerequisite.)

Drift, when it occurs within these conditions, is always toward **over-count → under-sell**, and self-heals at the next
reconcile.

### 7.1 No-oversell guarantee (the honest, consolidated statement)

This is the precise scope of "no oversell" — stated plainly so it is not over-claimed:

- **Under normal operation** (healthy apiserver + healthy Redis), and **across Redis failover when the strict knob is on**
  with a correct topology, the design is **strictly 0-oversell**: `actual` never exceeds `limit`.
- It is **not** absolutely 0-oversell under every failure. Three **rare, bounded, self-healing** residuals remain, each
  documented above and accepted (per the product decision to not add apiserver-side fencing):
  1. **Total Redis data loss** + a create whose CR-create call was issued just before the loss and commits *after* the
     cold-rebuild seed read (§7 cond. 4, §9).
  2. **Default async failover / partial Redis rollback** that drops un-replicated `resv` while `committed` survives
     (§7 cond. 4, §9). The strict knob closes this sub-case; default config accepts it.
  3. **Pathological apiserver commit latency** exceeding `Tgrace`, letting the absent+old free retire a token whose CR is
     about to appear (§7 cond. 2, §6.5).
- Each residual is **bounded** by the number of in-flight creates at the failure instant, **self-heals** as reconcile
  folds the affected CRs (no further oversell; the over-admission persists only until churn frees a slot), and never
  produces unbounded oversell.
- The single mechanism that would collapse all three to **absolute** 0 is **apiserver-side fencing** (a validating webhook
  rejecting a Sandbox create whose reservation is expired/unknown). It is **deliberately out of scope**; it remains a
  clean future hardening if absolute 0 under these failure intersections is ever required.

In short: **strict 0 in the common case; bounded, self-healing, documented residuals only under specific rare failure
intersections.** This faithfully implements the product intent ("prefer under-sell, never unbounded oversell") given the
chosen architecture (apiserver = ground truth, Redis = cache, no per-op fencing).

## 8. Generic "primary manager" leadership (efficiency, decoupled from quota)

The hot-path `Acquire`/`Release` run on **all** replicas (Redis is the serialization point — no leadership needed). Only
the **steady-state reconcile sweep** benefits from running once instead of N times.

- `SandboxManager` gains a **generic** leadership capability, intentionally **not** coupled to quota: a single
  `coordination.k8s.io/Lease` (e.g. `sandbox-manager-primary`, in the manager namespace) elected via the already-vendored
  `client-go/tools/leaderelection`. It exposes a thread-safe method **`IsPrimary() bool`** (set true in
  `OnStartedLeading`, false in `OnStoppedLeading`). Any future singleton background task can gate on it.
- The quota reconcile sweep is the **first consumer**: the periodic fast/slow sweeps run only while `IsPrimary()` is true.
  Per-key lazy **seed** (§6.6) and the hot path are **not** gated — they must run on whichever replica handles the request.
- **Leadership is an efficiency layer only; it carries no correctness weight.** Correctness rests entirely on the §7
  version guard. If leadership flaps, splits, or is misconfigured, the worst outcome is the reconcile running on several
  replicas at once — idempotent and version-guarded, hence safe. In particular, the brief handoff window where an old and
  a new primary both reconcile is covered by the version guard (stale apply skipped), so no oversell.
- RBAC: sandbox-manager needs `get/list/watch/create/update` on `coordination.k8s.io/leases` in its namespace, for this
  **one** generic lease.

## 9. Degradation, Cold Start & Redis Data Loss

Invariant under uncertainty: **bias to over-count; never under-count** (beyond what fail-closed prevents).

- **No Redis configured** → `noopBackend`: all keys unlimited; setting a non-empty quota is rejected (§6.1).
- **Redis configured but transiently unreachable** (restart, network error, or the unreachable phase of a failover):
  limited-key `Acquire` returns a retryable error (503/429); clients retry. Unlimited keys are unaffected. Under-sell,
  never oversell. (A failover that *completes* but silently dropped un-replicated reservations is a separate case — §7
  condition 4 / §2.)
- **New key (no `q:committed`, `q:warm` present)**: lazy seed (§6.6); that one key is briefly fail-closed for a single
  consistent read.
- **Total Redis data loss** (`q:warm` absent — un-persisted cold restart, flush, or first ever boot): this is the only
  case that could oversell (committed and resv both gone → `live` momentarily 0). Handled by a **global fail-closed
  cold-rebuild**:
  1. `Acquire` sees `COLD` (no `q:warm`) and fails closed for all limited keys.
  2. The first replica to notice anchors a single global settle window **on the Redis server clock, not a manager clock**:
     a small Lua does `SET q:warmAt <redis.call('TIME') + settle> NX` (equivalently, a `q:cold` key with a Redis-server
     `PEXPIRE settle`). Using Redis `TIME` here is essential — a backward-skewed manager must not be able to set a
     `warmAt` already in the past and collapse the window. `settle ≈ CR-visibility latency`, so any create in flight at
     the moment of loss has time to commit in apiserver.
  3. All limited keys stay fail-closed until `redis.call('TIME') >= q:warmAt` (again the Redis clock). There is no need to
     enumerate keys here (Redis is wiped, so there is nothing to list); the wait alone is what guarantees safety.
  4. After `warmAt`, `q:warm` is set and normal service resumes. Each key is then seeded **lazily on its first `Acquire`**
     via the per-key `NEED_SEED` path (§6.6, `mayCreate=1`): the seed's consistent read counts any create that was in
     flight at the moment of loss, **provided that create's CR has become consistent-visible within `settle`** — which the
     create-path CR-write *issue* deadline plus normal commit latency ensures (§7 condition 4). The residual is the same
     one §7 documents: a create whose CR-create call was issued just before the loss and whose apiserver commit lands
     *after* the seed read (pathological commit latency) — bounded and self-healing, closeable only by apiserver-side
     fencing (out of scope).

  This trades availability of limited keys during the (rare) cold-rebuild for **strict no-oversell**, with no need for
  hot-path persistence writes. Recommended Redis operational posture (to make total data loss rare): AOF
  `appendfsync everysec` + HA (Sentinel/Cluster with a replica). Failover then does not lose `committed`, so only an
  un-persisted total wipe triggers the cold-rebuild.
- **Partial Redis rollback** (`q:warm` and `committed` survive but recent `resv` writes are lost — AOF fsync gap on a
  crash-restart, restore from a slightly stale snapshot, or async-failover to a replica that missed the latest `ZADD`s).
  `q:warm` detects **total** loss only, so partial rollback is **not** caught by the cold-rebuild and `Acquire` proceeds
  with `live` short by the lost tokens → the created-but-uncovered CRs oversell until reconcile folds them. This is
  **exactly the bounded, self-healing residual of the default async posture** (§7 condition 4): bounded by the number of
  reservations lost (the in-flight creates at the rollback instant), self-healing as reconcile folds those CRs (no further
  oversell), persisting only until churn frees a slot. Handling, by posture:
  - **Default (knob off):** accept this residual. It is the same envelope as async-failover; do not special-case it.
  - **Strict (knob on):** synchronous reservation replication makes a *promoted replica* hold every acked `ZADD`, closing
    the async-failover sub-case. It does **not** by itself cover single-instance AOF-gap (no replica to sync to) — so the
    strict posture additionally **requires a replicated topology where only an acked node is electable** (§7 condition 4),
    never a single un-replicated instance.
  - **Optional hardening (either posture):** a monotonic `q:epoch` bumped by the reconcile; a replica that observes
    `q:epoch` regress (or a self-written value missing) infers a rollback and triggers the cold-rebuild path. This
    converts an undetected partial rollback into a detected fail-closed rebuild. Listed as discretion, not required for
    the chosen default posture.

Defaults (tunable): **CR-write issue deadline** seconds-scale (the admit→issue-`Create` bound, not the create-to-ready
wait); **`Tgrace`** (the single token-age threshold; no separate TTL) **minute-scale** and generously above
`issue deadline + worst plausible apiserver commit latency` — it only gates the *safe* under-sell-direction free, so
erring large is fine and shrinks the §7 cond. 2 residual; **settle window** (cold-rebuild fail-closed) kept short —
≈ issue deadline + a commit-latency margin (tens of seconds) — since it is an availability dip; **fast reconcile**
event-driven + short periodic tick; **slow reconcile** every ~1 min; leadership lease/renew/retry per `client-go`
defaults (≈15s/10s/2s).

## 10. Create Hot Path (limited key)

1. `CheckApiKey` already put `user` (with `QuotaSpec`) in context.
2. Unlimited key → `Acquire` returns a sentinel reservation; no Redis, no leadership lookup; zero cost. Majority of 2500/sec.
3. Limited key → one Lua `Acquire`. `OK` records the reservation `opID`; `REJECTED` → 429; `NEED_SEED` → seed + retry;
   `COLD`/transport error → fail-closed 503.
4. `opID` is stamped onto the CR via `basicSandboxCreateModifier`, with the owner label, in the same CR write.
5. Call `ClaimSandbox` / `CloneSandbox` **under a CR-write issue deadline** ≤ CR-visibility latency: if the time budget is
   exhausted, do **not issue** the CR-create call (§7 condition 4) so "in flight" has a known finite bound. (Once the call
   is issued, the apiserver may commit regardless of a client timeout — that is the documented total-loss residual, not a
   correctness break.) On a **provably pre-CR** failure (write call not yet issued, §6.4) → `Release(opID)` with
   `context.WithoutCancel`. On any failure at/after the write call (timeout/ambiguous) → **do not release** (§6.4). On
   success → do nothing; the CR-with-opID is folded by reconcile.

Acquire covers both claim and clone. The deletion side retires the reservation via the informer's true-deletion event
(§6.7), not via the `DELETE` handler.

## 11. API Surface

- **Create** (`POST /sandboxes`): unchanged request shape; quota enforced internally. Quota exceeded → **HTTP 429** with
  the E2B-compatible error body.
- **Key create** (`POST /api-keys`): optional nested `quota`. Setting/raising quota is **admin-only** (admin-team key);
  non-admin callers may not set or raise quota. Admin keys **may** be explicitly limited (default unlimited). With no
  Redis configured, a non-empty quota is rejected (§6.1).
- **Quota update** (new, admin-only): `PATCH /api-keys/{id}/quota` to set/change a key's `QuotaSpec`. Dynamic usage is
  never settable — only reconciled. **Limit-change propagation is bounded by the key-store cache TTL, not instantaneous:**
  the hot path enforces the `QuotaSpec` loaded at auth time, so a replica with a cached spec keeps using the old limit
  until its cache entry refreshes (existing Secret/MySQL TTL caches). This is a quota-*semantics* delay, **not a
  `live ≥ actual` violation** — `live` accounting stays correct; only *which limit* is compared can lag. A lowered limit
  therefore blocks new creates within ~one cache TTL (consistent with the non-goal of reclaiming existing sandboxes); a
  raised limit takes effect within the same window. Implementations may shorten the window via cache invalidation on
  PATCH if tighter propagation is wanted; the bounded delay is acceptable by default.
- **Describe** (optional, read): expose current `live`/`limit` for a key (admin or owner-team), backed by
  `QuotaManager.Describe`.
- **Key delete** (`DELETE /api-keys/{id}`): the key's quota config is removed with the key; **existing sandboxes are kept**
  (no cascade delete) and run out their own lifecycle.

Authorization reuses the existing `CheckCreateAPIKeyPermission` admin/team gating; the quota PATCH chains `CheckApiKey` +
an admin check.

## 12. Compatibility

- Old keys without a `quota` field → unlimited. New JSON field is `omitempty`; old/new payloads interoperate.
- MySQL column add is gated by `DisableAutoMigrate` with a manual DDL fallback; no behavior change for existing rows.
- `CountActiveSandboxes` is untouched; SandboxClaim self-healing is preserved. Quota uses the additive
  `CountSandboxesByOwner`.
- Existing sandboxes created before this change lack the owner **label**, which the strict-correctness consistent reads
  filter on. **Owner-label backfill is therefore a hard prerequisite, not optional** (§7 precondition B): run the
  one-time backfill (label every existing Sandbox from its `AnnotationOwner`) and confirm completion **before** enabling
  enforcement; a key with un-backfilled pre-existing CRs is treated as unlimited until then. The hot-path annotation
  behavior is unchanged.
- New RBAC: sandbox-manager needs `get/list/watch/create/update` on `coordination.k8s.io/leases` in its namespace (one
  generic lease, §8).
- New dependency: a Redis client is vendored; it is dormant unless Redis is configured. A configurable knob (default
  off) enables synchronous reservation replication for strict no-oversell across failover; the default (async) accepts a
  bounded self-healing failover residual (§7 condition 4).
- No change to E2B sandbox lifecycle semantics (pause/resume/timeout/delete) beyond the create-time admission and the
  reservation retirement on the informer's observed true deletion (§6.7).

## 13. Alternatives Considered

| Option | Mechanism | Hot-path external IO | Small-limit high churn | No oversell | Verdict |
|---|---|---|---|---|---|
| **Redis committed + reservation ZSET overlay, version-guarded reconcile (chosen)** | atomic Lua acquire; reconcile reseeds committed from apiserver under a monotonic version guard | one Redis op for **limited** keys only; none for unlimited | OK (Redis single-key throughput ≫ one tenant's churn; fast retirement) | Yes (strict under normal op; across failover, strict iff the sync-replication knob is on — default off accepts a bounded self-healing residual; total-data-loss handled by cold-rebuild fail-closed) | Recommended; standard inventory-deduction pattern, minimal self-built coordination |
| Per-shard Lease leader election + in-memory cell (previous design) | client-go leader election per shard; fnv mod N; consistent-read seed; peer forwarding; settle | none | OK | Yes (under-sell on handoff; tiny self-healing residual) | Rejected as too complex — large self-built distributed surface (sharding, forwarding, settle, warm state, rebuild, partition risk) |
| MySQL atomic counter (no Redis) | row-lock conditional UPDATE per op | every limited op | single hot row serializes; MySQL-only; no Secret-backend story | Yes | Rejected — hot-row serialization + backend-specific; Redis handles a hot key far better |
| Replicated consensus log (Raft/dragonboat) | reservations in a replicated state machine | none (off hot path) | OK | Yes, even total Redis loss | Deferred — heavy dependency; only removes the cold-rebuild availability dip, not required for the product contract |
| K8s ConfigMap/Secret CAS counter | resourceVersion per op | every op | apiserver cannot sustain | Yes | Rejected (infeasible at scale) |
| Informer-only counting (no shared store) | derive from per-replica cache | none | — | No (cross-replica lag → over-admit) | Rejected as enforcement; used only for committed maintenance/seed |

## 14. Risks

- **Redis as a new dependency / operational posture.** Mitigated by making it optional (no Redis ⇒ no quota) and by the
  cold-rebuild for total data loss. Recommend AOF + HA so failover does not lose `committed`.
- **Partial Redis rollback that drops recent reservations** (§7 condition 4, §9, §2). Async-failover, AOF fsync gap on
  crash-restart, or restore from a stale snapshot can lose recent `resv` writes while `committed`/`q:warm` survive — and
  `q:warm` detects only *total* loss, so this is **undetected** and `Acquire` proceeds with `live` short → bounded,
  self-healing oversell (same envelope as cold-loss). **Default (async): accepted.** Strict knob: requires synchronous
  replication **and** a topology where only an acked node is electable (single un-replicated instance can never be
  strict). Optional hardening: a monotonic `q:epoch` whose observed regression triggers the cold-rebuild (§9). The strict
  knob is **default off**, so by default this residual is accepted in exchange for acquire latency.
- **Clock skew on reservation timing** (resolved). If expiry/age used a manager's wall clock, a skewed manager could make
  a live in-flight token look old → consistent-read free retires it → uncovered CR → oversell. Resolved by computing all
  reservation time from `redis.call('TIME')` (one server clock) and requiring `Tgrace` > the CR-write issue deadline
  (§6.3/§6.5).
- **Reconcile liveness vs reservation accumulation.** Because the hot path never blind-expires tokens (§6.7/§7
  condition 2), a slow/dead reconcile can no longer oversell — but tokens accumulate, inflating `live` → over-reject
  (under-sell) and growing Redis memory. Mitigated by event-driven fast reconcile, the consistent-read free pass, and
  monitoring reconcile lag + `q:resv` cardinality. This converts a former correctness risk into a monitored availability
  risk.
- **Create CR-write issue deadline.** The cold-rebuild settle and `Tgrace` assume admit→CR-write is bounded; the create
  path enforces a deadline on **issuing** the CR-create call (§7 condition 4). Once the call is issued the apiserver may
  commit regardless of a client timeout, so the cold-loss residual is precisely "issued-just-before-total-loss, commits
  after the seed read" — bounded, self-healing. Closing it to hard zero needs apiserver-side fencing (out of scope).
- **Quota-mode transition reuse of stale `committed`** (resolved). While unlimited, the hot path bypasses Redis so
  `q:committed` is not maintained; re-limiting must not trust it. Resolved by invalidating `q:committed/q:cver` on every
  quota `PATCH` (§6.8), forcing a consistent reseed. Residual: a bounded *enforcement-onset* delay while the `QuotaSpec`
  cache propagates (a replica still seeing "unlimited" does not enforce) — under-sell of the new limit, bounded by cache
  TTL, shrinkable via cache invalidation on PATCH.
- **Absent+old free vs pathological apiserver commit latency** (steady-state residual). If a create's CR-create call was
  issued but its apiserver commit is delayed beyond `Tgrace`, the consistent-read free can retire the token just before
  the CR appears → bounded, self-healing oversell — even in normal operation. Mitigated by `Tgrace` ≫ normal commit
  latency (minutes); requires extreme apiserver overload to trigger. Closing to hard zero needs apiserver-side fencing
  (out of scope, accepted §7.1).
- **Cold-rebuild availability dip.** Total Redis data loss fails limited keys closed for ≈ settle window. Accepted as the
  price of strict no-oversell without hot-path persistence; rare with AOF + HA.
- **Consistent-read load.** Slow reconcile + seed + cold-rebuild issue `List(MatchingLabels{owner})` reads from the
  apiserver. Bounded to limited keys (a minority), server-side filtered, and off the hot path. Steady state uses the
  cheap informer index.
- **Freeing tokens from a lagging view.** Freeing absent reservations from the informer (not a consistent read) would
  drop live CRs' tokens → oversell. The design forbids this (free only from consistent reads, §6.5/§7).
- **Owner-label backfill (correctness prerequisite, not just a risk).** Sandboxes created before rollout lack the label
  and are missed by the strict consistent reads → oversell for keys with pre-existing CRs. Enforcement MUST NOT be
  enabled for a key until its existing CRs are backfilled (§7 precondition B, §12); un-backfilled keys are treated as
  unlimited.
- **Lingering Dead CRs hold quota** under the "count until truly deleted" rule (e.g. stuck finalizers). Deliberate,
  conservative, no-oversell direction.
- **Every owner-stamping path must Acquire.** A future code path that stamps `owner=K` without going through `Acquire`
  would create an uncovered CR until reconcile folds it (transient oversell). Documented invariant; enforced by routing
  all create paths through `QuotaManager.Acquire`.

## 15. Acceptance Criteria

- Concurrent creates for one limited key, across multiple replicas, never exceed `limit`; no oversell under small-limit
  high-churn load.
- Steady-state informer lag (simulated) never causes oversell: create-path counting is immediate (token at admit);
  delete/fold lag only under-sells.
- Reconcile is safe under concurrency and leadership handoff: a stale snapshot's apply is skipped by the `q:cver` guard;
  after convergence `committed` equals the consistent `CountSandboxesByOwner(owner)`.
- New-key lazy seed: first `Acquire` returns `NEED_SEED`, the key is seeded via a consistent read, retry succeeds; that
  key alone is briefly fail-closed.
- No blind hot-path expiry: with reconcile stopped, an existing-but-unfolded CR's token is **not** removed by `Acquire`,
  so a concurrent create cannot oversell (it under-sells instead). The acquire Lua contains no `ZREMRANGEBYSCORE`.
- Reservation retired on **true deletion**, not delete initiation: a `DELETE` whose CR is still terminating
  (`Dead`-but-not-GC) does **not** drop the token; the token is removed only when the informer observes the CR gone.
  A concurrent create during the terminating window cannot oversell.
- Version guard uses the List collection `ResourceVersion`: a stale-snapshot apply (lower `ver`) is skipped wholesale and
  cannot erase a fresher writer's folds; equal `ver` is a no-op.
- Total Redis data loss: `q:warm` absent triggers a global fail-closed cold-rebuild; after the settle window, in-flight
  creates that respected the CR-write deadline are counted and no oversell occurs.
- Create CR-write issue deadline: a create whose budget is exhausted does **not issue** the `Create` call; `settle` and
  `Tgrace` exceed that deadline. (Post-issue commits are the accepted bounded residual, not a test failure.)
- Failover with synchronous reservation replication: an acked reservation survives primary loss → no oversell, and the
  strict knob requires a topology where only an acked node is electable (test that `WAIT` ack on one replica does not
  permit a non-acked replica to be relied upon — acquire fails-closed instead). With async (default), the documented
  bounded self-healing residual is exercised.
- Clock-skew safety: with manager clocks deliberately skewed, reservation expiry/age is computed from `redis.call('TIME')`
  so a live in-flight token is never freed early by the consistent-read free pass (no oversell).
- Partial Redis rollback (recent `resv` lost while `q:warm`/`committed` survive): default posture shows only a bounded,
  self-healing over-admission (reconcile converges to `<= limit`); if the optional `q:epoch` hardening is implemented, the
  rollback is detected and triggers the fail-closed cold-rebuild.
- Cold-loss residual is bounded: a create whose CR-create call was issued just before total loss and commits after the
  seed read is the only over-admission, and the system converges to `<= limit` as reconcile folds it.
- Quota-mode transition: limited→unlimited (creates happen, Redis bypassed)→limited triggers `q:committed` invalidation on
  PATCH → next limited `Acquire` does a consistent reseed → no oversell from a stale `committed` (§6.8).
- Fast reconcile never seeds: with `q:committed` absent and a deliberately stale informer cache, the fast (mayCreate=0)
  apply returns `SKIPPED_UNSEEDED`; the first `committed` is written only by a consistent read (§6.5/Risk 3).
- Cold-rebuild settle is clock-skew-immune: a manager with a backward-skewed wall clock cannot collapse the settle window
  because `q:warmAt` and the wait check use `redis.call('TIME')` (§9/Risk 4).
- Steady-state absent+old residual: with `Tgrace` > issue deadline + normal commit latency, the consistent-read free does
  not retire a token whose CR is merely slow-but-normal; the documented residual occurs only under pathological apiserver
  commit latency and self-heals (§7 cond. 2).
- Owner-label backfill prerequisite: a key with pre-existing unlabelled CRs is treated as unlimited until backfilled;
  after backfill the consistent read counts them and enforcement is exact.
- Redis transiently unreachable: limited keys fail closed (retryable); unlimited fast path is unaffected and provably does
  zero Redis IO.
- Release classifier: release fires only on a provably-pre-CR failure (write call not yet issued) and on request cancel
  (`context.WithoutCancel`); any failure at/after the write call does **not** release. Reconcile free and the
  true-deletion event are exercised for the no-release paths.
- `IsPrimary()` gates the steady reconcile sweep only; correctness holds with the sweep forced on all replicas
  (version-guard regression test).
- No Redis configured: all keys behave as unlimited; setting a non-empty quota is rejected; quota PATCH rejected.
- Old keys without `quota` behave as unlimited; both Secret and MySQL backends store and load `QuotaSpec` correctly;
  MySQL migration respects `DisableAutoMigrate`.
- Owner label is stamped on every create path (claim/create/clone) and is a valid label value; consistent
  `List(MatchingLabels{owner})` returns the correct count.
- Quota exceeded returns HTTP 429 with the E2B-compatible error body.
- Admin-only quota set/raise enforced; non-admin cannot raise own quota; admin key may be explicitly limited.
- `CountActiveSandboxes` and SandboxClaim self-healing behavior are unchanged (regression test).
- Table-driven unit tests for `QuotaManager` (acquire/release/reconcile/seed, version guard, fail-closed paths,
  lag-safety, churn retirement) and for the create-path integration.

## 16. Resolved Decisions & Implementation Discretion

### Resolved (product)

- Counting rule: occupies a slot **until truly deleted** (includes Dead-not-GC); use `CountSandboxesByOwner`.
- Quota mutability: settable at key create **and** via an admin `PATCH` endpoint.
- Authorization: **admin-only** to set/raise quota; tenants cannot raise their own.
- Counting backend: **Redis, pluggable/optional**. No Redis ⇒ quota disabled (unlimited) and setting a non-empty quota is
  rejected.
- Redis transiently unavailable: limited keys **fail-closed**.
- Total Redis data loss: **global fail-closed cold-rebuild** (consistent reseed + a settle window timed on the **Redis
  server clock**, §9), strict except the one bounded self-healing residual of §7.1.
- **No-oversell scope (product): accept bounded residuals; do NOT add apiserver-side fencing.** Strict 0 under normal
  operation (and across failover with the strict knob); three rare, bounded, self-healing residuals are accepted (§7.1).
  A validating webhook for absolute 0 is explicitly deferred / out of scope.
- Quota `PATCH` **invalidates** the key's dynamic Redis state (`DEL q:committed/q:cver`) so a re-limited key is reseeded by
  a consistent read and never trusts a `committed` value that predates an unlimited interval (§6.8).
- Initial `q:committed` for any key is established **only by a consistent read** (lazy seed / slow reconcile /
  cold-rebuild, `mayCreate=1`); the fast informer reconcile (`mayCreate=0`) may only *update* an already-seeded key (§6.5).
- Reconciler placement: **inside sandbox-manager**, steady sweep gated on a **generic `IsPrimary()`** leadership
  capability (one generic Lease, decoupled from quota); correctness via the **version guard**, not leadership.
- Version guard watermark: the **List collection-level `ResourceVersion`** (etcd revision), with `C`/`opIDs` from the same
  snapshot. Not implementation discretion — the guard's correctness depends on it (§6.5). The fast (cache) reconcile must
  obtain that RV from a cached `List` (which carries `ListMeta.ResourceVersion`); a read path that cannot supply a
  comparable collection RV must **not** apply and defers to the slow reconcile.
- `opID` is **globally unique, never reused** (e.g. UUIDv4 per `Acquire`); ZSET member / `ZREM` / fold / CR annotation all
  key off it (§6.3).
- Reservation timing uses the **Redis server clock** (`redis.call('TIME')`): the score is the **acquire time** and the
  reconcile age test compares against Redis `TIME` — never a manager wall clock. There is a **single** age threshold
  `Tgrace` (no separate "TTL"), which MUST exceed the acquire→consistent-visible bound (CR-write **issue** deadline +
  apiserver commit-visibility latency); the cold-rebuild settle is likewise Redis-clock-timed (§6.3/§9).
- Partial Redis rollback (recent `resv` lost, `q:warm` survives) is **undetected by `q:warm`** and falls into the default
  async residual (§9); the strict knob requires synchronous replication **plus a topology where only an acked node is
  electable** (`WAIT <all electable>`), never a single un-replicated instance (§7 condition 4).
- Reservation retirement: **state-aware only**; the hot path performs **no blind expiry**. Tokens are freed by fold,
  the informer **true-deletion** event, consistent-read absent+old free, or provable pre-CR release (§6.7). The `DELETE`
  handler does not drop tokens.
- Release classifier: **conservative and positional** — release only when the create failed *before* issuing the
  CR-create call; everything at/after is no-release (§6.4).
- Create path enforces a deadline on **issuing** the CR-create call (does not issue if the budget is exhausted); a
  post-issue commit cannot be aborted client-side and is the documented bounded residual (§7 condition 4 / §7.1).
- Owner identity for consistent reads: add an **owner label** mirroring `AnnotationOwner`. **Backfilling the label on
  existing CRs is a hard prerequisite** before enabling enforcement (§7 precondition B / §12).
- Failover strictness: **configurable knob, default off (async)**. Default accepts a bounded, self-healing failover
  residual; turning the knob on enables synchronous reservation replication (`WAIT` / sync topology) for strict
  no-oversell across failover, at a hot-path latency / availability cost (§7 condition 4).
- Error codes: quota exceeded **429**; Redis-unavailable/cold **503** (retryable).
- Delete key with existing sandboxes: **keep** sandboxes, drop only the quota config.
- Admin key may be **explicitly limited** (default unlimited).

### Left to the implementing agent

- Exact annotation key for `opID` and the owner label constant name; Redis key prefixes and Lua script encoding.
- Redis client choice and config wiring (`pkg/sandbox-manager/config` / `clients`, `cmd/sandbox-manager`); connection
  pooling, retry/back-off, acquire timeout. The strict-failover posture is a resolved config knob (default off, §16); the
  exact `WAIT <numreplicas> <timeout>` parameters (or synchronous-topology setup) when it is enabled are discretion.
- Generic leadership lease name, `leaderelection` parameter values, and the `IsPrimary()` exposure on `SandboxManager`.
- Exact `Tgrace` / settle / reconcile-interval values; the CR-write issue-deadline value; how reconcile lag and `q:resv`
  cardinality are monitored/alerted.
- External nested JSON shape for `quota` (must stay nested/extensible).
- The code-level mechanism that records "CR-create call issued" so the §6.4 positional release classifier can decide
  (e.g. a flag set immediately before the `Create`/`Update` call on the claim/clone paths).
- The owner-label backfill **mechanism** (one-time Job vs init step) — but it must complete before enforcement is enabled
  (the *policy* is resolved, §7 precondition B).
- How the List collection `ResourceVersion` watermark is obtained from each read path (cached client vs `GetAPIReader`),
  and whether the fast reconcile reads counts from the informer owner-index directly or via a dedicated event counter.
- Optional `q:epoch` partial-rollback detection (§9): whether to implement it, and the heartbeat cadence / regression
  check. Not required for the default async posture.
- Whether to add cache invalidation on quota `PATCH` to tighten limit-change propagation below the key-store cache TTL
  (§11); the bounded TTL delay is acceptable by default.
