---
title: Short and Stable Sandbox IDs
authors:
  - "@AiRanthem"
reviewers: []
creation-date: 2026-07-11
last-updated: 2026-07-29
status: implemented
---

# Short and Stable Sandbox IDs

## Summary

OpenKruise Agents historically identified a Sandbox as:

```text
<namespace>--<sandbox-name>
```

This value is readable, but its length grows with both Kubernetes names. E2B-compatible traffic
addresses embed the Sandbox ID in a DNS name, so a valid namespace and Sandbox name can still
produce an address that exceeds DNS limits.

This proposal introduces an optional short Sandbox ID:

```text
<operator-prefix><26-character UID encoding>
```

The suffix encodes the Sandbox's complete 128-bit Kubernetes UID. Once assigned, the ID is stored
in the Sandbox label `agents.kruise.io/sandbox-id` and becomes that Sandbox CR's authoritative
identity.

The change is deliberately incremental:

- an unlabeled Sandbox continues to use its legacy ID;
- enabling the feature assigns short IDs only at the end of successful claim and clone operations;
- an existing non-empty label is always honored, even if assignment is later disabled;
- one Sandbox has one active ID at a time; legacy and short IDs are not simultaneous aliases;
- client-provided IDs remain opaque and are never decoded to recover a Kubernetes object.

The persisted identity, one-way migration, and version-ordered routing behavior are the core of
this design. The encoding itself is intentionally simple.

## Motivation

Changing only the ID returned by the create API would leave caches, routing, peer synchronization,
Checkpoints, pagination, and E2B diagnostics with conflicting views of the same Sandbox. A safe
short-ID design therefore needs to answer four broader questions:

1. Where is the selected identity persisted?
2. How does an existing Sandbox move from its legacy ID without exposing two aliases?
3. How do independent manager and gateway processes reject delayed route events?
4. How can operators diagnose an opaque ID without weakening tenant isolation?

### Goals

- Keep Sandbox IDs short enough for normal E2B dynamic hostnames.
- Preserve legacy behavior for unlabeled Sandboxes without a background migration.
- Make the selected ID stable across recycle and later claims of the same Sandbox CR.
- Keep assignment policy in sandbox-manager and infrastructure concerns policy-neutral.
- Ensure cache and route transitions never expose both IDs in one current view.
- Fail closed when cache lookup observes duplicate IDs.
- Support a staged manager/gateway rollout before short-ID assignment is activated.
- Let operators locate a labeled Sandbox directly with `kubectl`.
- Restore namespace/name diagnostics only after authorization succeeds.

### Non-Goals

- Giving one Sandbox permanent legacy and short aliases.
- Migrating all existing Sandboxes in the background.
- Rewriting IDs already stored on Checkpoints.
- Making short IDs reversible to namespace and name.
- Treating a Sandbox ID as proof of its current owner or claim session.
- Removing the `--` namespace restriction while legacy IDs remain supported.
- Repairing or normalizing a non-empty persisted label during reads.
- Supporting administrator-written, copied, or otherwise forged reserved labels and Routes.
- Rolling back to label-unaware binaries after short-ID assignment has begun.

## Identity Model

### One authoritative value

Sandbox ID resolution has exactly two branches:

| Sandbox metadata | Resolved ID |
|---|---|
| `agents.kruise.io/sandbox-id` is non-empty | Return the label unchanged |
| The label is absent or empty | Return `<namespace>--<name>` |

A non-empty label is a persisted fact. Readers do not revalidate its format, length, relationship
to the UID, or origin. Revalidating on every read could make different binaries disagree about an
identity that has already been stored.

The assignment flag controls only the creation of new labels. It never changes how existing
Sandboxes are read:

| Assignment | Unlabeled Sandbox | Labeled Sandbox |
|---|---|---|
| Disabled | Remains legacy | Existing label remains authoritative |
| Enabled | Receives a short ID after successful claim or clone | Existing label is preserved |

### One-way transition

The normal state transition is:

```text
unlabeled / legacy  ->  labeled / short
labeled / short     ->  labeled / short
```

An unlabeled Sandbox may be claimed with a legacy ID, recycled, and assigned a short ID during a
later enabled claim. A labeled Sandbox keeps its short ID through recycle, later claims, and flag
changes.

The ID identifies the Sandbox CR, not an individual claim or tenant session. Reusing a Sandbox for
another owner does not create a new ID, so authorization and external systems must never infer
current ownership from the ID alone.

### Reserved metadata

The selected ID is stored as:

```yaml
metadata:
  labels:
    agents.kruise.io/sandbox-id: n6lyz2y2m5g3fbbq4rq6r5kpte
```

