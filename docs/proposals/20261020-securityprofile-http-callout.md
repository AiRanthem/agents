---
title: Named HTTP Callouts for SecurityProfile
authors:
  - "@Kuromesi"
reviewers: []
creation-date: 2026-10-20
last-updated: 2026-10-20
status: provisional
see-also:
  - "/docs/proposals/20260521-traffic-policy-and-security-profile.md"
  - "https://github.com/openkruise/agents/pull/882"
  - "https://github.com/openkruise/agentio/pull/93"
---

# Named HTTP Callouts for SecurityProfile

## Summary

Add `actions.httpCallout` to `SecurityProfile` and `GlobalSecurityProfile`,
providing a gateway interceptor mechanism for invoking user-owned business logic
during request or response processing.

Users can reuse their existing authentication and credential-injection workflows
through an HTTP service. The service receives the configured request context and
returns the changes to apply, or an immediate response when processing should
stop. EPE handles the Envoy ext_proc integration, coordinates processing phases,
and applies the returned changes.

External integrators do not need to implement an ext_proc server or manage its
streaming protocol and processing state. They can focus on their business logic
and the modifications they want the gateway to make. Policy authors choose the
phases, disclosed headers and bodies, and failure behavior; operators manage
provider connections separately in Agentio's EPEConfig.

