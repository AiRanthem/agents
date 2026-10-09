# Change Log

## v0.6.0
> Change log since v0.3.0

Version range: v0.3.0 → v0.6.0

---

## 1. Features

### 1.1 Security Enhancement

**Network Policy & Egress Control**
- Added `TrafficPolicy`, `GlobalTrafficPolicy`, and `SecurityProfile` CRDs so sandbox egress can be declared and enforced centrally, completing protocol and scheme matching, admission validation, and CRD registration over the release (#397, #433, #445, #448, #483, #494, #521, #588, #610, #615, #745, #746, #915, #919, #930).
- SecurityProfile rules gained MCP tool access control (#614), header manipulation (#829), token-transformation headers (#859), and inline E2B L7 network rules (#838).
- TrafficPolicy pod selection is keyed on sandbox UID with a name fallback, preventing mis-targeting after sandbox recreation (#982).

**Authentication & Token Lifecycle**
- Added a feature-gated Security Identity Provider that issues and propagates sandbox access tokens end to end (#324, #450, #460, #463, #469). Issuance is gated on the `agent-name` label (#488), deferred until the sandbox is Ready (#642), and re-issued on resume, clone, and CSI re-mount (#633, #637, #638, #639, #671).
- Added proactive token rotation (#475, #742) and masked access tokens in route logs and debug output (#607).
- Gateway authentication supports JWT verification with optional runtime mTLS (#561, #648), preserves the UUID baseline when JWT is enabled (#885), and aligns its traffic token header with the E2B SDK (#689).

**TLS & Secure Transport**
- Added a gateway CA bundle injection framework covering containers and init containers (#478, #552); runtime clients negotiate TLS from Secret- or cert-manager-provided material (#702, #729, #994).
- CSI mounts (#720), the `/init` handshake (#700), security-token delivery (#734), and upgrade hooks (#886) all run over the resolved TLS transport, and every runtime call reports which transport was used (#752).
- Self-signed leaf certificates now carry SKI/AKI for Python 3.13+ clients (#797).

**Cluster Gossip & Supply-Chain Security**
- Manager and Gateway gossip supports memberlist encryption with peer mTLS (#967), configurable network-interface binding and reliable peer discovery (#920), and correct IPv6 upstream formatting (#901).
- CI now runs govulncheck, zizmor, and OpenSSF Scorecard with gosec enabled (#836); Tier-1 and Tier-2 code-scanning findings were resolved (#918, #921), including centralized path and log sanitizers plus strict POSIX path normalization for path- and log-injection alerts (#587, #928, #1044). A SECURITY.md policy was added (#606).

### 1.2 Operations Enhancement

**Checkpoint, Pause/Resume & Commit**
- Introduced `CheckpointControl` (#508) with a `CheckpointRestore` upgrade strategy (#670), filesystem-level `PersistentContents` (#674), selectable checkpoint labels (#712, #714), and a pause path that waits for in-flight checkpoints (#913).
- Introduced the `Commit` CRD and controller (#502, #533) with a nerdctl-based commit/push execution layer (#608); commit conditions are always recorded on terminal transitions (#1018) and provider/pod deletion rules were tightened (#595).
- Added `PauseStrategy` (Stop / Snapshot / CloudDisk) (#713, #774), exposed on `SandboxSet` (#839).
- Resume became atomic with a placeholder pause time and a minimum timeout floor (#435), reports post-resume re-initialization and CSI re-mount through events and conditions (#416), and surfaces clearer errors on cancellation (#424).
- Refined paused retention timeouts (#566), reduced the default failed-sandbox reserve TTL to 30 minutes (#457), and labeled checkpoints by sandbox UID with the name bounded to the 63-character label limit (#985).

**Upgrade & In-Place Update**
- Paused sandboxes can be upgraded through `SandboxUpdateOps` (#710) using a two-phase flow (#750) with the upgrade policy cleared on success (#785). Eligibility was broadened to sandboxes outside `SandboxSet` control (#482) and narrowed to Running/Upgrading candidates whose template differs from the target (#511, #553).
- Memory can be resized during claim (#519), injected resources survive resize (#462, #537), and unsupported in-place resize requests are distinguished from valid ones (#933).
- Fixed false-positive resource-change detection (#420, #557), stabilized init-container injection order (#513) and image-consistency verification (#538), and let resume upgrades continue from the previously failed step (#447).

**Observability, Events & Tracing**
- Added OpenTelemetry-based user-operation tracing that propagates across sandbox-manager, gateway, and controller, emits the trace ID as the first log field, and records Sandbox conditions on controller spans (#604, #950).
- New metrics for runtime container abnormality (#452) and abnormal-state duration (#591); metric cleanup moved off the reconcile hot path (#461).
- Added events and conditions for pod creation failures (#626), Kubernetes lifecycle events (#603), and controller/manager lifecycle tracing (#658); Pod status synchronization was generalized across controllers (#939).
- Reduced proxy and infra reconciler log volume (#579), added bounded streamed log capture (#987), and gave E2B an optional dedicated observability listener (#858).

**Startup Diagnostics & Serving**
- Startup failures now propagate to wait-ready and surface as `ScalingLimited` (#936), with unschedulable pods classified and reported in claim diagnostics before the pod-IP check (#942).
- Sandbox-manager loads secret-backed configuration at startup through a startup hook (#857) and waits for initial sandbox event handlers before serving (#1043).
- Probes are delivered through `PodProbeMarker` on real nodes and through the serverless annotation on virtual nodes (#1010).
- The manager service is exposed on port 8080 with matching gateway routing and ingress alignment (#993).

**Controller & SandboxSet**
- `SandboxSet` auto-creates `SandboxTemplate` (#396), uses a legacy revision hash to avoid recreating sandboxes on upgrade (#514), scopes `maxUnavailable` to a startup-failure budget (#910), sorts scale-down candidates by priority (#803), and propagates pool labels to Pods (#986).
- Sandbox finalizers became lazy — added on pause, removed on resume (#646); leftover pods from a previous same-name sandbox are rejected (#757); pod identity is stamped with the resolved sandbox name (#954).
- Status is persisted during the Pending phase (#455), the batch claim size flag takes effect (#656), and claims are scoped to namespace (#824).
- Added the `okactl` CLI for sandbox operations (#497) and multi-arch image publishing (#545).

**Performance & Caching**
- Stopped the Paused status-write hot loop and bounded stale-cache requeues (#972); reduced gateway informer cache memory (#724); the claim hot path now counts active sandboxes (#517).
- Secret-backed key storage switched from ticker polling to informer-driven refresh (#421); added APIReader fallbacks for claimed-sandbox lookup (#423) and checkpoint wait (#522); cache misses return definitively (#751); the TrafficPolicy cache is skipped when the CRD is absent (#730).

**E2B Compatibility**
- Added Claude Code support (#415), pod-IP metadata (#436), SDK-compatible API key encoding for E2B ≥ v2.25.0 (#473), named cloned sandboxes (#385), dynamically resolved sandbox domains (#649), and an unlimited default create-server timeout (#484).
- Added the Volume API (#580, #596), Network API (#616), dimension-aware API key quota (#565), a Secret-to-MySQL API key migration script (#309), and egress-control injection (#397). Volume management endpoints are temporarily disabled (#744).

**Storage & Runtime**
- Added RRSA-based storage authentication for on-demand CSI mounts (#568), an agent-runtime client with a CSI mount API (#685), atomic directory listing and removal (#723), a storage CLI (#539), and a per-sandbox CSI mount limit (#971).

**Short & Stable Sandbox IDs**
- Sandbox IDs are now short and stable across lifecycle operations, backed by a lock-free atomic max helper (#686, #766).

### 1.3 Cost Optimization

- **Sandbox recycle / return-to-pool** (#548, #569, #609) — reuse released sandboxes instead of paying for cold starts.
- **CheckpointRestore upgrade strategy** (#670, #674) — upgrade sandboxes from filesystem checkpoints rather than rebuilding them.
- **Auto-pause and resume** (#612, #899) with a probe-driven `AutoPausePolicy` (#899) and an `OnIngressTraffic` wake-on-traffic resume rule (#586, #900).
- **PoolAutoscaler** (#625) — capacity-based and cron-driven pool autoscaling with coordinated scale-up execution (#895); its feature gate is now enabled by default (#938).
- **Retention tuning** — refined paused retention (#566) and a 30-minute default reserve TTL for failed sandboxes (#457).
- **Hot-path reductions** — async metric cleanup (#461), active-sandbox counting on claim (#517), and the Paused status-write hot-loop fix (#972).

---

## 2. Bug Fixes

**Lifecycle & Status**
- `ClaimSandbox` no longer returns `(nil, nil)` on context cancellation (#399), and informer cache corruption from disabled deep-copy was removed (#387).
- Resume during pausing is rejected with 400 (#404); pausing sandboxes are allowed to pause (#422); resume decouples phase transition from pod readiness (#529); pause conditions were corrected for the checkpoint-disabled and pod-deleted paths (#524).
- Checkpoint delete expectations settle when the checkpoint is already gone (#812); checkpoints no longer leak when clone creation fails (#1008); clone honors the request CSI mount config over the checkpoint annotation (#641); a TTL leak was fixed by letting Checkpoint own SandboxTemplate (#419).
- Pod status is synced before upgrade initialization (#912); `SandboxSet` no longer reconciles while deleting (#856); invalid `SandboxClaim` retry loops were fixed (#840); sandbox cleanup falls back to SandboxManager on network-policy failure (#707); internal labels no longer leak into sandbox pod templates (#911).
- Auto-pause probe messages are trimmed before matching `messageRegex` (#1046), and an absent `RuntimeInitialized` is treated as serving during token refresh (#675).

**E2B Compatibility & API Keys**
- Dead sandboxes return 404 from `DescribeSandbox` so SDKs no longer raise (#636, #692); `is_running` is polled after kill to avoid an async-deletion race (#645); pagination is stable across duplicate timestamps (#563); reserved failed-sandbox cleanup was fixed (#589); traffic policy precedence was corrected (#740); resource ownership and key storage validation were hardened (#835).
- Invalid API key creation returns 400 (#449); the configured admin key is persisted and unreadable Secret entries are skipped (#854); API key persistence and owner labels were hardened (#677); registry secret lookup errors are propagated (#584).

**Controller / Webhook / CRD**
- Webhook controller queue bootstrap and server CertDir alignment (#654); `SandboxTemplate` webhook registration (#820); `PoolAutoscaler` webhook service (#917); SecurityProfile, GlobalSecurityProfile, and GlobalTrafficPolicy CRDs registered in kustomization (#915); TrafficPolicy cache setup skipped when the CRD is absent (#730); ops-template patch sanitization and checkpoint resume selection (#793).

**Gateway & Transport**
- Traffic token header aligned with the E2B SDK (#689); traffic tokens issued for cloned sandboxes (#728); UUID baseline preserved when JWT auth is enabled (#885); upgrade hooks use TLS (#886); IPv6 upstream addresses formatted correctly (#901); self-signed leaf certificates include SKI/AKI for Python 3.13+ (#797).

**Resource Leaks**
- Closed an unclosed `http.Response` body in the BrowserUse endpoint handler that leaked sockets (#708).

**Tests & CI**
- Stabilized flaky and non-repeatable tests across claim, resume, checkpoint conditions, quota fail-open, envoy ext_proc timeouts, background-command kill, and debug masking (#476, #592, #617, #634, #651, #816, #884, #906, #1016); retried E2B Build Image steps on runner resource failures (#647); added a free-disk-space step to the e2e-e2b-mysql workflow (#643); restored `go vet` and `make build` on master (#940); named `PatchFinalizer` in invalid-op panics for clearer failures (#965).

---

## 3. Chores

**Documentation & Proposals**
- Release notes for v0.3.0 (#383) and v0.6.0-alpha1 (#932); proposals for pause/resume checkpointing (#467), the checkpoint API extension (#966), sandbox reuse and return-to-pool (#547), CSI mount (#536), short and stable Sandbox IDs (#635), OpenTelemetry distributed tracing (#604), and agent identity for sandbox ingress authn and outbound traffic (#697); multi-agent development limits (#438) and agent guidance hierarchy (#655); deployment README link and zh-CN filename fixes (#970).

**CI & Test Infrastructure**
- Expanded E2E coverage for pinned E2B versions, sandbox-manager, create-with-labels, and command execution (#471, #518, #582); rewrote the pytest plugin architecture (#594); added a Kwok-based load-testing framework (#883) and `AgenticBucket`/`BucketSpace` coverage for open-source storage components (#817); updated the Envoy base image (#509).

**Refactors**
- Broke circular and layer-violating dependencies (#474); centralized path and log sanitizers (#928, #1044); generalized Pod status synchronization (#939); sidecar injection now takes `*Sandbox` (#480); security metadata is consumed from sandbox annotations (#630); token issuance no longer takes a request parameter (#632); sandbox "reuse" terminology was renamed to "recycle" (#609); E2B request context values use an unexported key type (#902).

**Tooling & Runtime Scripts**
- Added and refined the sync-charts skill for CRD, webhook, RBAC, and identity synchronization, including manager CRD wrapped-chart tracking and manifests drift policy (#916, #944); tracked `.agents/` for tool-agnostic agent assets; runtime script updates for `run_envd.sh` / `envd-run.sh` (#516, #541), file permissions (#486), and command timeouts (#503).

**Generated Code**
- Regenerated client (#417) and relocated security-related files (#456).

---

## New Contributors
* @oindrilakha12-ui made their first contribution in https://github.com/openkruise/agents/pull/387
* @Kuromesi made their first contribution in https://github.com/openkruise/agents/pull/397
* @l1b0k made their first contribution in https://github.com/openkruise/agents/pull/433
* @rakshaak29 made their first contribution in https://github.com/openkruise/agents/pull/442
* @zyl1121 made their first contribution in https://github.com/openkruise/agents/pull/447
* @delavet made their first contribution in https://github.com/openkruise/agents/pull/483
* @Liquorice-Ma made their first contribution in https://github.com/openkruise/agents/pull/497
* @silver-chard made their first contribution in https://github.com/openkruise/agents/pull/537
* @googs1025 made their first contribution in https://github.com/openkruise/agents/pull/545
* @Jayant-kernel made their first contribution in https://github.com/openkruise/agents/pull/558
* @zhuangzhewei09 made their first contribution in https://github.com/openkruise/agents/pull/563
* @ashnaaseth2325-oss made their first contribution in https://github.com/openkruise/agents/pull/584
* @denverdino made their first contribution in https://github.com/openkruise/agents/pull/587
* @yanghanlin made their first contribution in https://github.com/openkruise/agents/pull/594
* @singhsrijan46 made their first contribution in https://github.com/openkruise/agents/pull/613
* @chrisliu1995 made their first contribution in https://github.com/openkruise/agents/pull/625
* @ZeroCoder-dot made their first contribution in https://github.com/openkruise/agents/pull/673
* @AlbeeSo made their first contribution in https://github.com/openkruise/agents/pull/676
* @vishalmore90 made their first contribution in https://github.com/openkruise/agents/pull/708
* @HARSHRAJ2789 made their first contribution in https://github.com/openkruise/agents/pull/790
* @nishantbkl3345-ship-it made their first contribution in https://github.com/openkruise/agents/pull/798
* @DahuK made their first contribution in https://github.com/openkruise/agents/pull/836
* @jiaming2li made their first contribution in https://github.com/openkruise/agents/pull/883
* @RedZapdos123 made their first contribution in https://github.com/openkruise/agents/pull/886
* @ywExcellent made their first contribution in https://github.com/openkruise/agents/pull/895
* @cyrilcsr made their first contribution in https://github.com/openkruise/agents/pull/901
* @omlahore made their first contribution in https://github.com/openkruise/agents/pull/902
* @harkiratsm made their first contribution in https://github.com/openkruise/agents/pull/965
* @nce3xin made their first contribution in https://github.com/openkruise/agents/pull/966
* @u7k4rs6 made their first contribution in https://github.com/openkruise/agents/pull/1016

**Full Changelog**: https://github.com/openkruise/agents/compare/v0.3.0...v0.6.0

## v0.3.0
> Change log since v0.2.0

### Key Features
- Implemented rolling update support for SandboxSet with configurable maxUnavailable policy. ([#256](https://github.com/openkruise/agents/pull/256), [@BITLiutianyang](https://github.com/BITLiutianyang))
- Introduced pluggable KeyStorage with MySQL backend for E2B API key management. ([#291](https://github.com/openkruise/agents/pull/291), [@AiRanthem](https://github.com/AiRanthem))
- Added team-based namespace isolation and team-scoped API key authorization for multi-tenant support. ([#325](https://github.com/openkruise/agents/pull/325), [@AiRanthem](https://github.com/AiRanthem))
- Added Kruise custom path-based routing protocol in sandbox-gateway, supporting `/kruise/{namespace}--{sandbox-name}/{port}/{user-defined-path}` URL format to route requests directly to sandbox pods with path rewrite. ([#278](https://github.com/openkruise/agents/pull/278), [@chengzhycn](https://github.com/chengzhycn))
- Added in-place CPU resize capability when claiming warm pool sandboxes via SandboxClaim or E2B Create API, allowing resource reconfiguration without pod recreation. ([#228](https://github.com/openkruise/agents/pull/228), [@PersistentJZH](https://github.com/PersistentJZH))
- Implemented Recreate upgrade strategy for Sandbox with preUpgrade/postUpgrade lifecycle hooks support. ([#302](https://github.com/openkruise/agents/pull/302), [@zmberg](https://github.com/zmberg))
- Introduced SandboxUpdateOps CR for batch upgrading claimed sandboxes with lifecycle hooks support. ([#307](https://github.com/openkruise/agents/pull/307), [@zmberg](https://github.com/zmberg))
- Added E2B-compatible `GET /templates` and `GET /templates/{templateID}` API endpoints for SandboxTemplate listing and retrieval. ([#265](https://github.com/openkruise/agents/pull/265), [@ZhaoQing7892](https://github.com/ZhaoQing7892))

### Performance Improvements
- Added strategic merge patch markers to CRD types to improve kubectl apply performance and reduce API server load. ([#372](https://github.com/openkruise/agents/pull/372), [@zmberg](https://github.com/zmberg))
- Optimized CSI mounting logic from serial to parallel mounting capability for faster sandbox creation. ([#290](https://github.com/openkruise/agents/pull/290), [@BH4AWS](https://github.com/BH4AWS))
- Added feature gate to cache PodLabelSelector for performance optimization. ([#259](https://github.com/openkruise/agents/pull/259), [@PersistentJZH](https://github.com/PersistentJZH))

### Observability & Metrics
- Added Prometheus metrics for Sandbox, SandboxClaim, SandboxSet and sandbox-manager lifecycle observability. ([#258](https://github.com/openkruise/agents/pull/258), [@liangxiaoping](https://github.com/liangxiaoping); [#292](https://github.com/openkruise/agents/pull/292), [@KeyOfSpectator](https://github.com/KeyOfSpectator))
- Improved claim sandbox failure diagnostics by recording retry pick failures with sandbox key and reason in ClaimMetrics, and exposing aggregated diagnostics in E2B CreateSandbox API errors. ([#356](https://github.com/openkruise/agents/pull/356), [@AiRanthem](https://github.com/AiRanthem))

### Other Notable Changes
#### sandbox-controller
- Added support for negative TTL in SandboxClaim to prevent automatic deletion of the SandboxClaim CR. ([#277](https://github.com/openkruise/agents/pull/277), [@AiRanthem](https://github.com/AiRanthem))
- Introduced SandboxMultiClusterNaming feature gate to embed cluster ID hash in sandbox generateName prefix, preventing name collisions across clusters. ([#370](https://github.com/openkruise/agents/pull/370), [@zmberg](https://github.com/zmberg))
- Added CSI dynamic remounting when resuming sandbox to ensure consistent mount state. ([#305](https://github.com/openkruise/agents/pull/305), [@BH4AWS](https://github.com/BH4AWS))

#### sandbox-manager
- Added custom CDP port support for BrowserUse API, allowing users to specify a cdpPort query parameter to proxy Chrome DevTools Protocol requests. ([#298](https://github.com/openkruise/agents/pull/298), [@AiRanthem](https://github.com/AiRanthem))
- Added support for updating Sandbox and Pod labels during E2B Create Sandbox. ([#201](https://github.com/openkruise/agents/pull/201), [@furykerry](https://github.com/furykerry))

#### Bug Fixes
- Fixed unnecessary InitRuntime execution when no agent-runtime is configured in Sandbox. ([#340](https://github.com/openkruise/agents/pull/340), [@zmberg](https://github.com/zmberg))
- Fixed E2B connect timeout extension semantics to properly handle sandbox lifecycle timeouts. ([#303](https://github.com/openkruise/agents/pull/303), [@AiRanthem](https://github.com/AiRanthem))
- Fixed pause/resume operations to be concurrency-safe under parallel requests. ([#358](https://github.com/openkruise/agents/pull/358), [@AiRanthem](https://github.com/AiRanthem))
- Fixed templateRef sandbox hashing to avoid nil template panic. ([#260](https://github.com/openkruise/agents/pull/260), [@PersistentJZH](https://github.com/PersistentJZH))
- Fixed volume injection issue when user already specified posthook containers. ([#279](https://github.com/openkruise/agents/pull/279), [@BH4AWS](https://github.com/BH4AWS))
- Fixed panic when logging sidecar config errors. ([#301](https://github.com/openkruise/agents/pull/301), [@lxs137](https://github.com/lxs137))
- Updated EnvdVersion from 0.1.1 to 0.2.10 for compatibility. ([#276](https://github.com/openkruise/agents/pull/276), [@AiRanthem](https://github.com/AiRanthem))
- Fixed checkpoint not recording CSI mount state, causing cloned pods to fail mounting. ([#275](https://github.com/openkruise/agents/pull/275), [@BH4AWS](https://github.com/BH4AWS))

#### Security
- Reduced filesystem permissions for certificate and key files to prevent unauthorized access. ([#330](https://github.com/openkruise/agents/pull/330), [@PRAteek-singHWY](https://github.com/PRAteek-singHWY))

### Misc (Chores and tests)
- Added validation for TTLAfterCompleted and WaitReadyTimeout parameters. ([#361](https://github.com/openkruise/agents/pull/361), [@BH4AWS](https://github.com/BH4AWS))
- Implemented validation for SandboxSet volume claim template mounts. ([#359](https://github.com/openkruise/agents/pull/359), [@ajatshatru01](https://github.com/ajatshatru01))
- Added Claude Code deployment guide for AI agent sandbox integration. ([#334](https://github.com/openkruise/agents/pull/334), [@bcfre](https://github.com/bcfre))
- Added comprehensive roadmap for future development. ([#271](https://github.com/openkruise/agents/pull/271), [@furykerry](https://github.com/furykerry))
- Added code-reviewer agents and OWNERS file for maintainership clarity. ([#310](https://github.com/openkruise/agents/pull/310), [@furykerry](https://github.com/furykerry))
- Added fmt-imports.sh script and applied formatting across codebase. ([#272](https://github.com/openkruise/agents/pull/272), [@PersistentJZH](https://github.com/PersistentJZH))

## v0.2.0
> Change log since v0.1.0

### Key Features
- Introduced the sandbox-gateway component to separate the data plane (ingress traffic handling) from the component sandbox-manager, enhancing system stability and fault isolation. ([#203](https://github.com/openkruise/agents/pull/203), [@chengzhycn](https://github.com/chengzhycn))
- Added support for mounting multiple NAS/OSS volumes dynamically. ([#211](https://github.com/openkruise/agents/pull/211), [@BH4AWS](https://github.com/BH4AWS))
- Enhanced E2B APIs with snapshot and clone capabilities. ([#204](https://github.com/openkruise/agents/pull/204), [@AiRanthem](https://github.com/AiRanthem))
- Implemented paginated listing and deletion of snapshots. ([#233](https://github.com/openkruise/agents/pull/233), [@AiRanthem](https://github.com/AiRanthem))
- Added protection to prevent unauthorized deletion of Sandbox Pods, and only the sandbox controller may delete them. ([#214](https://github.com/openkruise/agents/pull/214), [@zmberg](https://github.com/zmberg))
- Enabled CSI volume mounting during sandbox creation via SandboxClaim. ([#229](https://github.com/openkruise/agents/pull/229), [@BH4AWS](https://github.com/BH4AWS))
- Added support for automatically injecting runtime and CSI sidecar containers based on sandbox ConfigMap configuration. ([#232](https://github.com/openkruise/agents/pull/232), [@BH4AWS](https://github.com/BH4AWS))

### Performance Improvements
- Improved performance in large-scale sandbox creation scenarios by optimizing ListSandboxesInPool using singleflight deduplication. ([#186](https://github.com/openkruise/agents/pull/186), [@AiRanthem](https://github.com/AiRanthem))
- Introduced feature gate SandboxCreatePodRateLimitGate to enable prioritized sandbox pod creation. ([#171](https://github.com/openkruise/agents/pull/171), [@zmberg](https://github.com/zmberg))

### Other Notable Changes
#### agents-sandbox-manager
- Extended the E2B CreateSandbox API with the e2b.agents.kruise.io/never-timeout annotation to support sandboxes that never auto-delete. ([#183](https://github.com/openkruise/agents/pull/183), [@AiRanthem](https://github.com/AiRanthem))
- Enabled CreateOnNoStock by default when claiming a sandbox. ([#187](https://github.com/openkruise/agents/pull/187), [@AiRanthem](https://github.com/AiRanthem))
- Removed default timeout assignment for paused sandboxes, preventing automatic deletion. ([#196](https://github.com/openkruise/agents/pull/196), [@AiRanthem](https://github.com/AiRanthem))
- Sandbox Manager now supports filtering sandbox-related custom resources via configurable sandbox-namespace and sandbox-label-selector. ([#217](https://github.com/openkruise/agents/pull/217), [@lxs137](https://github.com/lxs137))

#### agents-sandbox-controller
- Add flag parsing support (e.g., -v) for configurable logging verbosity. ([#184](https://github.com/openkruise/agents/pull/184), [@songtao98](https://github.com/songtao98))
- Add label selector for Pod informer to reduce cache size. ([#198](https://github.com/openkruise/agents/pull/198), [@PersistentJZH](https://github.com/PersistentJZH))

### Misc (Chores and tests)
- Docs: add OpenClaw deployment guide. ([#235](https://github.com/openkruise/agents/pull/235), [@bcfre](https://github.com/bcfre))
- docs(AGENTS): add AGENTS.md. ([#237](https://github.com/openkruise/agents/pull/237), [@AiRanthem](https://github.com/AiRanthem))
- Add sandboxSet Prometheus metrics. ([#223](https://github.com/openkruise/agents/pull/223), [@ZhaoQing7892](https://github.com/ZhaoQing7892))
- agent(skills): add detailed deployment skill for Qoder. ([#170](https://github.com/openkruise/agents/pull/170), [@AiRanthem](https://github.com/AiRanthem))

## v0.1.0
### agents-sandbox-controller
- Define and manage sandboxes declaratively using the new Sandbox, SandboxClaim APIs.
- Improve performance with SandboxSet, allowing for faster sandbox creation.

### agents-sandbox-manager
- Supports the E2B mainstream protocol, providing core capabilities such as Agent sandbox creation, routing, and management.
- Extend the E2B protocol to support in-place update image and dynamic mounting of NAS/OSS within the sandbox.