This label is owned by sandbox-manager. Public inputs and internal extension callbacks cannot add,
change, or delete it. Pool and template materialization must not copy it into a new Sandbox, while
recycle and metadata cleanup must preserve a label already assigned to the existing Sandbox CR.

The same qualified string is also used as a Checkpoint annotation. The two metadata kinds remain
strictly separate:

- the Sandbox label is the Sandbox's current authoritative ID;
- the Checkpoint annotation records the source Sandbox ID at Checkpoint creation time.

Readers never fall back from one metadata kind to the other.

Out-of-band writes to the reserved label are outside the supported protocol. Cache lookup still
detects duplicate resolved IDs and fails instead of choosing an arbitrary Sandbox. Routing assumes
that supported IDs were generated by the system and are unique within the cluster.

## ID Format and Assignment

### Encoding

The short suffix is produced by encoding all 16 bytes of the Kubernetes UID with unpadded,
lowercase RFC 4648 Base32. The result is always 26 characters from `[a-z2-7]`; no UID bits are
discarded.

For example:

```text
n6lyz2y2m5g3fbbq4rq6r5kpte
```

Using the full UID avoids adding a collision budget and collision-allocation protocol. Generation
fails if the UID cannot be decoded as a 16-byte UUID.

### Optional prefix

Operators may prepend a prefix with `--short-sandbox-id-prefix`. No separator is inserted
automatically, so an operator who wants `prod-` must include the hyphen in the configured value.
The prefix defaults to empty.

A non-empty prefix:

- starts with a lowercase letter or digit;
- otherwise contains only lowercase letters, digits, and hyphens;
- is at most 37 characters, keeping the complete ID within the 63-character Kubernetes label-value
  limit.

For Native E2B dynamic domains of the form `<port>-<sandbox-id>.<domain>`, operators should keep
the prefix at 31 characters or fewer so a five-digit port, separator, and ID fit in one DNS label.

The prefix is validated when sandbox-manager starts, even when assignment is disabled, and must be
consistent across replicas. Prefix changes affect only future assignments; existing labels are
never regenerated.

### Assignment boundary

Short-ID assignment is disabled by default. With `--enable-short-sandbox-id=true`, an unlabeled
Sandbox receives its ID only at the final successful stage of claim or clone. The value is
persisted before the success response returns it. A clone uses its own UID and never inherits the
source Sandbox's identity.

If generation or final persistence fails, the overall claim or clone fails through its existing
cleanup path. The system does not return a successful Sandbox whose client-visible identity has not
been persisted.

The design intentionally keeps no legacy alias during cache propagation. Internal observers may
briefly converge at different times, but each observed version of a Sandbox resolves to exactly
one ID.

## Responsibility Boundaries

The identity decision crosses several components, but each layer keeps one kind of responsibility:

| Boundary | Responsibility |
|---|---|
| API and controllers | Reject reserved metadata at public inputs and present protocol-specific responses |
| Sandbox-manager | Own ID format, assignment, one-way migration, and orchestration policy |
| Infrastructure | Persist generic metadata changes and expose neutral Kubernetes observations |
| Shared routing | Apply protocol-neutral projection, ordering, replacement, and deletion semantics |
| E2B compatibility | Enforce legacy namespace constraints and present authorized diagnostics |

Infrastructure does not choose or mutate Sandbox ID format. E2B does not generate or migrate IDs.
Controller code may protect the reserved key but does not depend on sandbox-manager identity
policy.

Manager and gateway keep separate in-memory route stores because they are separate processes. They
nevertheless use the same routing semantics so an identity transition cannot behave differently
between the two components.

## Lookup and Routing Contracts

### Opaque lookup

Every consumer treats a Sandbox ID as an opaque exact-match value. No cache, route store,
authorization path, or server adapter reverse-parses a legacy ID to recover namespace and name.

The claimed-Sandbox cache indexes exactly one resolved ID per Sandbox. When a label update is
observed, the entry moves from the legacy key to the short key rather than retaining both. Zero
matches remain not-found; multiple matches fail closed with a descriptive ambiguity error.

At the manager boundary, all underlying lookup failures retain the existing not-found error
category and include the underlying lookup error in the public message. Duplicate-ID ambiguity
does not create a new transport status.

### Atomic identity replacement

Routing is ordered by Kubernetes object identity and resource version, not by interpreting the
Sandbox ID:

- every current route is tied to an explicit namespace/name ObjectKey;
- a newer observation for the same ObjectKey atomically retires its previous ID and activates its
  new ID within each physical store;
- an older or equal resource version cannot replace current state;
- deletion is also ObjectKey- and resourceVersion-ordered;
- a deletion watermark is retained so a delayed update cannot resurrect a removed route;
- a recreated object with the same namespace/name crosses the old deletion watermark with its
  newer cluster resource version.