This proposal describes the API contract introduced by
[agents PR #882](https://github.com/openkruise/agents/pull/882). Installing the
CRD field alone does not enable callout execution. Agentio must consume the
published API, convert the action, and register it in the production filter
pipeline before profiles using the action can enforce policy.

## Motivation

Users may already have services that authenticate requests, obtain credentials,
and inject those credentials before forwarding traffic upstream. They need a
way to invoke this existing logic from the gateway without rebuilding it as a
built-in action.

For example, a user's service may inspect an incoming request, validate its
caller using an existing authentication system, retrieve an upstream credential,
and return instructions to replace the request's `Authorization` header. The
gateway then applies the modification and continues processing.

Direct integration with Envoy ext_proc requires the service to participate in a
bidirectional gRPC processing protocol. In addition to its business logic, the
implementation must handle processing messages across request and response
phases and produce the corresponding protocol responses. This adds integration
work unrelated to authentication or credential injection.

HTTP callouts provide a simpler integration boundary: receive an HTTP
invocation, execute business logic, and return a decision describing the
required modifications. EPE owns the interaction with ext_proc and translates
that decision into gateway behavior. Content scanning is another use case for
this same mechanism.

Named providers separate operator-managed connection settings from per-rule
configuration. Operators manage endpoints, timeouts, and TLS, while policy
authors choose when to invoke a provider and which data to disclose.

### Goals

- Reuse existing authentication and credential-injection logic through HTTP calls.
- Keep ext_proc protocol and processing-state management inside EPE.
- Support request-only, response-only, and combined callouts in both profile kinds.
- Reuse an operator-managed provider without exposing connection settings in rules.
- Make header and body disclosure explicit, with metadata-only calls by default.
- Define bounded, complete-body disclosure and predictable execution failures.
- Preserve existing rule ordering and released actions.

### Non-Goals/Future Work

- Implementing Agentio conversion or production filter registration in this PR.
- Defining a new Kubernetes provider CRD or namespace-scoped provider lookup.
- Changing credential-provider references or the audit webhook API.
- Streaming or chunked body processing, binary bodies, or truncated inspection.
- Specifying a new wire protocol, retry policy, or Envoy buffering configuration.
  The provider's HTTP Invocation/Decision protocol belongs to Agentio.

## Proposal

### User Stories

1. **Reuse an existing authentication and credential-injection workflow.**
   A user connects an existing service through an HTTP handler. The service
   validates the caller, obtains the appropriate upstream credential, and
   returns request-header modifications. EPE applies those modifications before
   forwarding the request.
2. **Implement an interceptor without learning ext_proc.**
   An integrator writes an HTTP handler that receives request context and returns
   modifications or an immediate response. They do not need to maintain an
   ext_proc stream or coordinate its processing phases.
3. **Extend interception to response processing.**
   A user configures a response-phase callout to run custom logic on the upstream
   response, with independently configured header and body disclosure.

### API and Example

Both profile kinds share `SecurityProfileSpec` and `SecurityRuleActions`. The
new optional `httpCallout` field uses `HTTPCalloutAction`; existing selectors,
matching rules, and profile priorities retain their semantics.

```yaml
apiVersion: agents.kruise.io/v1alpha1
kind: SecurityProfile
metadata:
  name: inject-upstream-credentials
  namespace: default
spec:
  selector:
    matchLabels:
      app: sandbox
  rules:
    - name: authenticate-and-inject
      match:
        - domains: [api.example.com]
      actions:
        httpCallout:
          provider:
            name: auth-interceptor
          request:
            headers:
              enabled: true
              filter:
                allowList: [authorization, x-request-id]
            body:
              enabled: false
          failStrategy: Block
```

The example requires a corresponding HTTP callout provider named
`auth-interceptor` in the serving EPE configuration. It explicitly discloses the
incoming authorization header to that trusted service for authentication, while
leaving body disclosure disabled. The service returns the upstream credential
as a request-header modification. The response phase is omitted because this
workflow only modifies the outgoing request. For a
`GlobalSecurityProfile`, use that kind and omit `metadata.namespace`; the action
shape is identical.

### Integration Boundary

The profile fields configure when the gateway invokes the service and which
traffic data it sends. The external service implements Agentio's
[HTTP Invocation/Decision contract](https://github.com/openkruise/agentio/blob/master/extensions/epe/pkg/filters/httpcallout/protocol.go)
to describe the changes it wants applied. An existing service can expose a
handler or adapter for that contract; it does not need to implement ext_proc.

For credential injection, the handler receives the disclosed authentication
context, runs its existing authentication and credential lookup logic, and
returns a continue decision with an authorization-header replacement. EPE
applies that decision and continues the action chain. A handler can instead
return an immediate response to stop processing, for example when authentication
fails. If `TokenTransformation` is also configured, it runs after the callout;
policy authors must account for that ordering when both actions modify credentials.

HTTP callouts expose a phase-based integration, rather than every ext_proc
capability. EPE manages the ext_proc protocol interaction. When body disclosure
is enabled, the complete body is buffered subject to the configured limit;
streaming or chunk-by-chunk processing is outside this proposal's scope.

### Provider Reference and Ownership

`provider` is a required `ExtensionProviderRef` containing only `name`. The name
has no default, is 1–253 characters, and is validated by the API's lowercase DNS
subdomain pattern. There is no `kind` or `namespace` field. The consuming action
determines the required provider type: `httpCallout` requires an HTTP callout
provider in the serving EPE's registry.

The operator owns the provider URL, timeout, and TLS settings. Decision-response
size limits also belong to the provider/runtime side, not to the profile's
`body.maxBytes`. In the companion
[Agentio PR #93](https://github.com/openkruise/agentio/pull/93), that limit is
configured by `HTTP_CALLOUT_MAX_RESPONSE_BYTES` at client initialization rather
than by an EPEConfig field.

CRD admission validates the reference's shape, not provider availability.
Missing, unavailable, or wrong-type providers are execution failures handled by
`failStrategy`. The runtime must not substitute a different or default provider.

### Phases and Data Disclosure

At least one of `request` and `response` must be present. Omitting a phase
disables it; an empty object (`request: {}` or `response: {}`) enables a
metadata-only invocation.

- `request` runs before forwarding the request upstream.
- `response` runs on the upstream response. It includes request correlation
  metadata but no request headers or request body.
- Each phase independently configures `headers` and `body`.

Both `headers` and `body` are optional configuration objects with an `enabled`
boolean defaulting to `false`. Omitting the object, specifying `{}`, or setting
`enabled: false` disables that data disclosure. Other settings have no runtime
effect while disclosure is disabled; ordinary schema constraints still apply.
Enabling body disclosure does not require the original body to be non-empty.

| Header configuration | Disclosed headers |
|---|---|
| Omitted or `enabled: false` | No headers. |
| `enabled: true`, no `filter` | All headers, including credentials and cookies. |
| `enabled: true`, `filter.allowList` | Only named headers. |
| `enabled: true`, `filter.denyList` | All headers except named headers. |

When `filter` is present, exactly one non-empty list is expected. An empty
`filter: {}` or a filter containing both lists is outside the supported contract.
The CRD has no CEL validation for this cross-field constraint; runtime
integration must validate it. Individual lists retain schema validation for
non-empty contents and header names. Header names are case-insensitive; lists
use set semantics and the API's supported HTTP token pattern, with name lengths
of 1–256 characters. Disabling headers does not remove invocation metadata such
as authority, path, and content type. A denylist can still disclose credentials
unless explicitly excluded.

When `body.enabled: true`, the runtime buffers and sends the complete body for
that phase, so the callout runs after buffering instead of at the headers phase.
Bodies must be valid UTF-8. Response-phase body disclosure sends only the
response body.

`body.maxBytes` defaults to 1 MiB (1048576 bytes) and accepts values from 1 through
8 MiB (8388608 bytes). Request and response phases configure their limits
independently. Oversized or invalid bodies cause an execution failure; they are
never truncated for inspection. This setting does not configure Envoy's
buffering limit or the size of the provider's decision response.

For example, a body inspector can enable both phases with different limits:

```yaml
httpCallout:
  provider:
    name: content-inspector
  request:
    headers:
      enabled: true
      filter:
        allowList: [content-type, x-request-id]
    body:
      enabled: true
      maxBytes: 1048576
  response:
    headers:
      enabled: true
      filter:
        allowList: [content-type]
    body:
      enabled: true
      maxBytes: 4194304
  failStrategy: Block
```

This structure separates enabling disclosure from configuring it. Future CEL
header filtering could add a mutually exclusive filter branch, and future body
streaming could add a processing mode. Neither capability is defined or enabled
by this API change; each requires its own runtime semantics and implementation.

### Action Ordering and Failure Behavior

The declared action order is `Bypass`, `Block`, `MCPToolPolicy`,
`HeaderManipulation`, `HTTPCallout`, then `TokenTransformation`. Existing terminal
actions can stop evaluation before a callout. A callout is non-terminal unless
it returns an immediate response or encounters a fail-closed execution error.
Every matching rule executes its own configured actions; audit remains
asynchronous after request resolution.

`failStrategy` reuses the existing enum:

| Value | Execution failure behavior |
|---|---|
| `Block` (default) | Reject the request. |
| `Allow` | Skip the failed callout's mutations and continue. |
| `Ignore` | Same current behavior as `Allow`. |

Execution failures include provider lookup, transport, timeout, body-disclosure,
and protocol errors. A valid immediate response from the provider is always
honored, regardless of `failStrategy`; a deliberate denial is not a callout
failure. This API does not prescribe an error response status or body.

### Implementation Details and Constraints

The PR adds the Go API types and action field, regenerates DeepCopy methods,
and adds matching OpenAPI schemas to both profile CRDs. Schema validation
requires a provider name and enforces field types, failure-strategy enum values,
list constraints, and size bounds. No CEL validation is added for this action.
The at-least-one-phase and exactly-one-filter-branch requirements are documented
contracts for runtime integration to enforce, not CRD admission checks. This PR
does not add a webhook or runtime validator.

EPEConfig provider registration and configuration watching are separate work in
Agentio PR #93. Runtime conversion and production filter registration must
follow the published agents API. Neither successful admission nor provider
registration alone establishes that the action is executing.

### Risks and Mitigations

- **Sensitive data disclosure:** default to metadata-only calls; use an explicit
  header allowlist and enable bodies only for providers trusted with that data.
- **Latency and buffering cost:** operators configure provider timeouts; policy
  authors limit disclosed bodies. Deployment buffering limits must be aligned
  separately, since `body.maxBytes` does not change them.
- **Provider outages:** `Block` is the default. Choosing `Allow` or `Ignore`
  explicitly accepts continuing without the failed inspection or its mutations.
- **Partial deployment:** install compatible runtime support before relying on
  a profile for enforcement, and verify actual traffic behavior.

## Alternatives

1. **Implement an ext_proc service directly.** This exposes the full processing
  protocol but requires external integrators to handle the stream and phase
  interactions. HTTP callouts keep that work in EPE and let integrators focus
  on business decisions and returned modifications.

2. **Inline URL, timeout, and TLS settings per rule.** This duplicates connection
   configuration and couples endpoint rotation to policy edits. Named providers
   keep those settings with their operator owner.
3. **Reuse audit webhooks.** Audit is asynchronous and cannot block or mutate the
   inspected exchange.
4. **Add namespace and kind to the reference.** The current provider registry is
   owned by the serving EPE, and the action already determines the required kind.
   Those fields would imply lookup semantics this API does not provide.
5. **Truncate oversized bodies.** Partial inspection could miss relevant content.
   Complete-body disclosure instead fails according to the selected strategy.

## Upgrade Strategy

The optional field is additive for released profiles; profiles that omit it keep
their existing behavior. This design replaces the unreleased
`externalProcessing.backend.http` shape with `httpCallout.provider.name`.
Experimental users must move connection settings to the provider configuration
and update the action; no compatibility alias is introduced.

The earlier unreleased callout shape is also replaced: `headers.mode: None`
becomes omitted headers or `enabled: false`; `All` becomes `enabled: true`
without a filter; `AllowList` and `DenyList` become `enabled: true` with the
corresponding list under `filter`. Replace `body: true/false` with
`body.enabled: true/false`, and move action-level `maxBodyBytes` into each
configured phase's `body.maxBytes`. This is a pre-release API revision, not a
conversion path for released objects.

Install the updated CRDs and compatible Agentio runtime, configure the named
provider, and then apply profiles using `httpCallout`. Verify request and
response behavior before depending on enforcement. Before rolling back to a
runtime without support, remove or replace callout-dependent policies; admission
of a profile is not proof that an older runtime enforces the action.

## Test Plan

For API implementation validation, run `make generate manifests`, compile the
API package with `go test ./api/v1alpha1`, and check `git diff --check`. API
package compilation alone does not exercise admission or runtime behavior.

Schema validation coverage should include both profile kinds: missing provider
or name, invalid names, header filters, disclosure defaults, body-size
boundaries, and rejection of the old boolean body shape. Confirm that this
action's schema contains no CEL rules and that admission does not enforce the
phase-presence or filter-exclusivity contracts. Follow-up runtime validation
must reject missing phases and empty or conflicting filter branches.

Follow-up runtime integration must cover request-only and response-only calls,
phase-specific disclosure, UTF-8 and oversized-body failures, missing and
wrong-type providers, timeouts and invalid decisions, the failure-strategy
matrix, immediate responses, mutations, and action ordering. These are runtime
acceptance criteria, not capabilities verified by this API-only PR.

## Implementation History

- 2026-10-20: Proposal added to agents PR #882 for the named HTTP callout API.
- Follow-up: consume the published API and enable the action in Agentio's
  production filter pipeline.