The ordering contract assumes every accepted route producer projects Kubernetes metadata from the
same cluster. Cross-cluster, forged, or misrouted payloads are unsupported.

Supported peer mutations carry an explicit namespace/name and a valid resource version. Malformed
or partial mutations are rejected without changing route state; valid stale events are
acknowledged as idempotent no-ops. During the pre-activation rollout only, legacy ID-only peer
messages are acknowledged and ignored rather than admitted into the new route model.

Route feeds preserve all informer-visible, non-terminating Sandboxes, regardless of lifecycle
state. Traffic admission remains a separate concern and continues to require a Running Sandbox.
For peer synchronization, only the exact `dead` state represents deletion; other states update
route knowledge without making them traffic-eligible.

Route projection also preserves the existing security and compatibility behavior: runtime access
tokens take precedence over the legacy token source, traffic authentication is enabled only when
its annotation is exactly `true`, and tokens are always redacted from route logs.

### Deletion fencing and informer truth

Informer List/Watch is the authoritative route-state source. Namespace and selector filtering are
applied at the informer boundary. Deletion timestamp updates and normal delete events preserve
their resource version before the object is discarded.

A synthetic tombstone without a trustworthy resource version is handled as a best-effort delete:
if the route is currently known, its current version becomes the deletion watermark. This closes
the common stale-event path but cannot prove the final deletion version if a newer peer update
arrived in between. The residual risk is accepted rather than adding API-server reads or a route
repair loop.

Deletion watermarks are retained for the process lifetime. This trades bounded per-object memory
for protection against arbitrarily delayed events; memory therefore grows with the cumulative
number of ObjectKeys observed by a process.

## User-Visible Behavior

### E2B diagnostics

Short IDs intentionally omit namespace and name. After Sandbox lookup and ownership authorization
succeed, E2B restores that context without changing identity semantics:

- successful metadata includes
  `e2b.agents.kruise.io/sandbox-resource: <namespace>/<name>`;
- downstream runtime, gateway, Checkpoint, and lifecycle errors append
  `sandboxResource=<namespace>/<name>`;
- user metadata cannot spoof either the Sandbox-ID label or the response-only resource key.

Not-found and unauthorized responses do not disclose namespace or name.

Operators can locate a supported short-ID Sandbox directly:

```shell
kubectl get sbx -A -l agents.kruise.io/sandbox-id=<sandbox-id>
```

### Checkpoints and pagination

A Checkpoint records the resolved source Sandbox ID at creation time. If that Sandbox later moves
from legacy to short, existing Checkpoints keep the legacy value and later Checkpoints record the
short value. No historical rewrite is performed.

Pagination uses the resolved ID only as an opaque uniqueness component. An identity transition may
change that component between list requests, like other mutable list state; the system does not
retain a second identity to stabilize pagination.

## Rollout and Rollback

The rollout protocol is a correctness precondition:

1. Deploy label-aware manager and gateway binaries with short-ID assignment disabled.
2. The two components may be rolled out in either order while assignment remains disabled.
3. Drain old replicas and their in-flight or retry peer traffic.
4. Verify every relevant informer handler is synchronized.
5. Enable assignment on sandbox-manager.

During the initial disabled rollout, new receivers ignore old ID-only peer route messages and rely
on their own informer for convergence. A brief missing or stale route is acceptable during this
window. This compatibility behavior is only for reaching the activation point; old senders are not
supported after assignment begins.

Once any short label has been persisted, rolling back to a binary that ignores the label is unsafe.
Such a binary would reconstruct the legacy ID and disagree with persisted identity.

Turning `--enable-short-sandbox-id` off remains safe as a way to stop new assignments, but it is not
a data rollback:

- existing labels remain authoritative;
- labeled Sandboxes remain short;
- unlabeled Sandboxes remain legacy.

Removing legacy compatibility is a separate future change after operators confirm that no
supported unlabeled Sandboxes remain.

## Operational Decisions and Trade-offs

- No dedicated Prometheus series are added for legacy resolution, assignment, Store processing, or
  peer compatibility. Existing claim/clone errors, operation timings, informer health, and
  structured route diagnostics remain the observability surface.
- Persisted identity is preferred over a global response-format switch because a global switch
  could make one Sandbox alternate IDs during rollout or configuration changes.
- Full UID encoding is preferred over truncation or a random allocation because it is deterministic
  and avoids a separate collision protocol.
- A single active ID is preferred over permanent aliases because aliases complicate authorization,
  cache uniqueness, route deletion, and eventual removal of the legacy format.
- Existing labels are trusted on read because read-time validation could split component behavior
  after identity has already been persisted.
- Informer convergence and deletion fencing are preferred over API-server repair loops to keep one
  route truth source and avoid replica-scaled repair traffic.
